"""Tests for ProfileStore — CRUD operations, file locking, and concurrency."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from unique_profile.profile import ProfileStore, locked_file, _empty_profile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path: Path) -> ProfileStore:
    """Fresh ProfileStore backed by a temp directory."""
    return ProfileStore(profile_dir=tmp_path)


@pytest.fixture()
def profile_path(store: ProfileStore) -> Path:
    return store._path


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInit:
    def test_creates_profile_dir(self, tmp_path: Path) -> None:
        target = tmp_path / "subdir" / "nested"
        ProfileStore(profile_dir=target)
        assert target.is_dir()

    def test_creates_default_profile_file(self, store: ProfileStore, profile_path: Path) -> None:
        assert profile_path.exists()
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        assert data == _empty_profile()

    def test_loads_existing_profile(self, tmp_path: Path) -> None:
        profile = _empty_profile()
        profile["identity"]["name"] = "John Doe"
        (tmp_path / "profile.json").write_text(json.dumps(profile), encoding="utf-8")

        store = ProfileStore(profile_dir=tmp_path)
        assert store.get_identity()["name"] == "John Doe"


# ---------------------------------------------------------------------------
# Section accessors
# ---------------------------------------------------------------------------

class TestAccessors:
    def test_get_identity(self, store: ProfileStore) -> None:
        assert "name" in store.get_identity()

    def test_get_preferences_defaults(self, store: ProfileStore) -> None:
        prefs = store.get_preferences()
        assert prefs["communication_style"] == "direct"
        assert prefs["humor"] is True

    def test_get_knowledge_context(self, store: ProfileStore) -> None:
        ctx = store.get_knowledge_context()
        assert ctx["skills"] == []
        assert ctx["ongoing_projects"] == []

    def test_get_memories_empty(self, store: ProfileStore) -> None:
        assert store.get_memories() == []


# ---------------------------------------------------------------------------
# update_section
# ---------------------------------------------------------------------------

class TestUpdateSection:
    def test_update_identity_field(self, store: ProfileStore) -> None:
        result = store.update_section("identity", "name", "John Doe")
        assert result["name"] == "John Doe"
        assert store.get_identity()["name"] == "John Doe"

    def test_update_preferences(self, store: ProfileStore) -> None:
        store.update_section("preferences", "formality", "professional")
        assert store.get_preferences()["formality"] == "professional"

    def test_update_knowledge_context(self, store: ProfileStore) -> None:
        store.update_section("knowledge_context", "skills", ["Python", "MCP"])
        assert store.get_knowledge_context()["skills"] == ["Python", "MCP"]

    def test_update_persists_to_disk(self, store: ProfileStore, profile_path: Path) -> None:
        store.update_section("identity", "location", "New York")
        on_disk = json.loads(profile_path.read_text(encoding="utf-8"))
        assert on_disk["identity"]["location"] == "New York"

    def test_update_invalid_section_raises(self, store: ProfileStore) -> None:
        with pytest.raises(ValueError, match="Unknown section"):
            store.update_section("nonexistent", "key", "val")

    def test_multiple_updates_dont_overwrite_each_other(self, store: ProfileStore) -> None:
        store.update_section("identity", "name", "John Doe")
        store.update_section("identity", "location", "New York")
        identity = store.get_identity()
        assert identity["name"] == "John Doe"
        assert identity["location"] == "New York"


# ---------------------------------------------------------------------------
# Memories — add, search, confirm, delete
# ---------------------------------------------------------------------------

class TestMemories:
    def test_add_memory_returns_entry(self, store: ProfileStore) -> None:
        mem = store.add_memory("Loves Python", tags=["preference"], source_model="claude-opus-4-6")
        assert mem["content"] == "Loves Python"
        assert mem["tags"] == ["preference"]
        assert mem["source_model"] == "claude-opus-4-6"
        assert mem["id"].startswith("mem_")
        assert mem["confidence"] == "auto_inferred"
        assert "timestamp" in mem

    def test_add_memory_persists(self, store: ProfileStore, profile_path: Path) -> None:
        store.add_memory("Test memory")
        on_disk = json.loads(profile_path.read_text(encoding="utf-8"))
        assert len(on_disk["memories"]) == 1

    def test_add_multiple_memories(self, store: ProfileStore) -> None:
        store.add_memory("First")
        store.add_memory("Second")
        store.add_memory("Third")
        assert len(store.get_memories()) == 3

    def test_memory_ids_are_unique(self, store: ProfileStore) -> None:
        ids = {store.add_memory(f"mem {i}")["id"] for i in range(20)}
        assert len(ids) == 20

    def test_search_by_content(self, store: ProfileStore) -> None:
        store.add_memory("Prefers dark mode")
        store.add_memory("Uses vim keybindings")
        results = store.search_memories("dark")
        assert len(results) == 1
        assert results[0]["content"] == "Prefers dark mode"

    def test_search_by_tag(self, store: ProfileStore) -> None:
        store.add_memory("Uses Python 3.12", tags=["tooling"])
        store.add_memory("Likes coffee", tags=["personal"])
        results = store.search_memories("tooling")
        assert len(results) == 1

    def test_search_case_insensitive(self, store: ProfileStore) -> None:
        store.add_memory("Loves RUST programming")
        assert len(store.search_memories("rust")) == 1
        assert len(store.search_memories("LOVES")) == 1

    def test_search_no_results(self, store: ProfileStore) -> None:
        store.add_memory("Something")
        assert store.search_memories("nonexistent") == []

    def test_confirm_memory(self, store: ProfileStore) -> None:
        mem = store.add_memory("Auto-detected fact")
        assert mem["confidence"] == "auto_inferred"

        assert store.confirm_memory(mem["id"]) is True
        confirmed = [m for m in store.get_memories() if m["id"] == mem["id"]][0]
        assert confirmed["confidence"] == "user_confirmed"

    def test_confirm_nonexistent_returns_false(self, store: ProfileStore) -> None:
        assert store.confirm_memory("mem_doesnotexist") is False

    def test_delete_memory(self, store: ProfileStore) -> None:
        mem = store.add_memory("To be deleted")
        assert store.delete_memory(mem["id"]) is True
        assert store.get_memories() == []

    def test_delete_nonexistent_returns_false(self, store: ProfileStore) -> None:
        assert store.delete_memory("mem_doesnotexist") is False

    def test_delete_only_removes_target(self, store: ProfileStore) -> None:
        m1 = store.add_memory("Keep me")
        m2 = store.add_memory("Delete me")
        store.delete_memory(m2["id"])
        remaining = store.get_memories()
        assert len(remaining) == 1
        assert remaining[0]["id"] == m1["id"]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class TestExport:
    def test_export_json(self, store: ProfileStore) -> None:
        store.update_section("identity", "name", "John Doe")
        exported = store.export_profile("json")
        data = json.loads(exported)
        assert data["identity"]["name"] == "John Doe"

    def test_export_markdown(self, store: ProfileStore) -> None:
        store.update_section("identity", "name", "John Doe")
        store.add_memory("Test memory")
        md = store.export_profile("markdown")
        assert "# Profile" in md
        assert "John Doe" in md
        assert "Memories" in md

    def test_export_invalid_format_raises(self, store: ProfileStore) -> None:
        with pytest.raises(ValueError, match="Unsupported format"):
            store.export_profile("xml")


# ---------------------------------------------------------------------------
# File locking
# ---------------------------------------------------------------------------

class TestFileLocking:
    def test_locked_file_context_manager(self, profile_path: Path) -> None:
        """Basic smoke test: lock, read, write, release."""
        with locked_file(profile_path, "r+") as f:
            data = json.load(f)
            data["identity"]["name"] = "Locked Write"
            f.seek(0)
            f.truncate()
            json.dump(data, f)

        result = json.loads(profile_path.read_text(encoding="utf-8"))
        assert result["identity"]["name"] == "Locked Write"

    def test_locked_update_rereads_from_disk(self, store: ProfileStore, profile_path: Path) -> None:
        """Verify _locked_update sees changes made by external writers."""
        # Simulate another process writing directly to disk
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        data["identity"]["name"] = "External Writer"
        profile_path.write_text(json.dumps(data), encoding="utf-8")

        # Our store's in-memory cache is stale, but _locked_update re-reads
        store.update_section("identity", "location", "New York")

        # Both the external write AND our update should be present
        final = json.loads(profile_path.read_text(encoding="utf-8"))
        assert final["identity"]["name"] == "External Writer"
        assert final["identity"]["location"] == "New York"

    def test_concurrent_writes_no_lost_updates(self, tmp_path: Path) -> None:
        """Spawn multiple processes that each add a memory — none should be lost.

        This is the key concurrency test: it proves that file locking prevents
        the classic read-modify-write race condition.
        """
        profile_dir = tmp_path / "concurrent"
        profile_dir.mkdir()
        profile_file = profile_dir / "profile.json"
        profile_file.write_text(json.dumps(_empty_profile()), encoding="utf-8")

        num_workers = 5
        memories_per_worker = 4

        src_path = Path(__file__).resolve().parent.parent / "src"
        worker_script = textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, r"{src_path}")
            from unique_profile.profile import ProfileStore
            worker_id = sys.argv[1]
            store = ProfileStore(profile_dir=r"{profile_dir}")
            for i in range({memories_per_worker}):
                store.add_memory(f"worker_{{worker_id}}_memo_{{i}}", tags=["concurrent"])
        """)

        script_file = tmp_path / "worker.py"
        script_file.write_text(worker_script, encoding="utf-8")

        # Launch all workers in parallel
        procs = []
        for w in range(num_workers):
            p = subprocess.Popen(
                [sys.executable, str(script_file), str(w)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            procs.append(p)

        # Wait for all to finish
        for p in procs:
            stdout, stderr = p.communicate(timeout=30)
            assert p.returncode == 0, f"Worker failed: {stderr.decode()}"

        # Verify: every single memory should be present (no lost updates)
        final = json.loads(profile_file.read_text(encoding="utf-8"))
        expected = num_workers * memories_per_worker
        assert len(final["memories"]) == expected, (
            f"Expected {expected} memories, got {len(final['memories'])}. "
            "Lost updates detected — file locking may be broken."
        )

    def test_lock_timeout_raises(self, profile_path: Path) -> None:
        """If a lock is held and retries are exhausted, TimeoutError is raised."""
        if sys.platform == "win32":
            import msvcrt
            f = open(profile_path, "r+", encoding="utf-8")
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                with pytest.raises(TimeoutError):
                    with locked_file(profile_path, "r+"):
                        pass
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                f.close()
        else:
            import fcntl
            f = open(profile_path, "r+", encoding="utf-8")
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with pytest.raises(TimeoutError):
                    with locked_file(profile_path, "r+"):
                        pass
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                f.close()
