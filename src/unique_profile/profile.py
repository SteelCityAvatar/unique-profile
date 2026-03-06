"""Profile schema and JSON-based storage layer with file locking."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator


DEFAULT_PROFILE_DIR = Path.home() / ".unique-profile"
PROFILE_FILE = "profile.json"

# -- File locking -------------------------------------------------------------
#
# We use OS-level advisory locks to prevent race conditions when multiple
# MCP clients read/write the profile simultaneously.
#
# How it works:
#   1. Open the file
#   2. Ask the OS to lock it (exclusive lock for writes, shared for reads)
#   3. If another process holds the lock, we retry with exponential backoff
#   4. Do our read/write
#   5. Release the lock (close the file)
#
# Why OS locks instead of lock files?
#   - If our process crashes, the OS automatically releases the lock
#   - No "stale lock" cleanup needed
#   - Zero dependencies
#
# Platform difference:
#   - Unix (Linux/Mac): fcntl.flock() — locks the file descriptor
#   - Windows: msvcrt.locking() — locks a byte range of the file
#   Both achieve the same result: mutual exclusion at the OS level.
# -----------------------------------------------------------------------------

# Backoff schedule: retry up to 5 times with increasing delays (total ~310ms)
_LOCK_RETRIES = 8
_LOCK_INITIAL_DELAY = 0.02  # 20ms


def _lock_file(f: Any) -> None:
    """Acquire an exclusive lock on an open file handle.

    On Unix, fcntl.flock() locks the entire file.
    On Windows, msvcrt.locking() locks the first byte (enough to act as a mutex).
    """
    if sys.platform == "win32":
        import msvcrt
        # LK_NBLCK = non-blocking exclusive lock on 1 byte
        # Raises OSError if the lock is already held
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        # LOCK_EX = exclusive, LOCK_NB = non-blocking (raise if can't lock)
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(f: Any) -> None:
    """Release the lock on an open file handle."""
    if sys.platform == "win32":
        import msvcrt
        # Seek back to 0 before unlocking the same byte we locked
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


@contextmanager
def locked_file(path: Path, mode: str = "r+") -> Generator[Any, None, None]:
    """Context manager that opens a file with an exclusive OS lock and retry.

    Usage:
        with locked_file(path, "r+") as f:
            data = json.load(f)
            data["key"] = "value"
            f.seek(0)
            f.truncate()
            json.dump(data, f)

    If the lock can't be acquired after retries, raises TimeoutError.
    """
    delay = _LOCK_INITIAL_DELAY

    for attempt in range(_LOCK_RETRIES):
        f = open(path, mode, encoding="utf-8")
        try:
            _lock_file(f)
            # Lock acquired — yield the file handle to the caller
            try:
                yield f
            finally:
                _unlock_file(f)
                f.close()
            return  # success, exit the retry loop
        except OSError:
            # Lock is held by another process — close and retry
            f.close()
            if attempt < _LOCK_RETRIES - 1:
                time.sleep(delay)
                delay *= 2  # exponential backoff: 10ms, 20ms, 40ms, 80ms, 160ms

    raise TimeoutError(
        f"Could not acquire lock on {path} after {_LOCK_RETRIES} attempts"
    )


def _empty_profile() -> dict[str, Any]:
    return {
        "identity": {
            "name": "",
            "background": "",
            "profession": "",
            "location": "",
            "languages": [],
        },
        "preferences": {
            "communication_style": "direct",
            "explanation_depth": "intermediate",
            "humor": True,
            "formality": "casual",
        },
        "knowledge_context": {
            "ongoing_projects": [],
            "skills": [],
            "interests": [],
        },
        "memories": [],
    }


class ProfileStore:
    """Reads and writes profile data to a local JSON file with OS-level locking.

    Every mutation follows the pattern:
        1. Open file with exclusive lock (retry with backoff if contended)
        2. Re-read the file (another process may have changed it since we last read)
        3. Apply the mutation
        4. Write back and release lock

    This ensures no lost updates even with multiple concurrent MCP clients.
    """

    def __init__(self, profile_dir: str | Path | None = None) -> None:
        self.profile_dir = Path(profile_dir) if profile_dir else DEFAULT_PROFILE_DIR
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.profile_dir / PROFILE_FILE
        self._ensure_file_exists()
        self._data = self._load()

    def _ensure_file_exists(self) -> None:
        """Create the profile file with defaults if it doesn't exist."""
        if not self._path.exists():
            self._path.write_text(
                json.dumps(_empty_profile(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    # -- persistence ----------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        """Read the profile from disk with retry for Windows lock contention."""
        delay = _LOCK_INITIAL_DELAY
        for attempt in range(_LOCK_RETRIES):
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except PermissionError:
                if attempt < _LOCK_RETRIES - 1:
                    time.sleep(delay)
                    delay *= 2
        return json.loads(self._path.read_text(encoding="utf-8"))

    def _locked_update(self, mutate_fn: Any) -> None:
        """Acquire lock, re-read file, apply mutation, write back, release lock.

        This is the core pattern for all writes. The mutate_fn receives the
        current data dict and modifies it in place.
        """
        with locked_file(self._path, "r+") as f:
            # Re-read from disk under lock (another process may have written)
            raw = f.read()
            data = json.loads(raw)

            # Apply the caller's mutation to the fresh data
            mutate_fn(data)

            # Write back under the same lock
            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2, ensure_ascii=False)

            # Update our in-memory copy
            self._data = data

    # -- section accessors (reads — no lock needed) ---------------------------

    def get_identity(self) -> dict[str, Any]:
        return self._data.get("identity", {})

    def get_preferences(self) -> dict[str, Any]:
        return self._data.get("preferences", {})

    def get_knowledge_context(self) -> dict[str, Any]:
        return self._data.get("knowledge_context", {})

    def get_memories(self) -> list[dict[str, Any]]:
        return self._data.get("memories", [])

    # -- mutations (all go through _locked_update) ----------------------------

    def update_section(self, section: str, key: str, value: Any) -> dict[str, Any]:
        """Update a key in a top-level section (identity, preferences, knowledge_context)."""
        if section not in ("identity", "preferences", "knowledge_context"):
            raise ValueError(f"Unknown section: {section}")

        def mutate(data: dict[str, Any]) -> None:
            data[section][key] = value

        self._locked_update(mutate)
        return self._data[section]

    def add_memory(
        self,
        content: str,
        tags: list[str] | None = None,
        source_model: str = "unknown",
    ) -> dict[str, Any]:
        """Add a memory entry with provenance tracking."""
        memory = {
            "id": f"mem_{uuid.uuid4().hex[:8]}",
            "content": content,
            "tags": tags or [],
            "source_model": source_model,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "confidence": "auto_inferred",
        }

        def mutate(data: dict[str, Any]) -> None:
            data["memories"].append(memory)

        self._locked_update(mutate)
        return memory

    def confirm_memory(self, memory_id: str) -> bool:
        """Mark a memory as user-confirmed."""
        found = False

        def mutate(data: dict[str, Any]) -> None:
            nonlocal found
            for mem in data["memories"]:
                if mem["id"] == memory_id:
                    mem["confidence"] = "user_confirmed"
                    found = True
                    return

        self._locked_update(mutate)
        return found

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory by ID."""
        found = False

        def mutate(data: dict[str, Any]) -> None:
            nonlocal found
            before = len(data["memories"])
            data["memories"] = [
                m for m in data["memories"] if m["id"] != memory_id
            ]
            found = len(data["memories"]) < before

        self._locked_update(mutate)
        return found

    def search_memories(self, query: str) -> list[dict[str, Any]]:
        """Simple substring search across memory content and tags.

        A future version could use embeddings for semantic search.
        """
        # Re-read from disk for fresh data (read-only, no lock needed)
        self._data = self._load()
        query_lower = query.lower()
        results = []
        for mem in self._data["memories"]:
            if query_lower in mem["content"].lower() or any(
                query_lower in tag.lower() for tag in mem.get("tags", [])
            ):
                results.append(mem)
        return results

    def export_profile(self, fmt: str = "json") -> str:
        """Export the full profile as a string."""
        # Re-read from disk for fresh data
        self._data = self._load()
        if fmt == "json":
            return json.dumps(self._data, indent=2, ensure_ascii=False)
        if fmt == "markdown":
            return self._to_markdown()
        raise ValueError(f"Unsupported format: {fmt}")

    def _to_markdown(self) -> str:
        lines: list[str] = []
        identity = self.get_identity()
        lines.append("# Profile")
        for k, v in identity.items():
            if v:
                lines.append(f"- **{k}**: {v}")

        prefs = self.get_preferences()
        lines.append("\n## Preferences")
        for k, v in prefs.items():
            lines.append(f"- **{k}**: {v}")

        ctx = self.get_knowledge_context()
        if ctx.get("skills"):
            lines.append(f"\n## Skills\n{', '.join(ctx['skills'])}")
        if ctx.get("interests"):
            lines.append(f"\n## Interests\n{', '.join(ctx['interests'])}")
        if ctx.get("ongoing_projects"):
            lines.append("\n## Ongoing Projects")
            for proj in ctx["ongoing_projects"]:
                lines.append(f"- **{proj.get('name', 'Untitled')}**: {proj.get('notes', '')}")

        memories = self.get_memories()
        if memories:
            lines.append(f"\n## Memories ({len(memories)})")
            for mem in memories[-10:]:  # last 10
                lines.append(f"- [{mem['timestamp'][:10]}] {mem['content'][:120]}")

        return "\n".join(lines)
