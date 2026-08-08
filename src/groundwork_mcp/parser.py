"""Groundwork MCP — tree-sitter AST parser (Python native bindings)."""

import json
import sys
from pathlib import Path
from typing import Optional
import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
import tree_sitter_python as tspy
from tree_sitter import Language, Parser, Node
from .types import SievedFile, ParsedFile, SymbolRecord, EdgeRecord, FileParseResult

# ── Language setup ────────────────────────────────────────────────────────────

_JS_LANG = Language(tsjs.language())
_TS_LANG = Language(tsts.language_typescript())
_TSX_LANG = Language(tsts.language_tsx())
_PY_LANG = Language(tspy.language())

_PARSERS: dict[str, Parser] = {
    "javascript": Parser(_JS_LANG),
    "typescript": Parser(_TS_LANG),
    "tsx": Parser(_TSX_LANG),
    "python": Parser(_PY_LANG),
}

_log_init = False

def _ensure_logged() -> None:
    global _log_init
    if not _log_init:
        _log(f"Parser initialized with {len(_PARSERS)} language(s): {', '.join(_PARSERS)}")
        _log_init = True

# ── Public API ────────────────────────────────────────────────────────────────

def parse_all_files(
    files: list[SievedFile],
    repo_root: str,
    progress_cb=None,
) -> list[FileParseResult]:
    """Parse all sieved files and extract symbols + edges."""
    _ensure_logged()
    results = []
    total = len(files)

    for i, f in enumerate(files):
        result = _parse_file(f, repo_root)
        results.append(result)
        if progress_cb:
            progress_cb(i + 1, total, f.relative_path)

    return results


def _parse_file(f: SievedFile, repo_root: str) -> FileParseResult:
    """Parse a single file — extract AST, symbols, and import edges."""
    try:
        source = Path(f.absolute_path).read_bytes()
        line_count = source.count(b"\n") + 1
    except (OSError, PermissionError):
        return FileParseResult(
            file=ParsedFile(
                file_path=f.relative_path,
                language=f.language,
                line_count=0,
                size_bytes=f.size_bytes,
                ast_json=None,
            )
        )

    parsed_file = ParsedFile(
        file_path=f.relative_path,
        language=f.language,
        line_count=line_count,
        size_bytes=f.size_bytes,
        ast_json=None,
    )

    parser = _PARSERS.get(f.language)
    if not parser:
        # Non-parseable language (json, yaml, markdown) — store without AST
        return FileParseResult(file=parsed_file)

    try:
        tree = parser.parse(source)
        symbols = _extract_symbols(tree.root_node, f.relative_path, f.language)
        edges = _extract_edges(tree.root_node, f.relative_path, repo_root)
        ast_json = _node_to_json(tree.root_node, source, depth=0, max_depth=4)
        parsed_file.ast_json = json.dumps(ast_json, separators=(",", ":"))
    except Exception as e:
        _log(f"Parse error in {f.relative_path}: {e}")
        symbols, edges = [], []

    return FileParseResult(file=parsed_file, symbols=symbols, edges=edges)


# ── AST → lightweight JSON ─────────────────────────────────────────────────────

def _node_to_json(node: Node, source: bytes, depth: int, max_depth: int) -> dict:
    """Convert tree-sitter node to a pruned JSON-serializable dict."""
    if depth >= max_depth:
        return {"type": node.type, "children": []}

    name = None
    # Try to get identifier name from first named child
    for child in node.children:
        if child.type in ("identifier", "name", "property_identifier"):
            try:
                name = source[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
            except Exception:
                pass
            break

    children = [
        _node_to_json(c, source, depth + 1, max_depth)
        for c in node.children
        if not c.is_extra  # skip comments/whitespace
    ] if depth < max_depth - 1 else []

    return {
        "t": node.type,
        "sl": node.start_point[0] + 1,
        "el": node.end_point[0] + 1,
        **({"n": name} if name else {}),
        **({"c": children} if children else {}),
    }


# ── Symbol Extraction ─────────────────────────────────────────────────────────

def _extract_symbols(root: Node, file_path: str, lang: str) -> list[SymbolRecord]:
    symbols: list[SymbolRecord] = []
    _walk_symbols(root, file_path, lang, symbols)
    return symbols


def _walk_symbols(node: Node, file_path: str, lang: str, out: list[SymbolRecord]) -> None:
    sym = _node_to_symbol(node, file_path, lang)
    if sym:
        out.append(sym)
    for child in node.children:
        _walk_symbols(child, file_path, lang, out)


def _node_to_symbol(node: Node, file_path: str, lang: str) -> Optional[SymbolRecord]:
    """Map a tree-sitter node type to a SymbolRecord."""
    t = node.type

    # ── JavaScript / TypeScript ──────────────────────────────────────
    if lang in ("javascript", "typescript", "tsx"):
        if t in ("function_declaration", "function_expression", "arrow_function"):
            name = _get_child_text(node, "identifier")
            # For arrow functions assigned to variables, name comes from parent
            return _make_symbol(file_path, name or "<anonymous>", "function", node)

        if t == "class_declaration":
            name = _get_child_text(node, "identifier")
            return _make_symbol(file_path, name or "<anonymous>", "class", node)

        if t == "method_definition":
            name = _get_child_text(node, "property_identifier") or _get_child_text(node, "identifier")
            return _make_symbol(file_path, name or "<anonymous>", "method", node)

        if t in ("interface_declaration",):
            name = _get_child_text(node, "type_identifier") or _get_child_text(node, "identifier")
            return _make_symbol(file_path, name or "<anonymous>", "interface", node)

        if t == "type_alias_declaration":
            name = _get_child_text(node, "type_identifier") or _get_child_text(node, "identifier")
            return _make_symbol(file_path, name or "<anonymous>", "type_alias", node)

        if t == "enum_declaration":
            name = _get_child_text(node, "identifier")
            return _make_symbol(file_path, name or "<anonymous>", "enum", node)

        if t in ("lexical_declaration", "variable_declaration"):
            # Get the first declarator
            for child in node.children:
                if child.type == "variable_declarator":
                    name = _get_child_text(child, "identifier")
                    return _make_symbol(file_path, name or "<var>", "variable", node)

    # ── Python ──────────────────────────────────────────────────────
    if lang == "python":
        if t == "function_definition":
            name = _get_child_text(node, "identifier")
            return _make_symbol(file_path, name or "<anonymous>", "function", node)

        if t == "class_definition":
            name = _get_child_text(node, "identifier")
            return _make_symbol(file_path, name or "<anonymous>", "class", node)

        if t == "assignment":
            # Top-level variable assignment
            for child in node.children:
                if child.type == "identifier":
                    name_text = child.text
                    if isinstance(name_text, bytes):
                        name_text = name_text.decode("utf-8", errors="replace")
                    return _make_symbol(file_path, name_text, "variable", node)

    return None


def _make_symbol(
    file_path: str, name: str, sym_type: str, node: Node
) -> SymbolRecord:
    return SymbolRecord(
        file_path=file_path,
        symbol_name=name,
        symbol_type=sym_type,  # type: ignore[arg-type]
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=None,
    )


def _get_child_text(node: Node, child_type: str) -> Optional[str]:
    for child in node.children:
        if child.type == child_type:
            raw = child.text
            if isinstance(raw, bytes):
                return raw.decode("utf-8", errors="replace")
            return raw
    return None


# ── Edge Extraction (imports) ─────────────────────────────────────────────────

def _extract_edges(root: Node, file_path: str, repo_root: str) -> list[EdgeRecord]:
    edges: list[EdgeRecord] = []
    _walk_edges(root, file_path, repo_root, edges)
    return edges


def _walk_edges(node: Node, file_path: str, repo_root: str, out: list[EdgeRecord]) -> None:
    edge = _node_to_edge(node, file_path, repo_root)
    if edge:
        out.append(edge)
    for child in node.children:
        _walk_edges(child, file_path, repo_root, out)


def _node_to_edge(node: Node, file_path: str, repo_root: str) -> Optional[EdgeRecord]:
    t = node.type

    # JS/TS: import statement / require call
    if t == "import_statement":
        module = _extract_import_string(node)
        if module:
            return EdgeRecord(
                source_file=file_path,
                target_file=_resolve_module(module, file_path, repo_root),
                target_module=module,
                edge_type="import",
            )

    # Python: import / from ... import
    if t in ("import_statement", "import_from_statement"):
        module = _extract_python_import(node)
        if module:
            return EdgeRecord(
                source_file=file_path,
                target_file=_resolve_module(module, file_path, repo_root),
                target_module=module,
                edge_type="import",
            )

    return None


def _extract_import_string(node: Node) -> Optional[str]:
    """Extract module string from a JS/TS import statement."""
    for child in node.children:
        if child.type == "string":
            raw = child.text
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            return raw.strip("'\"` ")
    return None


def _extract_python_import(node: Node) -> Optional[str]:
    """Extract module name from a Python import statement."""
    t = node.type
    for child in node.children:
        if child.type == "dotted_name":
            raw = child.text
            if isinstance(raw, bytes):
                return raw.decode("utf-8", errors="replace")
        if t == "import_from_statement" and child.type == "relative_import":
            raw = child.text
            if isinstance(raw, bytes):
                return raw.decode("utf-8", errors="replace")
    return None


def _resolve_module(module: str, source_file: str, repo_root: str) -> Optional[str]:
    """
    Try to resolve a relative import to a file in the repo.
    Returns relative path string or None if it's an external module.
    """
    if not (module.startswith("./") or module.startswith("../")):
        return None  # external module

    source_dir = Path(repo_root) / Path(source_file).parent
    candidates = [
        source_dir / module,
        source_dir / f"{module}.ts",
        source_dir / f"{module}.tsx",
        source_dir / f"{module}.js",
        source_dir / f"{module}/index.ts",
        source_dir / f"{module}/index.js",
    ]
    for c in candidates:
        if c.exists():
            try:
                return c.relative_to(repo_root).as_posix()
            except ValueError:
                pass
    return None


def _log(msg: str) -> None:
    print(f"[parser] {msg}", file=sys.stderr)
