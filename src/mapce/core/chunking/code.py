"""Code chunker — produces L1-L5 + Config chunks from a cloned repository.

L1: Repo-level    — README summary + directory tree + entry points + build info
L2: File-level    — path + imports + top-level docstrings + symbol signatures + exports
L3: Function/Class — full implementation + calls[] + called_by[] + type_refs
L4: Module-level  — top-level constants, registry decorators, __main__ blocks
L5: Test blocks   — test functions linked to tested symbols
Config:           — YAML/JSON/TOML hyperparameters
"""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# File extensions we care about
CODE_EXTS = {".py", ".cpp", ".cu", ".cuh", ".h", ".hpp"}
CONFIG_EXTS = {".yaml", ".yml", ".json", ".toml"}
DOC_EXTS = {".md", ".rst", ".txt"}
BUILD_FILES = {
    "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg",
    "CMakeLists.txt", "Makefile", "environment.yaml", "environment.yml",
    "Pipfile", "poetry.lock",
}
IGNORE_DIRS = {
    "__pycache__", ".git", ".github", "node_modules", "data", "assets",
    "checkpoints", "checkpoint", "logs", "outputs", ".eggs", "*.egg-info",
    "build", "dist", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
}
IGNORE_FILE_PATTERNS = [r"\.pt$", r"\.pth$", r"\.onnx$", r"\.engine$", r"\.so$", r"\.dll$", r"\.pyc$"]
MAX_FILE_SIZE_BYTES = 1_000_000  # skip files >1MB


# ---------------------------------------------------------------------------
# Chunk ID helpers
# ---------------------------------------------------------------------------

def _make_code_chunk_id(paper_id: str, repo_name: str, chunk_type: str, index: int) -> str:
    return f"code:{paper_id}:{repo_name}:{chunk_type}:{index}"


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _should_ignore_dir(dirname: str) -> bool:
    return dirname in IGNORE_DIRS or dirname.startswith(".")


def _should_ignore_file(filepath: Path) -> bool:
    if filepath.stat().st_size > MAX_FILE_SIZE_BYTES:
        return True
    for pattern in IGNORE_FILE_PATTERNS:
        if re.search(pattern, filepath.name):
            return True
    return False


def _is_test_file(filepath: Path) -> bool:
    name = filepath.name
    path_str = str(filepath)
    return (
        name.startswith("test_") or name.endswith("_test.py")
        or "tests/" in path_str or "test/" in path_str
    )


def _read_file_safe(path: Path) -> str | None:
    """Read a file's text content, returning None on failure."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# L1: Repo-level
# ---------------------------------------------------------------------------

def _get_directory_tree(root: Path, max_depth: int = 4) -> str:
    """Generate a simple directory tree string."""
    lines = []
    root = root.resolve()

    def walk(dir_path: Path, prefix: str = "", depth: int = 0):
        if depth > max_depth:
            return
        entries = sorted(dir_path.iterdir(), key=lambda e: (e.is_file(), e.name))
        for i, entry in enumerate(entries):
            if _should_ignore_dir(entry.name) if entry.is_dir() else _should_ignore_file(entry):
                continue
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir():
                extension = "    " if is_last else "│   "
                walk(entry, prefix + extension, depth + 1)

    lines.append(root.name + "/")
    walk(root)
    return "\n".join(lines)


def _get_entry_points(root: Path) -> list[str]:
    """Find likely entry-point scripts."""
    entries = []
    common_entries = [
        "main.py", "train.py", "run.py", "eval.py", "evaluate.py",
        "demo.py", "inference.py", "app.py", "cli.py",
    ]
    for name in common_entries:
        for found in root.rglob(name):
            if not any(p.name in IGNORE_DIRS for p in found.parents):
                entries.append(str(found.relative_to(root)))
    # Also check setup.py entry_points
    setup_py = root / "setup.py"
    if setup_py.exists():
        entries.append("setup.py (entry_points)")
    return entries


def _get_readme_summary(root: Path) -> str:
    """Extract a brief summary from README."""
    for name in ("README.md", "README.rst", "README.txt", "README"):
        readme = root / name
        if readme.exists():
            content = _read_file_safe(readme)
            if content:
                # Take first ~2000 chars
                return content[:2000]
    return ""


def _get_build_summary(root: Path) -> str:
    """Summarize build/install configuration."""
    parts = []
    for name in BUILD_FILES:
        fpath = root / name
        if fpath.exists():
            content = _read_file_safe(fpath)
            if content:
                parts.append(f"# {name}\n{content[:500]}")
    return "\n\n".join(parts)


def chunk_repo_l1(
    paper_id: str,
    repo_name: str,
    repo_url: str,
    root: Path,
    chunk_counter: int = 0,
) -> list[dict[str, Any]]:
    """Generate L1 (repo-level) chunk."""
    tree = _get_directory_tree(root)
    entries = _get_entry_points(root)
    readme = _get_readme_summary(root)
    build = _get_build_summary(root)

    content_parts = [f"# Repository: {repo_name}\nURL: {repo_url}\n"]
    if readme:
        content_parts.append(f"## README\n{readme}")
    content_parts.append(f"## Directory Structure\n```\n{tree}\n```")
    if entries:
        content_parts.append(f"## Entry Points\n" + "\n".join(f"- {e}" for e in entries))
    if build:
        content_parts.append(f"## Build/Install\n{build}")

    chunk = {
        "chunk_id": _make_code_chunk_id(paper_id, repo_name, "l1", chunk_counter),
        "chunk_type": "code_l1",
        "source_type": "code",
        "paper_id": paper_id,
        "content": "\n\n".join(content_parts),
        "repo_name": repo_name,
        "repo_url": repo_url,
        "file_path": None,
        "line_range": None,
        "language": None,
        "symbol_name": None,
        "symbol_type": "repo",
        # base fields
        "title": None,
        "authors": None,
        "year": None,
        "venue": None,
        "arxiv_id": None,
        "doi": None,
        "section_path": f"{repo_name}/",
        "section_level": 1,
        "chunk_index": chunk_counter,
        "prev_chunk_id": None,
        "next_chunk_id": None,
    }
    return [chunk]


# ---------------------------------------------------------------------------
# Python AST-based chunking (L2-L5)
# ---------------------------------------------------------------------------


def _extract_python_symbols(source: str, file_path: str) -> dict[str, Any]:
    """Parse a .py file and extract all symbols + module-level code."""
    result = {
        "functions": [],    # list of {name, signature, docstring, start_line, end_line, calls, body}
        "classes": [],      # list of {name, bases, docstring, methods[], start_line, end_line}
        "globals": [],      # top-level constant assignments / enum definitions
        "imports": [],      # import statements
        "decorators": [],   # @decorator(...) at module/class level
        "main_block": None, # if __name__ == "__main__": body
        "type_annotations": [],  # top-level type aliases
    }

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return result

    # Collect imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = ", ".join(a.name for a in node.names)
            result["imports"].append(f"from {module} import {names}")

    # Top-level analysis
    for node in ast.iter_child_nodes(tree):
        # Function definitions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_info = _extract_function_info(node, source)
            result["functions"].append(func_info)

        # Class definitions
        elif isinstance(node, ast.ClassDef):
            class_info = _extract_class_info(node, source, file_path)
            result["classes"].append(class_info)

        # Global assignments (constants, enums)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    try:
                        val = ast.literal_eval(node.value) if isinstance(node.value, ast.Constant) else "..."
                    except Exception:
                        val = "..."
                    result["globals"].append({
                        "name": target.id,
                        "value": str(val),
                        "line": node.lineno,
                    })

        # Decorated items at module level (registries, etc.)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Attribute):
                result["decorators"].append({
                    "call": ast.unparse(node.value),
                    "line": node.lineno,
                })

        # if __name__ == "__main__":
        elif isinstance(node, ast.If):
            test_str = ast.unparse(node.test)
            if "__name__" in test_str and "__main__" in test_str:
                result["main_block"] = {
                    "start_line": node.lineno,
                    "end_line": node.end_lineno or node.lineno,
                    "body": ast.unparse(node),
                }

    return result


def _extract_function_info(node: ast.FunctionDef | ast.AsyncFunctionDef, source: str) -> dict:
    """Extract detailed info from a function AST node."""
    args = []
    for arg in node.args.args:
        arg_str = arg.arg
        if arg.annotation:
            arg_str += f": {ast.unparse(arg.annotation)}"
        args.append(arg_str)

    returns = ast.unparse(node.returns) if node.returns else ""
    sig = f"def {node.name}({', '.join(args)})"
    if returns:
        sig += f" -> {returns}"

    docstring = ast.get_docstring(node) or ""

    # Find call expressions within the function body
    calls = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                calls.append(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                calls.append(ast.unparse(child.func))

    # Find type annotations referencing custom types
    type_refs = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id[0].isupper():
            type_refs.append(child.id)

    body = ast.unparse(node)

    return {
        "name": node.name,
        "signature": sig,
        "docstring": docstring,
        "start_line": node.lineno,
        "end_line": node.end_lineno or node.lineno,
        "calls": list(set(calls)),
        "type_refs": list(set(type_refs)),
        "body": body,
        "is_async": isinstance(node, ast.AsyncFunctionDef),
    }


def _extract_class_info(node: ast.ClassDef, source: str, file_path: str) -> dict:
    """Extract detailed info from a class AST node."""
    bases = [ast.unparse(b) for b in node.bases]
    docstring = ast.get_docstring(node) or ""
    methods = []
    class_calls = []

    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            m = _extract_function_info(child, source)
            methods.append(m)
            class_calls.extend(m["calls"])
        elif isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name):
                    methods.append({
                        "name": target.id,
                        "signature": f"{target.id} = ...",
                        "docstring": "",
                        "start_line": child.lineno,
                        "end_line": child.end_lineno or child.lineno,
                        "calls": [],
                        "type_refs": [],
                        "body": ast.unparse(child),
                        "is_async": False,
                    })

    return {
        "name": node.name,
        "bases": bases,
        "docstring": docstring,
        "start_line": node.lineno,
        "end_line": node.end_lineno or node.lineno,
        "methods": methods,
        "calls": list(set(class_calls)),
    }


# ---------------------------------------------------------------------------
# C++/CUDA chunking (basic regex-based, no full compilation needed)
# ---------------------------------------------------------------------------

_CPP_FUNC_RE = re.compile(
    r"(?:(?:virtual|static|inline|constexpr|explicit|__host__|__device__|__global__)\s+)*"
    r"([\w:<>,*&\s]+?)\s+"
    r"(\w+)\s*\(([^)]*)\)\s*(?:const)?\s*"
    r"(?:override)?\s*\{",
    re.MULTILINE,
)

_CPP_CLASS_RE = re.compile(
    r"(?:class|struct)\s+(\w+)\s*(?::\s*[^{]+)?\s*\{",
    re.MULTILINE,
)


def _extract_braced_body(source: str, start: int) -> int | None:
    """Return the offset just past the '}' that closes the first '{' at/after start.

    Skips braces inside string literals, char literals, and // and /* */
    comments, so a '}' in e.g. ``"}"``, ``'}'`` or ``// }`` does not
    prematurely close the body. Returns None if no balanced closing brace
    is found (e.g. a truncated or malformed function).
    """
    depth = 0
    started = False
    in_line_comment = in_block_comment = in_string = in_char = False
    i, n = start, len(source)
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
        elif in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
        elif in_string:
            if ch == "\\":
                i += 2
            else:
                if ch == '"':
                    in_string = False
                i += 1
        elif in_char:
            if ch == "\\":
                i += 2
            else:
                if ch == "'":
                    in_char = False
                i += 1
        elif ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
        elif ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
        elif ch == '"':
            in_string = True
            i += 1
        elif ch == "'":
            in_char = True
            i += 1
        elif ch == "{":
            depth += 1
            started = True
            i += 1
        elif ch == "}":
            depth -= 1
            i += 1
            if started and depth == 0:
                return i
        else:
            i += 1
    return None


def _extract_cpp_symbols(source: str, file_path: str) -> dict[str, Any]:
    """Basic C++/CUDA symbol extraction using regex.

    For production use, integrate tree-sitter-cpp for accurate AST parsing.
    """
    result = {
        "functions": [],
        "classes": [],
        "globals": [],
        "imports": [],  # #include directives
    }

    # Includes
    include_re = re.compile(r'#include\s+[<"]([^>"]+)[>"]')
    result["imports"] = include_re.findall(source)

    # Functions
    for match in _CPP_FUNC_RE.finditer(source):
        ret_type = match.group(1).strip()
        name = match.group(2)
        params = match.group(3)
        # Approximate body extraction — brace matching that ignores braces
        # inside string/char literals and comments.
        start = match.start()
        end = _extract_braced_body(source, start)
        if end is None:
            # Malformed/truncated body — fall back to the signature so we
            # never emit an empty chunk.
            body = f"{ret_type} {name}({params})"
        else:
            body = source[start:end]
        result["functions"].append({
            "name": name,
            "signature": f"{ret_type} {name}({params})",
            "docstring": "",
            "start_line": source[:start].count("\n") + 1,
            "body": body,
            "calls": [],
            "type_refs": [],
        })

    # Classes
    for match in _CPP_CLASS_RE.finditer(source):
        result["classes"].append({
            "name": match.group(1),
            "bases": [],
            "docstring": "",
            "start_line": source[: match.start()].count("\n") + 1,
        })

    return result


# ---------------------------------------------------------------------------
# File chunking (L2)
# ---------------------------------------------------------------------------

def _chunk_file_l2(
    paper_id: str,
    repo_name: str,
    file_path: Path,
    root: Path,
    chunk_counter: int,
    symbols: dict[str, Any],
    language: str,
) -> dict[str, Any] | None:
    """Generate L2 (file-level) chunk for a single source file.

    ``symbols``/``language`` are passed in by the caller (already parsed) so the
    file is not read and parsed a second time.
    """
    rel_path = str(file_path.relative_to(root))

    # Build a file-level summary
    summary_parts = [f"# File: {rel_path}"]
    summary_parts.append(f"Language: {language}")

    # C++ symbol dicts lack some keys (decorators/main_block), so use .get().
    if symbols.get("imports"):
        summary_parts.append("\n## Imports/Includes")
        summary_parts.extend(f"- {imp}" for imp in symbols["imports"][:30])

    # Function/class signatures
    all_sigs = []
    for f in symbols.get("functions", []):
        all_sigs.append(f"def {f['name']}(...)" if language == "python" else f"{f['name']}(...);")
    for c in symbols.get("classes", []):
        bases = f"({', '.join(c['bases'])})" if c.get("bases") else ""
        all_sigs.append(f"class {c['name']}{bases}")
    if all_sigs:
        summary_parts.append(f"\n## Symbols ({len(all_sigs)})")
        summary_parts.extend(f"- {s}" for s in all_sigs)

    if symbols.get("globals"):
        summary_parts.append("\n## Global Constants")
        summary_parts.extend(f"- {g['name']} = {g['value']}" for g in symbols["globals"])

    if symbols.get("decorators"):
        summary_parts.append("\n## Module-Level Decorators (Registries)")
        summary_parts.extend(f"- @{d['call']}" for d in symbols["decorators"])

    chunk = {
        "chunk_id": _make_code_chunk_id(paper_id, repo_name, "l2", chunk_counter),
        "chunk_type": "code_l2",
        "source_type": "code",
        "paper_id": paper_id,
        "content": "\n".join(summary_parts),
        "repo_name": repo_name,
        "repo_url": None,
        "file_path": rel_path,
        "line_range": None,
        "language": language,
        "symbol_name": None,
        "symbol_type": "file_summary",
        "title": None,
        "authors": None,
        "year": None,
        "venue": None,
        "arxiv_id": None,
        "doi": None,
        "section_path": f"{repo_name}/{rel_path}",
        "section_level": 2,
        "chunk_index": chunk_counter,
        "prev_chunk_id": None,
        "next_chunk_id": None,
        "imports": symbols.get("imports", []),
    }
    return chunk


# ---------------------------------------------------------------------------
# Function/Class chunks (L3)
# ---------------------------------------------------------------------------

def _chunk_symbols_l3(
    paper_id: str,
    repo_name: str,
    file_path: Path,
    root: Path,
    symbols: dict[str, Any],
    language: str,
    chunk_counter: int,
) -> list[dict[str, Any]]:
    """Generate L3 chunks for each function and class."""
    chunks = []
    rel_path = str(file_path.relative_to(root))

    base = {
        "source_type": "code",
        "paper_id": paper_id,
        "repo_name": repo_name,
        "file_path": rel_path,
        "language": language,
        "title": None, "authors": None, "year": None, "venue": None,
        "arxiv_id": None, "doi": None,
    }

    for func in symbols.get("functions", []):
        chunks.append({
            "chunk_id": _make_code_chunk_id(paper_id, repo_name, "l3", chunk_counter),
            "chunk_type": "code_l3",
            "content": func.get("body", func.get("signature", "")),
            "section_path": f"{repo_name}/{rel_path}::{func['name']}",
            "section_level": 3,
            "chunk_index": chunk_counter,
            "prev_chunk_id": None,
            "next_chunk_id": None,
            "symbol_name": func["name"],
            "symbol_type": "function",
            "signature": func.get("signature", ""),
            "docstring": func.get("docstring", ""),
            "calls": func.get("calls", []),
            "called_by": [],
            "type_refs": func.get("type_refs", []),
            "imports": [],
            "associated_test": None,
            # special fields
            "figure_path": None,
            "table_markdown": None,
            "table_image": None,
            "table_dims": None,
            "config_keys": None,
            **base,
        })
        chunk_counter += 1

    for cls in symbols.get("classes", []):
        cls_content = f"class {cls['name']}"
        if cls.get("bases"):
            cls_content += f"({', '.join(cls['bases'])})"
        cls_content += "\n"
        if cls.get("docstring"):
            cls_content += f'    """{cls["docstring"]}"""\n'
        for m in cls.get("methods", []):
            cls_content += f"    {m.get('signature', m.get('name', ''))}\n"
            if body := m.get("body"):
                # Include method bodies within reason
                cls_content += f"        ...\n"

        chunks.append({
            "chunk_id": _make_code_chunk_id(paper_id, repo_name, "l3", chunk_counter),
            "chunk_type": "code_l3",
            "content": cls_content,
            "section_path": f"{repo_name}/{rel_path}::{cls['name']}",
            "section_level": 3,
            "chunk_index": chunk_counter,
            "prev_chunk_id": None,
            "next_chunk_id": None,
            "symbol_name": cls["name"],
            "symbol_type": "class",
            "signature": f"class {cls['name']}",
            "docstring": cls.get("docstring", ""),
            "calls": cls.get("calls", []),
            "called_by": [],
            "type_refs": [],
            "imports": [],
            "associated_test": None,
            "figure_path": None,
            "table_markdown": None,
            "table_image": None,
            "table_dims": None,
            "config_keys": None,
            **base,
        })
        chunk_counter += 1

        # Also chunk each method as L3
        for m in cls.get("methods", []):
            if m.get("body") and len(m["body"]) > 50:
                chunks.append({
                    "chunk_id": _make_code_chunk_id(paper_id, repo_name, "l3", chunk_counter),
                    "chunk_type": "code_l3",
                    "content": m.get("body", ""),
                    "section_path": f"{repo_name}/{rel_path}::{cls['name']}.{m['name']}",
                    "section_level": 3,
                    "chunk_index": chunk_counter,
                    "prev_chunk_id": None,
                    "next_chunk_id": None,
                    "symbol_name": f"{cls['name']}.{m['name']}",
                    "symbol_type": "method",
                    "signature": m.get("signature", ""),
                    "docstring": m.get("docstring", ""),
                    "calls": m.get("calls", []),
                    "called_by": [],
                    "type_refs": m.get("type_refs", []),
                    "imports": [],
                    "associated_test": None,
                    "figure_path": None,
                    "table_markdown": None,
                    "table_image": None,
                    "table_dims": None,
                    "config_keys": None,
                    **base,
                })
                chunk_counter += 1

    return chunks


# ---------------------------------------------------------------------------
# Module-level chunks (L4)
# ---------------------------------------------------------------------------

def _chunk_module_l4(
    paper_id: str,
    repo_name: str,
    file_path: Path,
    root: Path,
    symbols: dict[str, Any],
    language: str,
    chunk_counter: int,
) -> list[dict[str, Any]]:
    """Generate L4 chunk for module-level code (globals, registry decorators, __main__)."""
    chunks = []
    rel_path = str(file_path.relative_to(root))

    base = {
        "source_type": "code",
        "paper_id": paper_id,
        "repo_name": repo_name,
        "file_path": rel_path,
        "language": language,
        "title": None, "authors": None, "year": None, "venue": None,
        "arxiv_id": None, "doi": None,
        "symbol_type": "module",
    }

    # Globals + decorators
    if symbols.get("globals") or symbols.get("decorators"):
        content_parts = [f"# Module-level definitions in {rel_path}"]
        for g in symbols.get("globals", []):
            content_parts.append(f"{g['name']} = {g['value']}")
        for d in symbols.get("decorators", []):
            content_parts.append(f"@{d['call']}")

        chunks.append({
            "chunk_id": _make_code_chunk_id(paper_id, repo_name, "l4", chunk_counter),
            "chunk_type": "code_l4",
            "content": "\n".join(content_parts),
            "section_path": f"{repo_name}/{rel_path}::module",
            "section_level": 4,
            "chunk_index": chunk_counter,
            "prev_chunk_id": None,
            "next_chunk_id": None,
            "symbol_name": f"{rel_path}::globals",
            "signature": None,
            "docstring": None,
            "calls": [],
            "called_by": [],
            "type_refs": [],
            "imports": [],
            "associated_test": None,
            "figure_path": None,
            "table_markdown": None,
            "table_image": None,
            "table_dims": None,
            "config_keys": None,
            **base,
        })
        chunk_counter += 1

    # __main__ block
    if symbols.get("main_block"):
        mb = symbols["main_block"]
        chunks.append({
            "chunk_id": _make_code_chunk_id(paper_id, repo_name, "l4", chunk_counter),
            "chunk_type": "code_l4",
            "content": mb.get("body", ""),
            "section_path": f"{repo_name}/{rel_path}::__main__",
            "section_level": 4,
            "chunk_index": chunk_counter,
            "prev_chunk_id": None,
            "next_chunk_id": None,
            "symbol_name": "__main__",
            "signature": "if __name__ == '__main__':",
            "docstring": None,
            "calls": [],
            "called_by": [],
            "type_refs": [],
            "imports": [],
            "associated_test": None,
            "figure_path": None,
            "table_markdown": None,
            "table_image": None,
            "table_dims": None,
            "config_keys": None,
            **base,
        })
        chunk_counter += 1

    return chunks


# ---------------------------------------------------------------------------
# Test chunks (L5)
# ---------------------------------------------------------------------------

def _chunk_tests(
    paper_id: str,
    repo_name: str,
    file_path: Path,
    root: Path,
    chunk_counter: int,
) -> list[dict[str, Any]]:
    """Generate L5 chunks from test files. Each test function gets its own chunk."""
    source = _read_file_safe(file_path)
    if source is None:
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    chunks = []
    rel_path = str(file_path.relative_to(root))

    base = {
        "source_type": "code",
        "paper_id": paper_id,
        "repo_name": repo_name,
        "file_path": rel_path,
        "language": "python",
        "title": None, "authors": None, "year": None, "venue": None,
        "arxiv_id": None, "doi": None,
        "symbol_type": "test",
    }

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("test"):
                continue
            body = ast.unparse(node)
            # Guess the tested symbol from the function name
            tested_symbol = node.name.replace("test_", "").replace("test", "")
            associated_test = None
            # Store the relationship: this test → tested symbol
            # The mapper can link them later

            chunks.append({
                "chunk_id": _make_code_chunk_id(paper_id, repo_name, "l5", chunk_counter),
                "chunk_type": "code_l5",
                "content": body,
                "section_path": f"{repo_name}/{rel_path}::{node.name}",
                "section_level": 5,
                "chunk_index": chunk_counter,
                "prev_chunk_id": None,
                "next_chunk_id": None,
                "symbol_name": node.name,
                "signature": f"def {node.name}(...):",
                "docstring": ast.get_docstring(node) or "",
                "calls": list(set(
                    child.func.id for child in ast.walk(node)
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                )),
                "called_by": [],
                "type_refs": [],
                "imports": [],
                "associated_test": None,
                "figure_path": None,
                "table_markdown": None,
                "table_image": None,
                "table_dims": None,
                "config_keys": None,
                **base,
            })
            chunk_counter += 1

    return chunks


# ---------------------------------------------------------------------------
# Config chunks
# ---------------------------------------------------------------------------

def _chunk_config(
    paper_id: str,
    repo_name: str,
    file_path: Path,
    root: Path,
    chunk_counter: int,
) -> dict[str, Any] | None:
    """Generate a Config chunk from a YAML/JSON/TOML file."""
    source = _read_file_safe(file_path)
    if source is None:
        return None

    rel_path = str(file_path.relative_to(root))
    ext = file_path.suffix.lower()

    # Parse and extract top-level keys
    config_keys = []
    try:
        if ext in (".yaml", ".yml"):
            data = yaml.safe_load(source)
        elif ext == ".json":
            data = json.loads(source)
        elif ext == ".toml":
            # Basic TOML: extract key = value pairs
            data = {}
            for line in source.split("\n"):
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    data[k.strip()] = v.strip().strip('"').strip("'")
        else:
            data = {}
    except Exception:
        data = {}

    if isinstance(data, dict):
        config_keys = list(data.keys())[:50]

    chunk_counter += 1
    return {
        "chunk_id": _make_code_chunk_id(paper_id, repo_name, "cfg", chunk_counter),
        "chunk_type": "code_config",
        "source_type": "code",
        "paper_id": paper_id,
        "content": f"# Config: {rel_path}\n\n{source[:4000]}",
        "repo_name": repo_name,
        "repo_url": None,
        "file_path": rel_path,
        "line_range": None,
        "language": ext.lstrip("."),
        "symbol_name": None,
        "symbol_type": "config",
        "title": None, "authors": None, "year": None, "venue": None,
        "arxiv_id": None, "doi": None,
        "section_path": f"{repo_name}/{rel_path}",
        "section_level": 99,
        "chunk_index": chunk_counter,
        "prev_chunk_id": None,
        "next_chunk_id": None,
        "config_keys": config_keys,
        # empty non-applicable fields
        "signature": None,
        "docstring": None,
        "calls": [],
        "called_by": [],
        "type_refs": [],
        "imports": [],
        "associated_test": None,
        "figure_path": None,
        "table_markdown": None,
        "table_image": None,
        "table_dims": None,
    }


# ---------------------------------------------------------------------------
# Main entry: chunk a full repository
# ---------------------------------------------------------------------------

def chunk_repo(
    paper_id: str,
    repo_url: str,
    root: Path,
) -> list[dict[str, Any]]:
    """Chunk an entire cloned repository into L1-L5 + Config chunks.

    Args:
        paper_id: The paper this repo is associated with.
        repo_url: URL of the repository.
        root: Path to the cloned repository root.

    Returns:
        List of chunk dicts ready for LanceDB insertion.
    """
    repo_name = root.name
    all_chunks: list[dict[str, Any]] = []
    chunk_counter = 0

    # L1: Repo-level
    l1_chunks = chunk_repo_l1(paper_id, repo_name, repo_url, root, chunk_counter)
    chunk_counter += len(l1_chunks)
    all_chunks.extend(l1_chunks)

    # Walk files
    for dirpath_str, dirnames, filenames in os.walk(root):
        # Filter ignored dirs in-place
        dirnames[:] = [d for d in dirnames if not _should_ignore_dir(d)]

        dirpath = Path(dirpath_str)
        for filename in filenames:
            file_path = dirpath / filename
            if _should_ignore_file(file_path):
                continue

            ext = file_path.suffix.lower()

            # Config files
            if ext in CONFIG_EXTS:
                cfg = _chunk_config(paper_id, repo_name, file_path, root, chunk_counter)
                if cfg:
                    all_chunks.append(cfg)
                    chunk_counter += 1
                continue

            # Source code files
            if ext in CODE_EXTS:
                source = _read_file_safe(file_path)
                if source is None:
                    continue

                # Parse symbols
                if ext == ".py":
                    symbols = _extract_python_symbols(source, str(file_path.relative_to(root)))
                    language = "python"
                else:
                    symbols = _extract_cpp_symbols(source, str(file_path.relative_to(root)))
                    language = "cpp" if ext != ".cu" else "cuda"

                # L2: File-level
                if _is_test_file(file_path):
                    # L5: Test
                    test_chunks = _chunk_tests(paper_id, repo_name, file_path, root, chunk_counter)
                    all_chunks.extend(test_chunks)
                    chunk_counter += len(test_chunks)
                else:
                    l2 = _chunk_file_l2(
                        paper_id, repo_name, file_path, root, chunk_counter,
                        symbols, language,
                    )
                    if l2:
                        all_chunks.append(l2)
                        chunk_counter += 1

                    # L3: Function/Class-level
                    l3_chunks = _chunk_symbols_l3(
                        paper_id, repo_name, file_path, root,
                        symbols, language, chunk_counter,
                    )
                    all_chunks.extend(l3_chunks)
                    chunk_counter += len(l3_chunks)

                    # L4: Module-level
                    l4_chunks = _chunk_module_l4(
                        paper_id, repo_name, file_path, root,
                        symbols, language, chunk_counter,
                    )
                    all_chunks.extend(l4_chunks)
                    chunk_counter += len(l4_chunks)

    return all_chunks
