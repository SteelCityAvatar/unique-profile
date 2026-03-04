"""Unique Profile MCP server — resources, tools, and prompts."""

from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP

from unique_profile.profile import ProfileStore

# Allow overriding the profile directory via env var
_profile_dir = os.environ.get("UNIQUE_PROFILE_DIR")
store = ProfileStore(profile_dir=_profile_dir)

mcp = FastMCP("Unique Profile")

# =============================================================================
# Resources — injected into the LLM's context at conversation start
# =============================================================================


@mcp.resource("profile://identity")
def get_identity() -> str:
    """The user's core identity: name, background, profession, location, languages."""
    return json.dumps(store.get_identity(), indent=2)


@mcp.resource("profile://preferences")
def get_preferences() -> str:
    """The user's communication preferences: style, depth, formality, humor."""
    return json.dumps(store.get_preferences(), indent=2)


@mcp.resource("profile://knowledge")
def get_knowledge_context() -> str:
    """The user's skills, interests, and ongoing projects."""
    return json.dumps(store.get_knowledge_context(), indent=2)


@mcp.resource("profile://memories")
def get_memories() -> str:
    """The user's stored memories and conversation summaries."""
    memories = store.get_memories()
    return json.dumps(memories[-50:], indent=2)  # cap at 50 most recent


# =============================================================================
# Tools — called by the LLM during conversation
# =============================================================================


@mcp.tool()
def update_profile(section: str, key: str, value: str) -> str:
    """Update a field in the user's profile.

    Args:
        section: One of 'identity', 'preferences', or 'knowledge_context'.
        key: The field name to update (e.g. 'name', 'location', 'communication_style').
        value: The new value. For list fields, pass a JSON array string.
    """
    # Try to parse JSON values (for lists, dicts)
    parsed_value: object = value
    try:
        parsed_value = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        pass

    result = store.update_section(section, key, parsed_value)
    return json.dumps({"status": "updated", "section": section, "data": result})


@mcp.tool()
def add_memory(content: str, tags: list[str] | None = None, source_model: str = "unknown") -> str:
    """Store a new memory about the user with provenance tracking.

    Args:
        content: The memory content to store.
        tags: Optional tags for categorization (e.g. ['project', 'preference']).
        source_model: The model that created this memory (e.g. 'claude-opus-4-6').
    """
    memory = store.add_memory(content, tags=tags, source_model=source_model)
    return json.dumps({"status": "saved", "memory": memory})


@mcp.tool()
def search_memories(query: str) -> str:
    """Search the user's memories by keyword.

    Args:
        query: Search term to match against memory content and tags.
    """
    results = store.search_memories(query)
    return json.dumps({"results": results, "count": len(results)})


@mcp.tool()
def delete_memory(memory_id: str) -> str:
    """Delete a specific memory by its ID.

    Args:
        memory_id: The memory ID to delete (e.g. 'mem_a1b2c3d4').
    """
    success = store.delete_memory(memory_id)
    status = "deleted" if success else "not_found"
    return json.dumps({"status": status, "memory_id": memory_id})


@mcp.tool()
def confirm_memory(memory_id: str) -> str:
    """Mark a memory as user-confirmed (raises its trust level).

    Args:
        memory_id: The memory ID to confirm.
    """
    success = store.confirm_memory(memory_id)
    status = "confirmed" if success else "not_found"
    return json.dumps({"status": status, "memory_id": memory_id})


@mcp.tool()
def export_profile(fmt: str = "json") -> str:
    """Export the full profile in the specified format.

    Args:
        fmt: Export format — 'json' or 'markdown'.
    """
    return store.export_profile(fmt)


# =============================================================================
# Prompts — reusable prompt templates
# =============================================================================


@mcp.prompt()
def introduce_yourself() -> str:
    """Generate a system prompt injection from the current profile state.

    Returns a formatted summary of the user's identity, preferences, and context
    that can be prepended to any conversation.
    """
    identity = store.get_identity()
    prefs = store.get_preferences()
    ctx = store.get_knowledge_context()
    memories = store.get_memories()

    parts = []
    parts.append("## About the User")

    if identity.get("name"):
        parts.append(f"Name: {identity['name']}")
    if identity.get("profession"):
        parts.append(f"Profession: {identity['profession']}")
    if identity.get("background"):
        parts.append(f"Background: {identity['background']}")
    if identity.get("location"):
        parts.append(f"Location: {identity['location']}")
    if identity.get("languages"):
        parts.append(f"Languages: {', '.join(identity['languages'])}")

    parts.append("\n## Communication Preferences")
    parts.append(f"Style: {prefs.get('communication_style', 'direct')}")
    parts.append(f"Explanation depth: {prefs.get('explanation_depth', 'intermediate')}")
    parts.append(f"Formality: {prefs.get('formality', 'casual')}")
    parts.append(f"Humor: {'yes' if prefs.get('humor') else 'no'}")

    if ctx.get("skills"):
        parts.append(f"\n## Skills\n{', '.join(ctx['skills'])}")
    if ctx.get("interests"):
        parts.append(f"\n## Interests\n{', '.join(ctx['interests'])}")
    if ctx.get("ongoing_projects"):
        parts.append("\n## Current Projects")
        for proj in ctx["ongoing_projects"]:
            parts.append(f"- {proj.get('name', 'Untitled')}: {proj.get('notes', '')}")

    if memories:
        recent = memories[-5:]
        parts.append(f"\n## Recent Memories ({len(memories)} total)")
        for mem in recent:
            parts.append(f"- [{mem['timestamp'][:10]}] {mem['content'][:150]}")

    return "\n".join(parts)


@mcp.prompt()
def summarize_session(conversation_notes: str = "") -> str:
    """Generate a prompt to summarize the current session for saving as a memory.

    Args:
        conversation_notes: Optional notes about the conversation to summarize.
    """
    return (
        "Please summarize the key facts, decisions, and context from this conversation "
        "that would be useful to remember for future sessions. Focus on:\n"
        "- New facts learned about the user\n"
        "- Decisions made or preferences expressed\n"
        "- Project progress or status updates\n"
        "- Any action items or next steps\n\n"
        "Format the summary as concise bullet points.\n"
        f"{f'Additional notes: {conversation_notes}' if conversation_notes else ''}"
    )


# =============================================================================
# Entry point
# =============================================================================


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
