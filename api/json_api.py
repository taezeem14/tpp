from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from typing import Any

from tpp.core.errors import TppError, render_error
from tpp.runtime.engine import EngineConfig, RuntimeEngine


def execute_json_request(payload: dict[str, Any]) -> dict[str, Any]:
    parser_mode = str(payload.get("parser_mode", "fuzzy"))
    debug_trace = bool(payload.get("debug_trace", False))
    profiling = bool(payload.get("profiling", False))

    engine = RuntimeEngine(
        EngineConfig(
            parser_mode=parser_mode,
            debug_trace=debug_trace,
            profiling=profiling,
            optimize=bool(payload.get("optimize", True)),
            strict_semantic_resolution=bool(payload.get("strict_semantic_resolution", False)),
            allow_python_bridge=bool(payload.get("allow_python_bridge", True)),
        )
    )

    for plugin_path in payload.get("plugins", []) or []:
        engine.load_plugin(str(plugin_path))

    mode = str(payload.get("mode", "run"))
    source = str(payload.get("source", ""))

    out = io.StringIO()
    response: dict[str, Any] = {"ok": True, "mode": mode}

    try:
        with redirect_stdout(out):
            if mode == "run":
                engine.run_source(source)
            elif mode == "test":
                program = engine.parse_source(source)
                results, passed, failed = engine.run_tests(program, verbose=False)
                response["tests"] = [
                    {
                        "name": item.name,
                        "passed": item.passed,
                        "duration_ms": item.duration_ms,
                        "details": item.details,
                    }
                    for item in results
                ]
                response["summary"] = {"passed": passed, "failed": failed}
                response["ok"] = failed == 0
            elif mode == "manifest":
                response["manifest"] = engine.manifest()
            else:
                raise ValueError(f"Unsupported api mode '{mode}'")
    except Exception as exc:
        response["ok"] = False
        response["error"] = render_error(exc, debug_trace=debug_trace)
        if isinstance(exc, TppError):
            response["error_category"] = exc.category

    response["stdout"] = out.getvalue()
    if profiling:
        response["profiling"] = engine.profiler.report()
    return response


def execute_json_payload_text(payload_text: str) -> str:
    payload = json.loads(payload_text)
    result = execute_json_request(payload)
    return json.dumps(result, indent=2)
