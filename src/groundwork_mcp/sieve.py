"""Groundwork MCP — File sieve (filter cloned repo down to parseable files)."""

import sys
from pathlib import Path
from .types import SievedFile, SieveResult, SupportedLanguage
from . import config
from .security import is_binary_file, check_repo_limits


def sieve_repo(repo_path: str) -> SieveResult:
    """
    Filter a cloned repository down to parseable source files.
    Skips: binary files, hidden dirs, lock files, oversized files,
    unsupported extensions, dependency dirs (node_modules, __pycache__, etc.)
    """
    root = Path(repo_path)
    _log(f"Sieving: {root}")

    within_limits, error = check_repo_limits(root)
    if not within_limits:
        raise RuntimeError(error)

    files: list[SievedFile] = []
    skipped = 0
    reasons: dict[str, int] = {}
    max_file_bytes = config.MAX_SINGLE_FILE_KB * 1024

    def skip(reason: str) -> None:
        nonlocal skipped
        skipped += 1
        reasons[reason] = reasons.get(reason, 0) + 1

    def walk(directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir())
        except PermissionError:
            skip("unreadable_dir")
            return

        for entry in entries:
            if entry.is_dir():
                if entry.name in config.SKIP_DIRS:
                    skip(f"skipped_dir:{entry.name}")
                    continue
                if entry.name.startswith("."):
                    skip("hidden_dir")
                    continue
                walk(entry)
            elif entry.is_file():
                if entry.name in config.SKIP_FILES:
                    skip("lock_file")
                    continue
                if entry.name.startswith(".") and entry.name != ".env.example":
                    skip("hidden_file")
                    continue

                size = entry.stat().st_size
                if size == 0:
                    skip("empty_file")
                    continue
                if size > max_file_bytes:
                    skip("oversized_file")
                    continue

                ext = entry.suffix.lower()
                language = config.SUPPORTED_EXTENSIONS.get(ext)
                if not language:
                    skip("unsupported_ext")
                    continue

                if is_binary_file(entry):
                    skip("binary_file")
                    continue

                rel = entry.relative_to(root).as_posix()
                files.append(SievedFile(
                    relative_path=rel,
                    absolute_path=str(entry),
                    language=language,  # type: ignore[arg-type]
                    size_bytes=size,
                ))

    walk(root)
    files.sort(key=lambda f: f.relative_path)

    total_size = sum(f.size_bytes for f in files)
    _log(f"Sieve done: {len(files)} files kept, {skipped} skipped ({total_size // 1024}KB)")

    return SieveResult(
        files=files,
        total_files=len(files),
        total_size_bytes=total_size,
        skipped_files=skipped,
        skipped_reasons=reasons,
    )


def _log(msg: str) -> None:
    print(f"[sieve] {msg}", file=sys.stderr)
