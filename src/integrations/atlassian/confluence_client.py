"""Typed async wrapper around the Atlassian MCP ``fetch`` tool for Confluence.

Confluence does not have dedicated MCP tool names in the Atlassian MCP server;
instead we use the generic ``fetch`` tool to call the Confluence REST API v2
endpoints.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

from src.schemas.atlassian import ConfluencePage, ConfluenceSearchResult

logger = logging.getLogger(__name__)

McpCallFn = Callable[[str, dict[str, Any]], Coroutine[Any, Any, Any]]

_CONFLUENCE_API_BASE = "/wiki/api/v2"


class ConfluenceClient:
    """High-level async Confluence client backed by the Atlassian MCP ``fetch`` tool.

    Parameters
    ----------
    mcp_call:
        Async callable ``(tool_name, arguments) -> Any`` provided by the
        agent runtime.
    """

    def __init__(self, mcp_call: McpCallFn) -> None:
        self._call = mcp_call

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    async def get_page(self, page_id: str) -> ConfluencePage:
        """Retrieve a Confluence page by its numeric ID.

        Returns metadata (title, status, version) but **not** the rendered
        body.  Use :meth:`get_page_content` to fetch the storage-format body.
        """
        url = f"{_CONFLUENCE_API_BASE}/pages/{page_id}"
        raw = await self._fetch(url)
        return _parse_page(raw)

    async def get_page_content(self, page_id: str) -> ConfluencePage:
        """Retrieve a page together with its storage-format body content."""
        url = (
            f"{_CONFLUENCE_API_BASE}/pages/{page_id}"
            "?body-format=storage"
        )
        raw = await self._fetch(url)
        return _parse_page(raw)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_pages(
        self,
        query: str,
        space_key: str | None = None,
        limit: int = 25,
    ) -> ConfluenceSearchResult:
        """Search for pages using CQL via the Confluence search endpoint.

        Parameters
        ----------
        query:
            Free-text search term.
        space_key:
            Optional space key to restrict the search.
        limit:
            Maximum number of results (default 25).
        """
        cql_parts = [f'type=page AND text~"{query}"']
        if space_key:
            cql_parts.append(f'space.key="{space_key}"')
        cql = " AND ".join(cql_parts)

        url = f"/wiki/rest/api/content/search?cql={cql}&limit={limit}"
        raw = await self._fetch(url)
        return _parse_search_result(raw)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _fetch(self, relative_url: str) -> Any:
        """Call the Atlassian MCP ``fetch`` tool with the given URL path."""
        result = await self._call(
            "mcp__claude_ai_Atlassian__fetch",
            {"url": relative_url},
        )
        return result


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_page(raw: Any) -> ConfluencePage:
    if isinstance(raw, dict):
        page_data: dict[str, Any] = dict(raw)
        # Flatten space key if nested
        space = page_data.pop("space", None)
        if isinstance(space, dict) and "key" in space:
            page_data.setdefault("space_key", space["key"])
        return ConfluencePage.model_validate(page_data)
    return ConfluencePage.model_validate_json(str(raw))


def _parse_search_result(raw: Any) -> ConfluenceSearchResult:
    if isinstance(raw, dict):
        results_raw: list[dict[str, Any]] = raw.get("results", [])
        pages = [_parse_page(r) for r in results_raw]
        return ConfluenceSearchResult(
            start=int(raw.get("start", 0)),
            limit=int(raw.get("limit", 25)),
            **{"totalSize": int(raw.get("totalSize", raw.get("size", len(pages))))},
            results=pages,
        )
    return ConfluenceSearchResult.model_validate_json(str(raw))
