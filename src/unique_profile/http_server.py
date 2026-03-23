"""HTTP server exposing profile data to the Chrome extension.

Run with:
    unique-profile-serve
    # or
    python -m unique_profile.http_server

Port defaults to 27182; override with UNIQUE_PROFILE_HTTP_PORT env var.
Profile dir defaults to ~/.unique-profile; override with UNIQUE_PROFILE_DIR env var.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from unique_profile.profile import ProfileStore

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_PORT = int(os.environ.get("UNIQUE_PROFILE_HTTP_PORT", 27182))
_profile_dir = os.environ.get("UNIQUE_PROFILE_DIR")
store = ProfileStore(profile_dir=_profile_dir)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Unique Profile HTTP API", version="0.1.0")

# Allow requests from Chrome extensions and localhost dev tools.
# chrome-extension://* covers all installed extensions.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "chrome-extension://*",
        "http://localhost",
        "http://127.0.0.1",
    ],
    allow_origin_regex=r"chrome-extension://.*",
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/profile")
def get_profile() -> dict:
    """Return the full profile as JSON."""
    store._data = store._load()
    return store._data


@app.get("/profile/export")
def export_profile(fmt: str = "markdown") -> dict:
    """Export the profile as JSON or markdown text.

    Query params:
        fmt: 'json' or 'markdown' (default: markdown)
    """
    if fmt not in ("json", "markdown"):
        raise HTTPException(status_code=400, detail="fmt must be 'json' or 'markdown'")
    return {"fmt": fmt, "content": store.export_profile(fmt)}


class MemoryIn(BaseModel):
    content: str
    tags: list[str] = []
    source_model: str = "chrome-extension"


@app.post("/profile/memories", status_code=201)
def add_memory(body: MemoryIn) -> dict:
    """Add a new memory entry."""
    memory = store.add_memory(
        content=body.content,
        tags=body.tags,
        source_model=body.source_model,
    )
    return {"status": "saved", "memory": memory}


@app.delete("/profile/memories/{memory_id}")
def delete_memory(memory_id: str) -> dict:
    """Delete a memory by ID."""
    success = store.delete_memory(memory_id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "deleted", "memory_id": memory_id}


@app.get("/health")
def health() -> dict:
    """Liveness check — used by the extension to detect if the server is running."""
    return {"status": "ok", "port": _PORT}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=_PORT)


if __name__ == "__main__":
    main()
