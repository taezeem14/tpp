from __future__ import annotations

import importlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from tpp.core.ast_nodes import FunctionDefStmt, Program
from tpp.core.errors import PluginTppError, SecurityTppError
from tpp.core.utils import normalize_phrase


@dataclass
class PluginMetadata:
    name: str
    version: str
    dependencies: list[str] = field(default_factory=list)


class PluginManager:
    def __init__(self) -> None:
        self.loaded_plugins: dict[str, PluginMetadata] = {}
        self.keyword_rewrites: dict[str, str] = {}
        self.keywords: set[str] = set()
        self.ast_transforms: list[Callable[[Program], Program]] = []

    def snapshot_keywords(self) -> tuple[dict[str, str], set[str]]:
        return dict(self.keyword_rewrites), set(self.keywords)

    def load_file(self, path: str | Path) -> PluginMetadata:
        plugin_path = Path(path)
        if not plugin_path.exists():
            raise PluginTppError(f"Plugin file '{plugin_path}' does not exist.")

        try:
            data = json.loads(plugin_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PluginTppError(f"Plugin file '{plugin_path}' is not valid JSON: {exc}") from exc

        metadata, keywords, transforms, python_hooks = self._normalize_plugin_payload(data, plugin_path)

        missing_deps = [dep for dep in metadata.dependencies if dep not in self.loaded_plugins]
        if missing_deps:
            raise PluginTppError(
                f"Plugin '{metadata.name}' is missing dependencies: {', '.join(missing_deps)}",
                suggestion="Load dependency plugins first.",
            )

        for phrase, template in keywords:
            norm = normalize_phrase(phrase)
            self.keywords.add(norm)
            if template is not None:
                self.keyword_rewrites[norm] = template

        for transform in transforms:
            self.ast_transforms.append(self._build_builtin_transform(transform, metadata.name))

        for hook in python_hooks:
            self.ast_transforms.append(self._load_python_transform(hook, metadata.name))

        self.loaded_plugins[metadata.name] = metadata
        return metadata

    def install_plugin(self, source_path: str | Path, install_dir: str | Path) -> Path:
        source = Path(source_path)
        if not source.exists():
            raise PluginTppError(f"Plugin source '{source}' does not exist.")
        if source.suffix.lower() != ".json":
            raise PluginTppError("Only JSON plugin files are supported for install.")

        target_dir = Path(install_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / source.name
        shutil.copy2(source, target_path)
        return target_path

    def apply_ast_transforms(self, program: Program) -> Program:
        transformed = program
        for transform in self.ast_transforms:
            transformed = transform(transformed)
        return transformed

    def _normalize_plugin_payload(
        self,
        data: Any,
        plugin_path: Path,
    ) -> tuple[PluginMetadata, list[tuple[str, str | None]], list[dict[str, Any]], list[dict[str, Any]]]:
        if isinstance(data, dict) and "name" in data:
            name = str(data.get("name", "")).strip()
            version = str(data.get("version", "0.0.0")).strip() or "0.0.0"
            dependencies = [str(dep).strip() for dep in data.get("dependencies", []) if str(dep).strip()]
            metadata = PluginMetadata(name=name, version=version, dependencies=dependencies)

            if not metadata.name:
                raise PluginTppError(f"Plugin '{plugin_path}' is missing a valid name.")

            keywords: list[tuple[str, str | None]] = []
            raw_keywords = data.get("keywords", [])
            for entry in raw_keywords:
                if isinstance(entry, str):
                    keywords.append((entry, None))
                elif isinstance(entry, dict):
                    phrase = str(entry.get("phrase") or entry.get("keyword") or "").strip()
                    template = entry.get("template")
                    if not phrase:
                        continue
                    keywords.append((phrase, str(template).strip() if isinstance(template, str) else None))

            transforms = [item for item in data.get("transforms", []) if isinstance(item, dict)]
            python_hooks = [item for item in data.get("python_hooks", []) if isinstance(item, dict)]
            return metadata, keywords, transforms, python_hooks

        # Backward-compatible simple plugin formats
        metadata = PluginMetadata(name=plugin_path.stem, version="0.0.0")
        keywords: list[tuple[str, str | None]] = []
        if isinstance(data, dict):
            if "keywords" in data and isinstance(data["keywords"], list):
                for entry in data["keywords"]:
                    if isinstance(entry, str):
                        keywords.append((entry, None))
                    elif isinstance(entry, dict):
                        phrase = str(entry.get("phrase") or entry.get("keyword") or "").strip()
                        template = entry.get("template")
                        if phrase:
                            keywords.append((phrase, str(template).strip() if isinstance(template, str) else None))
            else:
                for phrase, template in data.items():
                    keywords.append((str(phrase), str(template) if template is not None else None))
        elif isinstance(data, list):
            for entry in data:
                if isinstance(entry, str):
                    keywords.append((entry, None))
                elif isinstance(entry, dict):
                    phrase = str(entry.get("phrase") or entry.get("keyword") or "").strip()
                    template = entry.get("template")
                    if phrase:
                        keywords.append((phrase, str(template).strip() if isinstance(template, str) else None))

        return metadata, keywords, [], []

    def _build_builtin_transform(self, transform_spec: dict[str, Any], plugin_name: str) -> Callable[[Program], Program]:
        transform_type = str(transform_spec.get("type", "")).strip()

        if transform_type == "rename_function":
            old_name = str(transform_spec.get("from", "")).strip()
            new_name = str(transform_spec.get("to", "")).strip()
            if not old_name or not new_name:
                raise PluginTppError(
                    f"Plugin '{plugin_name}' has an invalid rename_function transform.",
                    suggestion="Provide both 'from' and 'to' names.",
                )

            def transform(program: Program) -> Program:
                for statement in program.statements:
                    if isinstance(statement, FunctionDefStmt) and statement.name == old_name:
                        statement.name = new_name
                return program

            return transform

        raise PluginTppError(
            f"Plugin '{plugin_name}' requested unknown transform type '{transform_type}'.",
            suggestion="Use a supported builtin transform or python_hooks.",
        )

    def _load_python_transform(self, hook_spec: dict[str, Any], plugin_name: str) -> Callable[[Program], Program]:
        module_name = str(hook_spec.get("module", "")).strip()
        callable_name = str(hook_spec.get("callable", "")).strip()

        if not module_name.startswith("tpp_plugins."):
            raise SecurityTppError(
                f"Plugin '{plugin_name}' attempted to load unsafe module '{module_name}'.",
                suggestion="Python hooks must live under the 'tpp_plugins.' namespace.",
            )

        if not callable_name:
            raise PluginTppError(f"Plugin '{plugin_name}' python hook is missing callable name.")

        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise PluginTppError(f"Could not import plugin hook module '{module_name}': {exc}") from exc

        if not hasattr(module, callable_name):
            raise PluginTppError(f"Plugin hook '{module_name}.{callable_name}' was not found.")

        hook = getattr(module, callable_name)
        if not callable(hook):
            raise PluginTppError(f"Plugin hook '{module_name}.{callable_name}' is not callable.")

        def transform(program: Program) -> Program:
            result = hook(program)
            if result is None:
                return program
            if not isinstance(result, Program):
                raise PluginTppError(
                    f"Plugin hook '{module_name}.{callable_name}' returned an invalid value.",
                    suggestion="Return Program or None.",
                )
            return result

        return transform
