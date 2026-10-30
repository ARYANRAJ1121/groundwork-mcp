"""Tests for groundwork_mcp.parser — tree-sitter symbol, edge, and call extraction."""

import pytest
from pathlib import Path
from groundwork_mcp.parser import parse_all_files, _parse_file
from groundwork_mcp.types import SievedFile


def _sieved(tmp_path, name, lang, content):
    """Create a SievedFile from content written to tmp_path."""
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return SievedFile(
        relative_path=name,
        absolute_path=str(p),
        language=lang,
        size_bytes=len(content.encode("utf-8")),
    )


# ── Python Symbol Extraction ─────────────────────────────────────────────────


class TestPythonSymbols:

    def test_function_detected(self, tmp_path):
        sf = _sieved(tmp_path, "mod.py", "python", "def foo():\n    pass\n")
        result = _parse_file(sf, str(tmp_path))
        names = [(s.symbol_name, s.symbol_type) for s in result.symbols]
        assert ("foo", "function") in names

    def test_class_detected(self, tmp_path):
        sf = _sieved(tmp_path, "mod.py", "python", "class MyClass:\n    pass\n")
        result = _parse_file(sf, str(tmp_path))
        names = [(s.symbol_name, s.symbol_type) for s in result.symbols]
        assert ("MyClass", "class") in names

    def test_module_level_variable(self, tmp_path):
        sf = _sieved(tmp_path, "mod.py", "python", "MAX_SIZE = 100\n\ndef f():\n    x = 1\n")
        result = _parse_file(sf, str(tmp_path))
        names = [(s.symbol_name, s.symbol_type) for s in result.symbols]
        assert ("MAX_SIZE", "variable") in names
        # Inner variable should NOT be captured
        assert ("x", "variable") not in names

    def test_signature_extracted(self, tmp_path):
        sf = _sieved(tmp_path, "mod.py", "python", "def greet(name: str) -> str:\n    return f'Hi {name}'\n")
        result = _parse_file(sf, str(tmp_path))
        func = [s for s in result.symbols if s.symbol_name == "greet"][0]
        assert "def greet" in func.signature
        assert func.start_line == 1
        assert func.end_line == 2

    def test_dunder_variables_skipped(self, tmp_path):
        sf = _sieved(tmp_path, "mod.py", "python", "__version__ = '1.0'\n__all__ = ['foo']\n")
        result = _parse_file(sf, str(tmp_path))
        names = [s.symbol_name for s in result.symbols]
        assert "__version__" not in names
        assert "__all__" not in names


# ── Python Import Extraction ─────────────────────────────────────────────────


class TestPythonImports:

    def test_import_statement(self, tmp_path):
        sf = _sieved(tmp_path, "mod.py", "python", "import os\nimport sys\n")
        result = _parse_file(sf, str(tmp_path))
        modules = [e.target_module for e in result.edges]
        assert "os" in modules
        assert "sys" in modules

    def test_from_import(self, tmp_path):
        sf = _sieved(tmp_path, "mod.py", "python", "from pathlib import Path\n")
        result = _parse_file(sf, str(tmp_path))
        modules = [e.target_module for e in result.edges]
        assert "pathlib" in modules

    def test_edge_line_numbers(self, tmp_path):
        sf = _sieved(tmp_path, "mod.py", "python", "import os\nimport sys\n")
        result = _parse_file(sf, str(tmp_path))
        lines = {e.target_module: e.line for e in result.edges}
        assert lines["os"] == 1
        assert lines["sys"] == 2

    def test_external_imports_no_target_file(self, tmp_path):
        sf = _sieved(tmp_path, "mod.py", "python", "import numpy\n")
        result = _parse_file(sf, str(tmp_path))
        edge = result.edges[0]
        assert edge.target_file is None  # external module
        assert edge.target_module == "numpy"


# ── Python Call Extraction ────────────────────────────────────────────────────


class TestPythonCalls:

    def test_simple_call(self, tmp_path):
        sf = _sieved(tmp_path, "mod.py", "python",
                      "def main():\n    helper()\n")
        result = _parse_file(sf, str(tmp_path))
        call_names = [(c.caller_function, c.callee_name) for c in result.calls]
        assert ("main", "helper") in call_names

    def test_method_call(self, tmp_path):
        sf = _sieved(tmp_path, "mod.py", "python",
                      "class Foo:\n    def bar(self):\n        self.baz()\n")
        result = _parse_file(sf, str(tmp_path))
        call_names = [(c.caller_function, c.callee_name) for c in result.calls]
        assert ("bar", "baz") in call_names

    def test_builtin_calls_filtered(self, tmp_path):
        sf = _sieved(tmp_path, "mod.py", "python",
                      "def f():\n    print('hi')\n    len([1,2])\n    x = range(10)\n")
        result = _parse_file(sf, str(tmp_path))
        call_names = [c.callee_name for c in result.calls]
        assert "print" not in call_names
        assert "len" not in call_names
        assert "range" not in call_names

    def test_top_level_call(self, tmp_path):
        sf = _sieved(tmp_path, "mod.py", "python",
                      "setup()\n")
        result = _parse_file(sf, str(tmp_path))
        calls = [c for c in result.calls if c.callee_name == "setup"]
        if calls:
            assert calls[0].caller_function == "<module>"


# ── JavaScript/TypeScript Symbols ─────────────────────────────────────────────


class TestJSSymbols:

    def test_function_declaration(self, tmp_path):
        sf = _sieved(tmp_path, "app.js", "javascript",
                      "function greet(name) {\n  return 'Hello ' + name;\n}\n")
        result = _parse_file(sf, str(tmp_path))
        names = [(s.symbol_name, s.symbol_type) for s in result.symbols]
        assert ("greet", "function") in names

    def test_class_declaration(self, tmp_path):
        sf = _sieved(tmp_path, "app.js", "javascript",
                      "class Animal {\n  constructor(name) {\n    this.name = name;\n  }\n}\n")
        result = _parse_file(sf, str(tmp_path))
        names = [(s.symbol_name, s.symbol_type) for s in result.symbols]
        assert ("Animal", "class") in names

    def test_typescript_interface(self, tmp_path):
        sf = _sieved(tmp_path, "types.ts", "typescript",
                      "interface Config {\n  host: string;\n  port: number;\n}\n")
        result = _parse_file(sf, str(tmp_path))
        names = [(s.symbol_name, s.symbol_type) for s in result.symbols]
        assert ("Config", "interface") in names

    def test_typescript_enum(self, tmp_path):
        sf = _sieved(tmp_path, "types.ts", "typescript",
                      "enum Color {\n  Red,\n  Green,\n  Blue\n}\n")
        result = _parse_file(sf, str(tmp_path))
        names = [(s.symbol_name, s.symbol_type) for s in result.symbols]
        assert ("Color", "enum") in names

    def test_typescript_type_alias(self, tmp_path):
        sf = _sieved(tmp_path, "types.ts", "typescript",
                      "type ID = string | number;\n")
        result = _parse_file(sf, str(tmp_path))
        names = [(s.symbol_name, s.symbol_type) for s in result.symbols]
        assert ("ID", "type_alias") in names


# ── JS Import Extraction ─────────────────────────────────────────────────────


class TestJSImports:

    def test_import_statement(self, tmp_path):
        sf = _sieved(tmp_path, "app.js", "javascript",
                      "import { foo } from './lib';\n")
        result = _parse_file(sf, str(tmp_path))
        modules = [e.target_module for e in result.edges]
        assert "./lib" in modules


# ── Progress Callback ────────────────────────────────────────────────────────


class TestProgressCallback:

    def test_callback_fires(self, tmp_path):
        files = [
            _sieved(tmp_path, "a.py", "python", "x = 1\n"),
            _sieved(tmp_path, "b.py", "python", "y = 2\n"),
        ]
        calls = []
        def cb(done, total, current):
            calls.append((done, total, current))

        parse_all_files(files, str(tmp_path), cb)
        assert len(calls) == 2
        assert calls[0] == (1, 2, "a.py")
        assert calls[1] == (2, 2, "b.py")


# ── Non-parseable Files ──────────────────────────────────────────────────────


class TestNonParseableFiles:

    def test_markdown_raw_content_only(self, tmp_path):
        sf = _sieved(tmp_path, "README.md", "markdown",
                      "# Hello\n\nWorld.\n")
        result = _parse_file(sf, str(tmp_path))
        assert result.file.raw_content.replace("\r\n", "\n") == "# Hello\n\nWorld.\n"
        assert result.symbols == []
        assert result.edges == []
        assert result.calls == []

    def test_json_raw_content_only(self, tmp_path):
        sf = _sieved(tmp_path, "config.json", "json",
                      '{"key": "value"}\n')
        result = _parse_file(sf, str(tmp_path))
        assert result.file.raw_content is not None
        assert result.symbols == []

    def test_content_hash_computed(self, tmp_path):
        sf = _sieved(tmp_path, "a.py", "python", "x = 1\n")
        result = _parse_file(sf, str(tmp_path))
        assert result.file.content_hash is not None
        assert len(result.file.content_hash) == 64  # SHA-256 hex

