#!/usr/bin/env python3
"""Build a machine-readable codebase graph for Math Agent.

The output is intended for coding agents and lightweight tooling:
- file-level structure
- symbol inventory
- internal import edges
- test-to-source edges
- curated task routing and execution-path hints
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import tomllib


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[2]
OUTPUT_PATH = SCRIPT_PATH.with_name("codebase-graph.json")
SRC_ROOT = PROJECT_ROOT / "src"

EXCLUDED_PARTS = {
    ".git",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    "runs",
    "AGENT",
    ".cache",
}

SOURCE_EXTENSIONS = {".py", ".md", ".toml", ".json"}
TOP_LEVEL_INCLUDE = {"README.md", "AGENT.md", "pyproject.toml", ".gitignore"}

EXECUTION_PATHS = [
    "src/math_agent/main.py",
    "src/math_agent/config.py",
    "src/math_agent/orchestrator/coordinator.py",
    "src/math_agent/orchestrator/phase1.py",
    "src/math_agent/runtime/factory.py",
    "src/math_agent/documents/memo.py",
    "src/math_agent/documents/notes.py",
]

TASK_ROUTES = [
    {
        "task": "cli_launch_or_eval",
        "paths": [
            "src/math_agent/main.py",
            "src/math_agent/config.py",
            "src/math_agent/eval/harness.py",
            "configs/default.toml",
            "pyproject.toml",
        ],
        "notes": "CLI flags, run launch, resume, eval dispatch, and visible console output.",
    },
    {
        "task": "runtime_backends",
        "paths": [
            "src/math_agent/runtime/base.py",
            "src/math_agent/runtime/factory.py",
            "src/math_agent/runtime/codex.py",
            "src/math_agent/runtime/claude.py",
            "src/math_agent/runtime/api.py",
        ],
        "notes": "CLI and API backend execution, retries, session handling, and runtime session construction.",
    },
    {
        "task": "phase1_orchestration",
        "paths": [
            "src/math_agent/orchestrator/coordinator.py",
            "src/math_agent/orchestrator/phase1.py",
            "src/math_agent/context/prompt_assembler.py",
            "src/math_agent/context/compression.py",
        ],
        "notes": "Run lifecycle, roadmap generation loop, review/falsifier flow, prompt assembly ladders, and resume behavior.",
    },
    {
        "task": "memory_and_resume",
        "paths": [
            "src/math_agent/documents/memo.py",
            "src/math_agent/documents/notes.py",
            "src/math_agent/orchestrator/phase1.py",
            "tests/test_orchestrator/test_phase1_resume.py",
        ],
        "notes": "Persistent proof state, proof notes, and resume-from-MEMO logic.",
    },
    {
        "task": "lean_verification",
        "paths": [
            "src/math_agent/orchestrator/coordinator.py",
            "src/math_agent/lean/toolplane.py",
            "src/math_agent/lean/compiler.py",
            "src/math_agent/lean/project.py",
            "tests/test_orchestrator/test_coordinator.py",
            "tests/test_lean/test_compiler.py",
        ],
        "notes": "Optional Lean statement/sketch checks and shared-workspace bootstrap/reuse.",
    },
    {
        "task": "agent_prompts_and_parsing",
        "paths": [
            "src/math_agent/agents/thinking.py",
            "src/math_agent/agents/formalizer.py",
            "src/math_agent/agents/assistant.py",
            "src/math_agent/agents/review.py",
            "src/math_agent/agents/falsifier.py",
            "src/math_agent/agents/base.py",
            "src/math_agent/agents/prompt_loader.py",
            "src/math_agent/agents/prompts/thinking_bundle.md",
        ],
        "notes": "Agent request payloads, parser contracts, and prompt text.",
    },
    {
        "task": "problem_registry",
        "paths": [
            "src/math_agent/problem/spec.py",
        ],
        "notes": "Built-in problems and suites.",
    },
    {
        "task": "agent_docs",
        "paths": [
            "AGENT.md",
            "README.md",
        ],
        "notes": "Agent-facing and human-facing orientation docs.",
    },
    {
        "task": "tests",
        "paths": [
            "tests/test_agents/test_prompts.py",
            "tests/test_agents/test_review.py",
            "tests/test_agents/test_thinking.py",
            "tests/test_context/test_prompt_assembler.py",
            "tests/test_context/test_compression.py",
            "tests/test_documents/test_memory.py",
            "tests/test_orchestrator/test_coordinator.py",
            "tests/test_orchestrator/test_phase1_resume.py",
            "tests/test_runtime/test_runtime_config.py",
            "tests/test_eval/test_harness.py",
        ],
        "notes": "High-signal regression coverage.",
    },
]


def file_id(path: str) -> str:
    return f"file:{path}"


def symbol_id(module: str, qualname: str) -> str:
    return f"symbol:{module}:{qualname}"


def route_id(name: str) -> str:
    return f"route:{name}"


def entrypoint_id(name: str) -> str:
    return f"entrypoint:{name}"


def path_is_included(path: Path) -> bool:
    rel = path.relative_to(PROJECT_ROOT)
    if any(part in EXCLUDED_PARTS for part in rel.parts):
        return False
    if rel.as_posix() in TOP_LEVEL_INCLUDE:
        return True
    if rel.parts and rel.parts[0] in {"src", "tests", "configs"}:
        return path.suffix in SOURCE_EXTENSIONS
    return False


def iter_project_files() -> list[Path]:
    candidates: list[Path] = []
    for path in PROJECT_ROOT.rglob("*"):
        if path.is_dir():
            continue
        if path_is_included(path):
            candidates.append(path)
    return sorted(candidates)


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def first_line(text: str | None) -> str | None:
    if not text:
        return None
    for line in text.splitlines():
        value = line.strip().lstrip("#").strip()
        if value:
            return value
    return None


def detect_kind(rel_path: str) -> str:
    if rel_path.endswith(".py"):
        return "python_test" if rel_path.startswith("tests/") else "python"
    if rel_path.endswith(".md"):
        return "prompt_markdown" if "prompts/" in rel_path else "markdown"
    if rel_path.endswith(".toml"):
        return "config"
    if rel_path.endswith(".json"):
        return "json"
    return "file"


def file_tags(rel_path: str) -> list[str]:
    tags: list[str] = []
    if rel_path == "src/math_agent/main.py":
        tags.extend(["entrypoint", "cli"])
    if "/orchestrator/" in rel_path:
        tags.append("orchestration")
    if "/documents/" in rel_path:
        tags.append("memory")
    if "/runtime/" in rel_path:
        tags.append("runtime")
    if "/agents/" in rel_path:
        tags.append("agent")
    if "/context/" in rel_path:
        tags.append("context")
    if rel_path.startswith("tests/"):
        tags.append("test")
    if rel_path.startswith("configs/") or rel_path == "pyproject.toml":
        tags.append("config")
    return sorted(set(tags))


def module_name_for(path: Path) -> str | None:
    rel = path.relative_to(PROJECT_ROOT)
    if rel.suffix != ".py":
        return None
    if rel.parts[0] == "src":
        inner = rel.relative_to("src").with_suffix("")
    elif rel.parts[0] == "tests":
        inner = rel.with_suffix("")
    else:
        return None
    parts = list(inner.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def end_lineno(node: ast.AST) -> int | None:
    return getattr(node, "end_lineno", None)


def doc_summary(node: ast.AST) -> str | None:
    return first_line(ast.get_docstring(node))


def internal_module_to_paths(module: str) -> list[str]:
    if not module.startswith("math_agent"):
        return []
    parts = module.split(".")
    candidate_file = Path("src") / Path(*parts)
    file_path = candidate_file.with_suffix(".py")
    init_path = candidate_file / "__init__.py"
    results: list[str] = []
    if (PROJECT_ROOT / file_path).exists():
        results.append(file_path.as_posix())
    if (PROJECT_ROOT / init_path).exists():
        results.append(init_path.as_posix())
    return results


def resolve_import_module(current_module: str | None, node: ast.ImportFrom) -> str | None:
    module = node.module or ""
    if node.level <= 0:
        return module or None
    if not current_module:
        return None
    parts = current_module.split(".")
    prefix = parts[:-node.level]
    if module:
        prefix.extend(module.split("."))
    return ".".join(prefix) or None


def parse_python_file(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    rel_path = path.relative_to(PROJECT_ROOT).as_posix()
    module = module_name_for(path)
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=rel_path)

    imports: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(
                    {
                        "module": alias.name,
                        "alias": alias.asname,
                        "lineno": node.lineno,
                    }
                )
        elif isinstance(node, ast.ImportFrom):
            resolved = resolve_import_module(module, node)
            imports.append(
                {
                    "module": resolved,
                    "raw_module": node.module,
                    "level": node.level,
                    "names": [alias.name for alias in node.names],
                    "lineno": node.lineno,
                }
            )

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = node.name
            symbols.append(
                {
                    "id": symbol_id(module or rel_path, qualname),
                    "file_id": file_id(rel_path),
                    "module": module,
                    "qualname": qualname,
                    "name": node.name,
                    "symbol_type": "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                    "lineno": node.lineno,
                    "end_lineno": end_lineno(node),
                    "summary": doc_summary(node),
                }
            )
        elif isinstance(node, ast.ClassDef):
            class_qualname = node.name
            symbols.append(
                {
                    "id": symbol_id(module or rel_path, class_qualname),
                    "file_id": file_id(rel_path),
                    "module": module,
                    "qualname": class_qualname,
                    "name": node.name,
                    "symbol_type": "class",
                    "lineno": node.lineno,
                    "end_lineno": end_lineno(node),
                    "summary": doc_summary(node),
                }
            )
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualname = f"{node.name}.{child.name}"
                    symbols.append(
                        {
                            "id": symbol_id(module or rel_path, qualname),
                            "file_id": file_id(rel_path),
                            "module": module,
                            "qualname": qualname,
                            "name": child.name,
                            "symbol_type": "method",
                            "lineno": child.lineno,
                            "end_lineno": end_lineno(child),
                            "summary": doc_summary(child),
                        }
                    )

    module_doc = doc_summary(tree)
    file_record = {
        "id": file_id(rel_path),
        "path": rel_path,
        "kind": detect_kind(rel_path),
        "module": module,
        "line_count": len(text.splitlines()),
        "size_bytes": len(text.encode("utf-8")),
        "sha1": sha1_text(text),
        "summary": module_doc or first_line(text),
        "tags": file_tags(rel_path),
        "imports": imports,
    }
    return file_record, symbols, imports


def parse_non_python_file(path: Path) -> dict[str, Any]:
    rel_path = path.relative_to(PROJECT_ROOT).as_posix()
    text = path.read_text(encoding="utf-8")
    return {
        "id": file_id(rel_path),
        "path": rel_path,
        "kind": detect_kind(rel_path),
        "module": None,
        "line_count": len(text.splitlines()),
        "size_bytes": len(text.encode("utf-8")),
        "sha1": sha1_text(text),
        "summary": first_line(text),
        "tags": file_tags(rel_path),
        "imports": [],
    }


def load_entrypoints() -> list[dict[str, Any]]:
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    if not pyproject_path.exists():
        return []
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    scripts = data.get("project", {}).get("scripts", {})
    results: list[dict[str, Any]] = []
    for name, target in sorted(scripts.items()):
        module_name, _, object_name = target.partition(":")
        target_paths = internal_module_to_paths(module_name)
        results.append(
            {
                "id": entrypoint_id(name),
                "name": name,
                "target": target,
                "module": module_name,
                "object": object_name or None,
                "file_paths": target_paths,
            }
        )
    return results


def build_graph() -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    path_to_file: dict[str, dict[str, Any]] = {}
    symbol_lookup: dict[tuple[str, str], dict[str, Any]] = {}

    for path in iter_project_files():
        if path.suffix == ".py":
            file_record, file_symbols, imports = parse_python_file(path)
            files.append(file_record)
            symbols.extend(file_symbols)
            for symbol in file_symbols:
                if symbol["module"]:
                    symbol_lookup[(symbol["module"], symbol["name"])] = symbol
            for symbol in file_symbols:
                edges.append(
                    {
                        "source": file_record["id"],
                        "target": symbol["id"],
                        "type": "defines",
                    }
                )
            for import_record in imports:
                module = import_record.get("module")
                if not module:
                    continue
                target_paths = internal_module_to_paths(module)
                for target_path in target_paths:
                    edge_type = "tests" if file_record["kind"] == "python_test" else "imports"
                    edges.append(
                        {
                            "source": file_record["id"],
                            "target": file_id(target_path),
                            "type": edge_type,
                            "lineno": import_record.get("lineno"),
                            "module": module,
                        }
                    )
        else:
            file_record = parse_non_python_file(path)
            files.append(file_record)

        path_to_file[file_record["path"]] = file_record

    entrypoints = load_entrypoints()
    for entry in entrypoints:
        for target_path in entry["file_paths"]:
            edges.append(
                {
                    "source": entry["id"],
                    "target": file_id(target_path),
                    "type": "entrypoint_targets_file",
                }
            )
        if entry["module"] and entry["object"]:
            symbol = symbol_lookup.get((entry["module"], entry["object"]))
            if symbol:
                edges.append(
                    {
                        "source": entry["id"],
                        "target": symbol["id"],
                        "type": "entrypoint_targets_symbol",
                    }
                )

    routes: list[dict[str, Any]] = []
    for route in TASK_ROUTES:
        route_record = {
            "id": route_id(route["task"]),
            "task": route["task"],
            "notes": route["notes"],
            "paths": route["paths"],
        }
        routes.append(route_record)
        for path in route["paths"]:
            if path in path_to_file:
                edges.append(
                    {
                        "source": route_record["id"],
                        "target": file_id(path),
                        "type": "route",
                    }
                )

    graph = {
        "meta": {
            "project_root": PROJECT_ROOT.as_posix(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generator": SCRIPT_PATH.name,
            "graph_version": "1.0",
        },
        "entrypoints": entrypoints,
        "execution_path": EXECUTION_PATHS,
        "task_routes": routes,
        "files": sorted(files, key=lambda item: item["path"]),
        "symbols": sorted(symbols, key=lambda item: (item["file_id"], item["lineno"], item["qualname"])),
        "edges": sorted(
            edges,
            key=lambda item: (
                item["type"],
                item["source"],
                item["target"],
                item.get("lineno", 0),
            ),
        ),
        "stats": {
            "file_count": len(files),
            "symbol_count": len(symbols),
            "edge_count": len(edges),
            "source_file_count": sum(1 for item in files if item["path"].startswith("src/")),
            "test_file_count": sum(1 for item in files if item["path"].startswith("tests/")),
        },
    }
    return graph


def write_graph(output_path: Path) -> dict[str, Any]:
    graph = build_graph()
    output_path.write_text(json.dumps(graph, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return graph


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="Path to write the generated JSON graph.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print the JSON graph to stdout after writing the file.",
    )
    args = parser.parse_args()

    output_path = args.output.resolve()
    graph = write_graph(output_path)
    print(
        f"Wrote {output_path} "
        f"({graph['stats']['file_count']} files, {graph['stats']['symbol_count']} symbols, {graph['stats']['edge_count']} edges)."
    )
    if args.stdout:
        print(json.dumps(graph, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
