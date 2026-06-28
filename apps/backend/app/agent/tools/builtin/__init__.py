"""Built-in tools for the agent."""

import json
from pathlib import Path


def web_search(query: str) -> str:
    """Search the web for information.

    Args:
        query: The search query string.

    Returns:
        Search results as JSON string.
    """
    # TODO: Integrate with a real search API (Tavily, Brave, etc.)
    return json.dumps({
        "query": query,
        "results": [],
        "note": "Web search not yet configured. Set SEARCH_API_KEY in .env.",
    })


def read_local_file(path: str) -> str:
    """Read a file from the local filesystem.

    Args:
        path: Relative or absolute path to the file.

    Returns:
        File contents as string.
    """
    p = Path(path)
    if not p.exists():
        return f"Error: file not found: {path}"
    return p.read_text(encoding="utf-8")
