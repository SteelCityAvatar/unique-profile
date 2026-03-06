# Decision Log

Every technical decision made during development, in chronological order.

---

## 001 — OS-level file locking over lock files (2026-03-03)

**Context:** Multiple MCP clients (Claude, Codex, etc.) can write to `profile.json` simultaneously.

**Decision:** Use OS-level advisory locks (`fcntl.flock` on Unix, `msvcrt.locking` on Windows) instead of lock files (`.lock` sentinel files).

**Rationale:**
- If the process crashes, the OS automatically releases the lock — no stale lock cleanup
- Zero dependencies (stdlib only)
- Small code footprint (~30 lines)

**Trade-off:** Doesn't work over NFS/network drives. Acceptable for v0.1 since the profile is local.

See `docs/file-locking-design.md` for the full analysis of alternatives.

---

## 002 — Exponential backoff on lock contention (2026-03-03)

**Context:** When a lock is held by another process, we need a retry strategy.

**Decision:** Retry with exponential backoff rather than blocking or failing immediately.

**Original config:** 5 retries, 10ms initial delay (~310ms max wait).

**Rationale:** Brief contention is expected (JSON read-modify-write is fast). Exponential backoff avoids thundering herd while keeping latency low for the common uncontended case.

---

## 003 — Bumped lock retries from 5/10ms to 8/20ms (2026-03-05)

**Context:** Concurrency tests with 5 parallel worker processes were timing out on Windows.

**Decision:** Increased to 8 retries with 20ms initial delay (~5.1s max wait).

**Rationale:** Windows `msvcrt.locking()` is mandatory (not advisory like Unix `fcntl`), creating more contention. The original budget was too tight for real multi-process scenarios — exactly the case when Claude and Codex both write to the profile.

---

## 004 — Added retry logic to `_load()` for Windows compatibility (2026-03-05)

**Context:** On Windows, `msvcrt.locking()` blocks even plain file reads (not just writes). The `_load()` method in `__init__` was failing with `PermissionError` when another process held the lock.

**Decision:** Added the same retry-with-backoff pattern to `_load()` that we already use for writes.

**Rationale:** Unix advisory locks don't block readers, but Windows mandatory locks do. Without this fix, a second MCP client starting up while the first is mid-write would crash on init. Caught by the concurrent writes test.

---

## 005 — Profile data is user-owned, seeded from a template (2026-03-05)

**Context:** The profile needs to be populated with real user data (identity, preferences, skills, memories) so that any MCP client gets useful context.

**Decision:** Profile lives at `~/.unique-profile/profile.json`. Seeded manually or via the `update_profile` / `add_memory` tools. No auto-inference from conversation history in v0.1.

**Rationale:** User ownership and explicit control are core to the project. Auto-inference can be added later with a `confidence: auto_inferred` flag (already in the schema).

---

## 006 — Test strategy: real-world functional tests (2026-03-05)

**Context:** Needed to validate the ProfileStore works correctly end-to-end.

**Decision:** Tests in `tests/test_profile.py` cover:
- Init (dir creation, file creation, loading existing profiles)
- CRUD on all sections (identity, preferences, knowledge_context)
- Full memory lifecycle (add → search → confirm → delete)
- Export (JSON and markdown)
- File locking (context manager, re-read under lock, concurrent multi-process writes, lock timeout)

The concurrency test spawns 5 real subprocesses each writing 4 memories, then asserts all 20 are present. This directly validates the locking mechanism under the exact conditions we'll see with Claude + Codex.

**Rationale:** Real subprocess-based concurrency tests over mocking — we need to prove the OS locks actually work, not that our mock cooperates.
