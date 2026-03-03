"""Profile schema and JSON-based storage layer."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PROFILE_DIR = Path.home() / ".unique-profile"
PROFILE_FILE = "profile.json"


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
    """Reads and writes profile data to a local JSON file."""

    def __init__(self, profile_dir: str | Path | None = None) -> None:
        self.profile_dir = Path(profile_dir) if profile_dir else DEFAULT_PROFILE_DIR
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.profile_dir / PROFILE_FILE
        self._data = self._load()

    # -- persistence ----------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            return json.loads(self._path.read_text(encoding="utf-8"))
        data = _empty_profile()
        self._save(data)
        return data

    def _save(self, data: dict[str, Any] | None = None) -> None:
        if data is not None:
            self._data = data
        self._path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # -- section accessors ----------------------------------------------------

    def get_identity(self) -> dict[str, Any]:
        return self._data.get("identity", {})

    def get_preferences(self) -> dict[str, Any]:
        return self._data.get("preferences", {})

    def get_knowledge_context(self) -> dict[str, Any]:
        return self._data.get("knowledge_context", {})

    def get_memories(self) -> list[dict[str, Any]]:
        return self._data.get("memories", [])

    # -- mutations ------------------------------------------------------------

    def update_section(self, section: str, key: str, value: Any) -> dict[str, Any]:
        """Update a key in a top-level section (identity, preferences, knowledge_context)."""
        if section not in ("identity", "preferences", "knowledge_context"):
            raise ValueError(f"Unknown section: {section}")
        self._data[section][key] = value
        self._save()
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
        self._data["memories"].append(memory)
        self._save()
        return memory

    def confirm_memory(self, memory_id: str) -> bool:
        """Mark a memory as user-confirmed."""
        for mem in self._data["memories"]:
            if mem["id"] == memory_id:
                mem["confidence"] = "user_confirmed"
                self._save()
                return True
        return False

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory by ID."""
        before = len(self._data["memories"])
        self._data["memories"] = [
            m for m in self._data["memories"] if m["id"] != memory_id
        ]
        if len(self._data["memories"]) < before:
            self._save()
            return True
        return False

    def search_memories(self, query: str) -> list[dict[str, Any]]:
        """Simple substring search across memory content and tags.

        A future version could use embeddings for semantic search.
        """
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
