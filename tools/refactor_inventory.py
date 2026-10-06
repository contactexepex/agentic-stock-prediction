#!/usr/bin/env python3
"""Inventory for docs/REFACTOR_PLAN.md: an AST scan of scripts/ (read-only).

  python tools/refactor_inventory.py [--top 50] [--json]

Prints: line count, top-level functions and classes per module; string literals repeated across
modules (docstrings and f-string fragments excluded), ranked by the number of modules then the total
count; exception messages (raise X("...") / raise X(f"...") with f-string fields shown as {}) used more
than once; function names defined in more than one module, each with its signature (parameters
and defaults); and functions whose bodies are identical (same AST, names included) in different
modules, with their signatures and whether those match too (a merge must keep each caller's defaults)."""
from __future__ import annotations

import argparse
import ast
import json
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


def modules() -> list[Path]:
    return sorted(p for p in SCRIPTS.rglob("*.py") if "__pycache__" not in p.parts)


def docstring_nodes(tree: ast.AST) -> set[int]:
    """ids of the Constant nodes that are module, class or function docstrings."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            value = first.value if isinstance(first, ast.Expr) else None
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                found.add(id(value))
    return found


def fstring_fragments(tree: ast.AST) -> set[int]:
    return {id(v) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for v in node.values}


def message_template(node: ast.AST) -> str | None:
    """The text of a string or f-string argument, f-string fields as {}."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    return None


def scan(top: int) -> dict:
    literal_total: Counter = Counter()
    literal_modules: dict[str, set[str]] = defaultdict(set)
    messages: dict[str, list[str]] = defaultdict(list)
    function_modules: dict[str, set[str]] = defaultdict(set)
    signatures: dict[str, set[tuple[str, str]]] = defaultdict(set)
    bodies: dict[str, list[tuple[str, str]]] = defaultdict(list)
    per_module = {}
    for path in modules():
        rel = path.relative_to(REPO).as_posix()
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        skip = docstring_nodes(tree) | fstring_fragments(tree)
        per_module[rel] = {
            "lines": len(text.splitlines()),
            "functions": [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))],
            "classes": [n.name for n in tree.body if isinstance(n, ast.ClassDef)],
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
                if len(node.value) >= 2:
                    literal_total[node.value] += 1
                    literal_modules[node.value].add(rel)
            elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
                template = message_template(node.exc.args[0])
                if template:
                    messages[template].append(f"{rel}:{node.lineno}")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_modules[node.name].add(rel)
                signature = f"({ast.unparse(node.args)})"
                signatures[node.name].add((rel, signature))
                body = ast.dump(ast.Module(body=[s for s in node.body if not (
                    isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))], type_ignores=[]))
                if len(node.body) > 1 or len(body) > 200:
                    bodies[body].append((f"{rel}::{node.name}", signature))
    shared = [(s, len(literal_modules[s]), n) for s, n in literal_total.items() if len(literal_modules[s]) > 1]
    repeated = sorted(shared, key=lambda x: (-x[1], -x[2], x[0]))[:top]
    return {
        "modules": per_module,
        "repeated_literals": [{"literal": s, "modules": m, "count": n} for s, m, n in repeated],
        "repeated_messages": {k: v for k, v in sorted(messages.items(), key=lambda kv: -len(kv[1])) if len(v) > 1},
        "same_name_functions": {k: [f"{rel}{sig}" for rel, sig in sorted(signatures[k])]
                                for k, v in sorted(function_modules.items()) if len(v) > 1},
        "identical_bodies": [{"functions": [f"{name}{sig}" for name, sig in sorted(group)],
                              "same_signature": len({sig for _, sig in group}) == 1}
                             for group in bodies.values() if len({name.split("::")[0] for name, _ in group}) > 1],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = scan(args.top)
    if args.json:
        print(json.dumps(result, indent=1))
        return 0
    print("## Modules")
    for rel, info in sorted(result["modules"].items(), key=lambda kv: -kv[1]["lines"]):
        print(f"{info['lines']:5d} {rel}  functions={len(info['functions'])} classes={info['classes']}")
    print(f"\n## Top {args.top} string literals repeated across modules (modules, count)")
    for row in result["repeated_literals"]:
        print(f"{row['modules']:3d} {row['count']:4d}  {row['literal']!r}")
    print("\n## Exception messages raised more than once")
    for template, where in result["repeated_messages"].items():
        print(f"{len(where):3d}  {template!r}  {', '.join(where)}")
    print("\n## Function names defined in several modules")
    for name, where in result["same_name_functions"].items():
        print(f"{name}: {', '.join(where)}")
    print("\n## Identical function bodies in different modules")
    for group in result["identical_bodies"]:
        same = "same signature" if group["same_signature"] else "SIGNATURES DIFFER"
        print(f"{same}: " + ", ".join(group["functions"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
