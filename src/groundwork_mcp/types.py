"""Groundwork MCP — shared types and dataclasses."""

from dataclasses import dataclass, field
from typing import Literal, Optional

# ── Job Status ────────────────────────────────────────────────────────────────

JobStatus = Literal["queued", "cloning", "sieving", "parsing", "complete", "failed"]

SupportedLanguage = Literal[
    "javascript", "typescript", "tsx", "python",
    "json", "yaml", "markdown", "toml", "config"
]

SymbolType = Literal[
    "function", "class", "method", "variable",
    "export", "interface", "type_alias", "enum"
]

EdgeType = Literal["import", "call", "extends", "implements"]

# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class IngestJob:
    id: str
    repo_url: str
    repo_name: str
    branch: str
    status: JobStatus
    progress: float
    files_processed: int
    files_total: int
    tokens_estimate: int
    commit_sha: Optional[str]
    clone_path: Optional[str]
    error_message: Optional[str]
    created_at: str
    updated_at: str


@dataclass
class SievedFile:
    """A file that passed the Sieve filter."""
    relative_path: str
    absolute_path: str
    language: SupportedLanguage
    size_bytes: int


@dataclass
class SieveResult:
    files: list[SievedFile]
    total_files: int
    total_size_bytes: int
    skipped_files: int
    skipped_reasons: dict[str, int]


@dataclass
class ParsedFile:
    file_path: str
    language: SupportedLanguage
    line_count: int
    size_bytes: int
    ast_json: Optional[str]


@dataclass
class SymbolRecord:
    file_path: str
    symbol_name: str
    symbol_type: SymbolType
    start_line: int
    end_line: int
    signature: Optional[str]


@dataclass
class EdgeRecord:
    source_file: str
    target_file: Optional[str]
    target_module: str
    edge_type: EdgeType


@dataclass
class FileParseResult:
    file: ParsedFile
    symbols: list[SymbolRecord] = field(default_factory=list)
    edges: list[EdgeRecord] = field(default_factory=list)


@dataclass
class CloneResult:
    clone_path: str
    commit_sha: str
    repo_name: str
