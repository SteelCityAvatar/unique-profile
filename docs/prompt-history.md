# Prompt History

Two sections: (1) development session log — the prompts and decisions from our build sessions, and (2) MCP prompt template versions.

---

# Part 1: Development Session Log

Chronological record of prompts given during development and what they produced.

## Session 1 (2026-03-03)

> Initial scaffold for the MCP server.

- Created project structure: `src/unique_profile/`, `tests/`, `docs/`
- Implemented `ProfileStore` with JSON-based persistence (`profile.py`)
- Implemented MCP server with resources, tools, and prompts (`server.py`)
- Added `pyproject.toml` with `unique-profile` console entry point
- Added `__main__.py` for `python -m unique_profile` support

> Fix Python 3.10 requirement, FastMCP init, and add __main__ entry point.

- Corrected `requires-python` in `pyproject.toml`
- Fixed FastMCP initialization
- Added `__main__.py` entry point

> Add pinned requirements.txt for easy setup on other machines.

- Generated `requirements.txt` from the venv

> Add architecture diagram to README.

- Added Mermaid diagram showing clients → server → storage flow
- Follow-up fix: replaced `\n` with `<br/>` for Mermaid compatibility

## Session 2 (2026-03-05, pre-git)

> Design a file locking mechanism for concurrent access to profile.json.

- Analyzed three options: OS locks, lock files, OS locks + retry
- Chose OS-level locks with exponential backoff (Option 3)
- Implemented cross-platform locking: `fcntl.flock` (Unix) / `msvcrt.locking` (Windows)
- Added `locked_file` context manager and `_locked_update` pattern to `ProfileStore`
- Wrote `docs/file-locking-design.md` documenting the full analysis

## Session 3 (2026-03-05)

> Review the locking mechanism, then write unit tests.

- Reviewed locking code, confirmed the approach
- Wrote 33 tests in `tests/test_profile.py` covering init, CRUD, memory lifecycle, export, and file locking
- Concurrency test: 5 parallel subprocesses × 4 memories each, assert all 20 present

> Run the tests.

- 32 passed, 1 failed: concurrent test hit `TimeoutError` — backoff budget too tight for Windows
- Fix: bumped retries from 5/10ms to 8/20ms (~5.1s max wait)
- Second failure: `PermissionError` on Windows — `msvcrt.locking` is mandatory, blocks even reads
- Fix: added retry-with-backoff to `_load()` method
- Result: 33/33 passing

> Seed real profile data for live MCP testing.

- Populated `~/.unique-profile/profile.json` with user's identity, preferences, skills, projects, and 7 memories
- MCP server config already present in `~/.claude/settings.json`

> Keep a decision log of every technical decision.

- Created `docs/decisions.md` with 6 entries covering locking strategy, backoff tuning, Windows fixes, profile seeding, and test strategy

> Keep PII out of git. Use fake/obfuscated data for the public repo.

- Real profile stays at `~/.unique-profile/profile.json` (local only)
- Tests and example data to use generic placeholder names before pushing
- Commits to be reviewed for PII before push

> Write test summary documentation.

- Created `tests/TEST_SUMMARY.md` with descriptions of all 33 tests, no PII

## Session 4 (2026-03-23) — Chrome Extension + HTTP Companion

> Scope and build a Chrome extension to push the unique profile to AI chat platforms.

**Architecture decisions made:**
- Monorepo: extension lives alongside the MCP server (see Decision 007)
- Local HTTP server over Native Messaging or manual import (see Decision 008)
- HTTP server integrated into the existing package as `http_server.py` (see Decision 009)
- Port 27182, CORS via regex for `chrome-extension://*` (see Decisions 010–011)
- Feature branch: `feature/chrome-extension` off `master`

**PII guardrail:** Added `profile.json` / `!examples/profile.json` to `.gitignore` to block accidental commit of real profile data anywhere in the repo tree.

**Files added this session:**
- `src/unique_profile/http_server.py` — FastAPI wrapper around `ProfileStore`; endpoints: `GET /profile`, `GET /profile/export`, `POST /profile/memories`, `DELETE /profile/memories/{id}`, `GET /health`
- `pyproject.toml` — added `fastapi`, `uvicorn[standard]` deps; new `unique-profile-serve` console script
- `extension/manifest.json` — MV3 manifest; host permissions for localhost + AI chat platforms
- `extension/background.js` — service worker; fetches and caches profile, message hub for content scripts
- `extension/popup/popup.html` + `popup.js` — status UI with per-platform sync controls
- `extension/content-scripts/claude.js` — injects profile into claude.ai Projects custom instructions
- `extension/content-scripts/chatgpt.js` — injects profile into ChatGPT custom instructions
- `extension/content-scripts/gemini.js` — injects profile into Gemini personalization settings
- `docs/chrome-extension.md` — architecture and usage guide for the extension + HTTP server

---

# Part 2: MCP Prompt Template Versions

Version history for prompt templates registered in `server.py`.

---

## `introduce_yourself`

### v1 (2026-03-03) — Initial

Generates a system prompt from the current profile state. Reads all four sections (identity, preferences, knowledge_context, memories) and concatenates them into a structured plaintext block.

**Template logic:**
- Conditionally includes each identity field only if non-empty
- Hardcoded labels for preference fields (Style, Explanation depth, Formality, Humor)
- Lists skills and interests as comma-separated inline text
- Lists ongoing projects as bullet points (`- name: notes`)
- Appends last 5 memories with truncated content (150 chars) and date prefix

**Output format:** Markdown-like headings (`## About the User`, `## Communication Preferences`, etc.)

**Known limitations:**
- No token budget awareness — output length scales with profile size
- No priority weighting — a stale memory gets the same treatment as a confirmed preference
- Skills/interests rendered as flat comma lists, no grouping

---

## `summarize_session`

### v1 (2026-03-03) — Initial

Returns a static instruction prompt that asks the LLM to summarize the current conversation for storage as a memory entry.

**Template logic:**
- Fixed instruction text with four focus areas: new facts, decisions/preferences, project progress, action items
- Accepts optional `conversation_notes` parameter, appended as `Additional notes: {notes}` if provided
- Requests output as concise bullet points

**Output format:** Plain instruction text (not structured data)

**Known limitations:**
- No schema enforcement on the summary output — relies on the LLM to follow the bullet-point format
- No integration with `add_memory` — the caller must take the summary and call `add_memory` separately
- No deduplication guidance — doesn't tell the LLM to check for existing similar memories before saving
