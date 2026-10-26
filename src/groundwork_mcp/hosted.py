"""Public, commit-keyed architecture-map web endpoint for a hosted deployment."""

import asyncio
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import config
from .cloner import resolve_remote_commit
from .database import claim_public_snapshot, create_job, delete_job, find_completed_snapshot, get_job, init_database
from .pipeline import run_pipeline
from .security import extract_repo_name, validate_repo_url
from .server import get_file_content, get_repo_summary

_requests: dict[str, deque[float]] = defaultdict(deque)
_RATE_WINDOW_SECONDS = 3600
_RATE_MAX = 8


@asynccontextmanager
async def lifespan(_app):
    init_database()
    yield


app = FastAPI(title="Groundwork Public Architecture Index", lifespan=lifespan)


class IndexRequest(BaseModel):
    repo_url: str = Field(max_length=300)
    branch: str = Field(default="", max_length=200)


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(_PAGE)


@app.post("/api/architecture")
async def architecture(body: IndexRequest, request: Request):
    address = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = _requests[address]
    while window and now - window[0] > _RATE_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= _RATE_MAX:
        raise HTTPException(429, "Rate limit reached. Try again later.")
    window.append(now)

    valid, error = validate_repo_url(body.repo_url)
    if not valid:
        raise HTTPException(400, error)
    if config.GITHUB_TOKEN:
        raise HTTPException(503, "Public index must not use a server-wide GitHub token.")

    branch = body.branch.strip() or None
    try:
        commit = await asyncio.to_thread(resolve_remote_commit, body.repo_url, branch)
    except Exception as exc:
        raise HTTPException(502, f"Could not resolve public GitHub repository: {exc}") from exc

    job = find_completed_snapshot(body.repo_url, commit)
    cached = job is not None
    if job is None:
        job_id = str(uuid.uuid4())
        create_job(job_id, body.repo_url, extract_repo_name(body.repo_url), branch or "default")
        claimed, current_id = claim_public_snapshot(body.repo_url, commit, job_id)
        if claimed:
            # Pin the archive to the exact SHA claimed in the shared cache key.
            await run_pipeline(job_id, body.repo_url, commit)
            job = get_job(job_id)
        else:
            delete_job(job_id)
            for _ in range(300):
                job = get_job(current_id)
                if not job or job.status in ("complete", "failed"):
                    break
                await asyncio.sleep(1)
            cached = bool(job and job.status == "complete")
    if not job or job.status != "complete":
        raise HTTPException(502, f"Indexing failed: {job.error_message if job else 'job disappeared'}")

    readme = get_file_content(job.id, "README.md")
    return {
        "repo": job.repo_name,
        "commit_sha": job.commit_sha,
        "job_id": job.id,
        "cached": cached,
        "summary": get_repo_summary(job.id),
        "readme": readme.get("content", readme.get("error", "README.md not found")),
    }


_PAGE = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Groundwork — cited repository architecture</title>
<style>
body{font:16px system-ui;max-width:900px;margin:48px auto;padding:0 20px;color:#182230}h1{margin-bottom:8px}p{color:#536273}form{display:flex;gap:8px;margin:28px 0}input{flex:1;padding:12px;border:1px solid #bac5d1;border-radius:8px;font:inherit}button{padding:12px 18px;border:0;border-radius:8px;background:#175cd3;color:white;font:inherit;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:18px;border-radius:10px}#status{min-height:24px}
</style>
<h1>Groundwork</h1><p>Paste a public GitHub repository to see its indexed architecture and source evidence, pinned to a commit.</p>
<form id="form"><input id="repo" type="url" placeholder="https://github.com/owner/repo" required><button>Map repository</button></form>
<div id="status" role="status"></div><section id="result" hidden><h2 id="title"></h2><p id="commit"></p><h3>Architecture</h3><pre id="summary"></pre><h3>README evidence</h3><pre id="readme"></pre></section>
<script>document.querySelector('#form').addEventListener('submit',async e=>{e.preventDefault();const status=document.querySelector('#status'),result=document.querySelector('#result');result.hidden=true;status.textContent='Resolving commit and checking the shared index…';try{const r=await fetch('/api/architecture',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({repo_url:document.querySelector('#repo').value})});const data=await r.json();if(!r.ok)throw Error(data.detail||'Request failed');document.querySelector('#title').textContent=data.repo;document.querySelector('#commit').textContent='Commit '+data.commit_sha+' · job '+data.job_id;document.querySelector('#summary').textContent=typeof data.summary==='string'?data.summary:JSON.stringify(data.summary,null,2);document.querySelector('#readme').textContent=data.readme;result.hidden=false;status.textContent='Ready. All indexed source stays on this host.'}catch(err){status.textContent=err.message}});</script></html>"""


def main():
    import uvicorn

    uvicorn.run("groundwork_mcp.hosted:app", host="0.0.0.0", port=int(__import__("os").environ.get("GROUNDWORK_WEB_PORT", "8080")))


if __name__ == "__main__":
    main()
