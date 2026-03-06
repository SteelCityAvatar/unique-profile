# Test Summary

All tests live in `tests/test_profile.py` and run against a fresh `ProfileStore` backed by a temp directory (via pytest's `tmp_path`).

---

## TestInit (3 tests)
- **test_creates_profile_dir** — Creates a store pointing at a nested dir that doesn't exist, asserts it gets created
- **test_creates_default_profile_file** — Asserts `profile.json` exists on disk and matches the empty profile template
- **test_loads_existing_profile** — Pre-writes a profile to disk, creates a store, asserts it picks up the existing data on init

## TestAccessors (4 tests)
- **test_get_identity** — Asserts identity dict contains expected keys
- **test_get_preferences_defaults** — Asserts default values: `communication_style == "direct"`, `humor == True`
- **test_get_knowledge_context** — Asserts `skills` and `ongoing_projects` start as empty lists
- **test_get_memories_empty** — Asserts memories start as `[]`

## TestUpdateSection (6 tests)
- **test_update_identity_field** — Sets a field, asserts it in the return value and via accessor
- **test_update_preferences** — Updates formality, asserts it sticks
- **test_update_knowledge_context** — Sets skills list, asserts it
- **test_update_persists_to_disk** — Updates a field, reads raw JSON from disk, asserts it's there
- **test_update_invalid_section_raises** — Passes an invalid section name, expects `ValueError`
- **test_multiple_updates_dont_overwrite_each_other** — Sets two different fields sequentially, asserts both are present (catches read-modify-write clobber bugs)

## TestMemories (11 tests)
- **test_add_memory_returns_entry** — Adds a memory with content/tags/source_model, asserts all fields: `id` prefix, `confidence`, timestamp
- **test_add_memory_persists** — Adds a memory, reads raw JSON from disk, asserts count
- **test_add_multiple_memories** — Adds 3 memories, asserts count is 3
- **test_memory_ids_are_unique** — Adds 20 memories, collects IDs into a set, asserts no collisions
- **test_search_by_content** — Adds two memories, searches by keyword, asserts only the matching one returns
- **test_search_by_tag** — Adds memories with different tags, searches by tag, asserts correct filtering
- **test_search_case_insensitive** — Asserts search works regardless of case in query or content
- **test_search_no_results** — Searches for a nonexistent term, asserts empty result
- **test_confirm_memory** — Adds a memory (`auto_inferred`), confirms it, asserts confidence changes to `user_confirmed`
- **test_confirm_nonexistent_returns_false** — Tries to confirm a fake ID, asserts `False`
- **test_delete_memory** — Adds then deletes, asserts empty list
- **test_delete_nonexistent_returns_false** — Tries to delete a fake ID, asserts `False`
- **test_delete_only_removes_target** — Adds two, deletes one, asserts the other survives

## TestExport (3 tests)
- **test_export_json** — Updates a field, exports as JSON, parses it, asserts the field is present
- **test_export_markdown** — Updates a field and adds a memory, exports as markdown, asserts expected headings and content appear
- **test_export_invalid_format_raises** — Passes `"xml"`, expects `ValueError`

## TestFileLocking (4 tests)
- **test_locked_file_context_manager** — Opens the file with `locked_file`, does a read-modify-write inside the lock, asserts the write landed on disk
- **test_locked_update_rereads_from_disk** — Writes directly to disk (simulating an external process), then calls `update_section`. Asserts both the external change and the new update are present — proves `_locked_update` re-reads under lock instead of using stale in-memory data
- **test_concurrent_writes_no_lost_updates** — Spawns 5 real subprocesses, each adding 4 memories (20 total). Asserts all 20 are in the file. If locking is broken, the count will be less than 20 due to lost updates
- **test_lock_timeout_raises** — Holds a lock externally, then tries `locked_file` on the same path, asserts `TimeoutError` after retries are exhausted
