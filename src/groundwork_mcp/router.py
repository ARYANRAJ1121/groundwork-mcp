"""
Groundwork MCP — Laya-powered intelligent query router.

Uses Laya's non-autoregressive decision engine to classify user queries
and recommend the best Groundwork tool + arguments. Runs locally in ~33ms
with no API key.

Decision types used:
  - choice: select the right tool from the 11 available
  - score:  estimate query complexity (simple / moderate / complex)
  - noul:   binary checks (needs_job_id, is_code_related)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Lazy-loaded Laya Router ──────────────────────────────────────────────────

_laya_router = None


def _get_router():
    """Lazily initialise the Laya Router on first use."""
    global _laya_router
    if _laya_router is None:
        try:
            from laya import Router
            # OPTIMIZATION: preload=True keeps the checkpoints hot in memory 
            # for instant ~33ms routing, rather than loading on the fly.
            _laya_router = Router(preload=True)
            logger.info("Laya Router initialised (preloaded)")
        except ImportError:
            logger.warning(
                "laya is not installed. "
                "Install with: pip install laya  — falling back to keyword router."
            )
    return _laya_router


# ── Tool descriptions for Laya choice criteria ──────────────────────────────

TOOL_CRITERIA: dict[str, str] = {
    "ingest_repo": (
        "User provides a GitHub URL and wants to clone, ingest, download, or index "
        "a new repository."
    ),
    "get_ingest_status": (
        "User wants to check the progress or status of an ongoing ingestion job. "
        "Keywords: status, progress, how far, is it done."
    ),
    "list_ingested_repos": (
        "User wants to see all repositories that have been ingested. "
        "Keywords: list repos, show repos, what repos, all repos."
    ),
    "get_repo_summary": (
        "User wants a high-level overview of a repo's structure, languages, "
        "symbol counts, dependencies, or architecture. "
        "Keywords: summary, overview, what is this project, architecture, structure."
    ),
    "query_symbols": (
        "User asks where a specific function, class, variable, or symbol is defined "
        "or declared in the code. Keywords: where is <name> defined, find function."
    ),
    "get_import_edges": (
        "User wants to see import/dependency relationships between files. "
        "Keywords: imports, dependencies, what does this file import, who imports."
    ),
    "get_file_content": (
        "User wants to read the content of a specific file (README, source, config). "
        "Keywords: show file, read file, what does file say, show README, file content."
    ),
    "list_repo_files": (
        "User wants to browse or list all files in the repo, optionally filtered "
        "by language or path. Keywords: list files, show files, what files exist."
    ),
    "delete_repo": (
        "User wants to delete or remove a previously ingested repository. "
        "Keywords: delete, remove, clean up, free space."
    ),
    "search_code": (
        "User wants to do a text/grep search across code for strings, config values, "
        "error messages, or variable names. "
        "Keywords: search, find text, grep, where is string, look for."
    ),
    "get_call_graph": (
        "User wants to trace function calls — who calls a function, what a function "
        "calls, or execution flow. "
        "Keywords: call graph, callers, callees, who calls, what calls, trace."
    ),
}

# ── Laya question schema ─────────────────────────────────────────────────────

ROUTING_QUESTIONS: dict[str, dict[str, Any]] = {
    "tool_selection": {
        "type": "choice",
        "instructions": (
            "Given a user's natural-language question about a GitHub repository's "
            "code, structure, or content, select the single best tool to answer it."
        ),
        "criteria": TOOL_CRITERIA,
    },
    "complexity": {
        "type": "score",
        "instructions": "How complex is this query to answer?",
        "criteria": [
            "simple — single tool call with obvious arguments",
            "moderate — may need one or two tool calls",
            "complex — multi-step exploration likely needed",
        ],
    },
    "needs_job_id": {
        "type": "noul",
        "instructions": (
            "Does this query require a job_id to identify which ingested "
            "repository to query? Most exploration queries do."
        ),
    },
    "is_about_specific_file": {
        "type": "noul",
        "instructions": (
            "Does the user mention or ask about a specific file, path, or filename?"
        ),
    },
}


# ── Keyword-based fallback router ────────────────────────────────────────────

_KEYWORD_MAP: list[tuple[list[str], str]] = [
    (["ingest", "clone", "index", "add repo", "scan"], "ingest_repo"),
    (["status", "progress", "done yet", "how far"], "get_ingest_status"),
    (["list repo", "show repo", "all repo", "ingested"], "list_ingested_repos"),
    (["summary", "overview", "architecture", "structure", "about this"], "get_repo_summary"),
    (["symbol", "function", "class", "method", "where is", "defined", "definition"], "query_symbols"),
    (["import", "dependency", "depends", "requires"], "get_import_edges"),
    (["readme", "read file", "show file", "file content", "what does"], "get_file_content"),
    (["list file", "show file", "browse", "what file"], "list_repo_files"),
    (["delete", "remove", "clean up"], "delete_repo"),
    (["search", "grep", "find text", "look for", "where is string"], "search_code"),
    (["call graph", "callers", "callees", "who calls", "trace"], "get_call_graph"),
]


def _keyword_route(query: str) -> dict[str, Any]:
    """Simple keyword-based fallback when Laya is unavailable."""
    q = query.lower()
    for keywords, tool in _KEYWORD_MAP:
        if any(kw in q for kw in keywords):
            return {
                "recommended_tool": tool,
                "confidence": 0.5,
                "complexity": "unknown",
                "needs_job_id": tool not in ("ingest_repo", "list_ingested_repos"),
                "is_about_specific_file": False,
                "method": "keyword_fallback",
            }
    # Default to repo summary if nothing matched
    return {
        "recommended_tool": "get_repo_summary",
        "confidence": 0.2,
        "complexity": "unknown",
        "needs_job_id": True,
        "is_about_specific_file": False,
        "method": "keyword_fallback_default",
    }


# ── Main routing function ────────────────────────────────────────────────────

def route_query(user_query: str) -> dict[str, Any]:
    """
    Classify a user query and recommend the best Groundwork tool.

    Returns a dict with:
        recommended_tool:      str   — tool name
        confidence:            float — Laya confidence (0-1)
        complexity:            str   — "simple" | "moderate" | "complex"
        needs_job_id:          bool  — whether a job_id argument is needed
        is_about_specific_file: bool — whether a file path is mentioned
        method:                str   — "laya" | "keyword_fallback"
        reasoning:             str   — human-readable explanation
    """
    router = _get_router()

    if router is None:
        return _keyword_route(user_query)

    try:
        result = router.predict(user_query, ROUTING_QUESTIONS)
        answers = result["answers"]

        tool_answer = answers["tool_selection"]
        recommended_tool = tool_answer["choice"]
        confidence = tool_answer.get("confidence", 0.0)

        # Map score index to label
        complexity_answer = answers["complexity"]
        score_val = complexity_answer.get("score", 0)
        complexity_labels = ["simple", "moderate", "complex"]
        if isinstance(score_val, (int, float)):
            idx = min(int(round(score_val)), len(complexity_labels) - 1)
            complexity = complexity_labels[max(0, idx)]
        else:
            complexity = "moderate"

        needs_job_id_prob = answers["needs_job_id"].get("noul", 0.5)
        is_about_file_prob = answers["is_about_specific_file"].get("noul", 0.5)

        # Build reasoning
        tool_desc = TOOL_CRITERIA.get(recommended_tool, recommended_tool)
        reasoning_parts = [
            f"Laya classified this as a '{recommended_tool}' query "
            f"(confidence: {confidence:.0%}).",
        ]
        if confidence < 0.5:
            reasoning_parts.append(
                "Low confidence — consider rephrasing or trying the suggested tool "
                "and falling back to get_repo_summary."
            )
        if needs_job_id_prob > 0.5:
            reasoning_parts.append(
                "This query likely requires a job_id. "
                "Use list_ingested_repos() to find available job IDs."
            )

        return {
            "recommended_tool": recommended_tool,
            "confidence": round(confidence, 3),
            "complexity": complexity,
            "needs_job_id": needs_job_id_prob > 0.5,
            "is_about_specific_file": is_about_file_prob > 0.5,
            "method": "laya",
            "routing_metadata": result.get("routing", {}),
            "reasoning": " ".join(reasoning_parts),
        }

    except Exception as e:
        logger.warning("Laya prediction failed: %s — falling back to keywords", e)
        fallback = _keyword_route(user_query)
        fallback["laya_error"] = str(e)
        return fallback
