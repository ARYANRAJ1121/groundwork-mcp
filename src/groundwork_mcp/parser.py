"""Groundwork MCP — tree-sitter AST parser (Python native bindings)."""

import json
import sys
from pathlib import Path
from typing import Optional
import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
import tree_sitter_python as tspy
from tree_sitter import Language, Parser, Node
from .types import SievedFile, ParsedFile, SymbolRecord, EdgeRecord, CallRecord, FileParseResult

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
                raw_content=None,
            )
        )

    # Decode raw content for storage (cap at 500KB)
    MAX_RAW = 500_000
    try:
        raw_text = source[:MAX_RAW].decode("utf-8", errors="replace")
    except Exception:
        raw_text = None

    parsed_file = ParsedFile(
        file_path=f.relative_path,
        language=f.language,
        line_count=line_count,
        size_bytes=f.size_bytes,
        ast_json=None,
        raw_content=raw_text,
    )

    parser = _PARSERS.get(f.language)
    if not parser:
        # Non-parseable file (markdown, json, yaml, toml) — raw content already stored
        return FileParseResult(file=parsed_file)

    try:
        tree = parser.parse(source)
        symbols = _extract_symbols(tree.root_node, f.relative_path, f.language, source)
        edges = _extract_edges(tree.root_node, f.relative_path, repo_root)
        calls = _extract_calls(tree.root_node, f.relative_path, f.language)
        ast_json = _node_to_json(tree.root_node, source, depth=0, max_depth=4)
        parsed_file.ast_json = json.dumps(ast_json, separators=(",", ":"))
    except Exception as e:
        _log(f"Parse error in {f.relative_path}: {e}")
        symbols, edges, calls = [], [], []

    return FileParseResult(file=parsed_file, symbols=symbols, edges=edges, calls=calls)


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

def _extract_symbols(root: Node, file_path: str, lang: str, source: bytes) -> list[SymbolRecord]:
    symbols: list[SymbolRecord] = []
    _walk_symbols(root, file_path, lang, source, symbols)
    return symbols


def _walk_symbols(node: Node, file_path: str, lang: str, source: bytes, out: list[SymbolRecord]) -> None:
    sym = _node_to_symbol(node, file_path, lang, source)
    if sym:
        out.append(sym)
    for child in node.children:
        _walk_symbols(child, file_path, lang, source, out)


def _node_to_symbol(node: Node, file_path: str, lang: str, source: bytes) -> Optional[SymbolRecord]:
    """Map a tree-sitter node type to a SymbolRecord."""
    t = node.type

    # ── JavaScript / TypeScript ──────────────────────────────────────
    if lang in ("javascript", "typescript", "tsx"):
        if t in ("function_declaration", "function_expression", "arrow_function"):
            name = _get_child_text(node, "identifier")
            return _make_symbol(file_path, name or "<anonymous>", "function", node, source)

        if t == "class_declaration":
            name = _get_child_text(node, "identifier")
            return _make_symbol(file_path, name or "<anonymous>", "class", node, source)

        if t == "method_definition":
            name = _get_child_text(node, "property_identifier") or _get_child_text(node, "identifier")
            return _make_symbol(file_path, name or "<anonymous>", "method", node, source)

        if t in ("interface_declaration",):
            name = _get_child_text(node, "type_identifier") or _get_child_text(node, "identifier")
            return _make_symbol(file_path, name or "<anonymous>", "interface", node, source)

        if t == "type_alias_declaration":
            name = _get_child_text(node, "type_identifier") or _get_child_text(node, "identifier")
            return _make_symbol(file_path, name or "<anonymous>", "type_alias", node, source)

        if t == "enum_declaration":
            name = _get_child_text(node, "identifier")
            return _make_symbol(file_path, name or "<anonymous>", "enum", node, source)

        if t in ("lexical_declaration", "variable_declaration"):
            # Get the first declarator
            for child in node.children:
                if child.type == "variable_declarator":
                    name = _get_child_text(child, "identifier")
                    return _make_symbol(file_path, name or "<var>", "variable", node, source)

    # ── Python ──────────────────────────────────────────────────────
    if lang == "python":
        if t == "function_definition":
            name = _get_child_text(node, "identifier")
            return _make_symbol(file_path, name or "<anonymous>", "function", node, source)

        if t == "class_definition":
            name = _get_child_text(node, "identifier")
            return _make_symbol(file_path, name or "<anonymous>", "class", node, source)

        if t == "assignment":
            # Only capture module-level assignments (parent is the module root)
            # Skip assignments inside functions/classes to avoid noise
            parent = node.parent
            if parent is not None and parent.type == "module":
                for child in node.children:
                    if child.type == "identifier":
                        name_text = child.text
                        if isinstance(name_text, bytes):
                            name_text = name_text.decode("utf-8", errors="replace")
                        # Skip private/dunder vars — too noisy
                        if not name_text.startswith("__"):
                            return _make_symbol(file_path, name_text, "variable", node, source)

    return None


def _make_symbol(
    file_path: str, name: str, sym_type: str, node: Node, source: bytes
) -> SymbolRecord:
    """Create a SymbolRecord, extracting the first line as the signature."""
    # Extract the first non-empty line of the node as the signature
    signature: Optional[str] = None
    try:
        first_line_bytes = source[node.start_byte:].split(b"\n")[0]
        sig = first_line_bytes.decode("utf-8", errors="replace").strip()
        if sig and len(sig) <= 200:  # cap to 200 chars
            signature = sig
    except Exception:
        pass

    return SymbolRecord(
        file_path=file_path,
        symbol_name=name,
        symbol_type=sym_type,  # type: ignore[arg-type]
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=signature,
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


# ── Call Graph Extraction ─────────────────────────────────────────────────────

def _extract_calls(root: Node, file_path: str, lang: str) -> list[CallRecord]:
    """
    Walk the AST and extract all function/method call sites.
    Tracks which function definition we're currently inside so we know the caller.
    """
    if lang not in ("python", "javascript", "typescript", "tsx"):
        return []
    calls: list[CallRecord] = []
    _walk_calls(root, file_path, lang, function_stack=[], out=calls)
    return calls


def _walk_calls(
    node: Node,
    file_path: str,
    lang: str,
    function_stack: list[str],
    out: list[CallRecord],
) -> None:
    """Recursive stateful walk — maintains function_stack as call context."""
    entered = False

    # Track when we enter a named function/method
    if lang == "python" and node.type == "function_definition":
        name = _get_child_text(node, "identifier")
        if name:
            function_stack.append(name)
            entered = True

    elif lang in ("javascript", "typescript", "tsx"):
        if node.type in ("function_declaration", "function_expression"):
            name = _get_child_text(node, "identifier")
            if name:
                function_stack.append(name)
                entered = True
        elif node.type == "method_definition":
            name = (
                _get_child_text(node, "property_identifier")
                or _get_child_text(node, "identifier")
            )
            if name:
                function_stack.append(name)
                entered = True

    # Current caller context
    caller = function_stack[-1] if function_stack else "<module>"

    # Detect a call site at this node
    callee = None
    if lang == "python" and node.type == "call":
        callee = _callee_name(node)
    elif lang in ("javascript", "typescript", "tsx") and node.type == "call_expression":
        callee = _callee_name(node)

    if callee:
        out.append(CallRecord(
            caller_file=file_path,
            caller_function=caller,
            callee_name=callee,
            line=node.start_point[0] + 1,
        ))

    # Recurse into children
    for child in node.children:
        _walk_calls(child, file_path, lang, function_stack, out)

    # Pop our context when leaving this function node
    if entered:
        function_stack.pop()


def _callee_name(node: Node) -> Optional[str]:
    """
    Extract the function/method name from a call or call_expression node.

    Handles:
      foo()           → "foo"
      self.method()   → "method"
      obj.method()    → "method"
      foo.bar.baz()   → "baz"
    """
    if not node.children:
        return None

    callee_node = node.children[0]

    # Simple identifier: foo()
    if callee_node.type == "identifier":
        raw = callee_node.text
        name = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        # Skip builtins and single-char names
        if len(name) > 1 and name not in _BUILTIN_SKIP:
            return name

    # Attribute access: self.method() or obj.method()
    if callee_node.type in ("attribute", "member_expression"):
        # Walk children in reverse to get the rightmost identifier (method name)
        for child in reversed(callee_node.children):
            if child.type in ("identifier", "attribute", "property_identifier"):
                raw = child.text
                name = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                if len(name) > 1 and name not in _BUILTIN_SKIP:
                    return name

    return None


# Common builtins that are too noisy to index as call targets
_BUILTIN_SKIP = frozenset({
    "print", "len", "range", "str", "int", "float", "list", "dict", "set",
    "tuple", "bool", "type", "isinstance", "issubclass", "hasattr", "getattr",
    "setattr", "delattr", "super", "object", "enumerate", "zip", "map",
    "filter", "sorted", "reversed", "min", "max", "sum", "abs", "round",
    "open", "repr", "format", "id", "hash", "iter", "next", "vars", "dir",
    "append", "extend", "update", "get", "items", "keys", "values",
    "console", "require", "exports", "module",
})
