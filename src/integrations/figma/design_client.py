"""Typed async wrapper around Figma MCP tools.

Provides read-only access to Figma files, nodes, styles, and components
through the injected MCP callable.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

from src.schemas.figma import FigmaComponent, FigmaFile, FigmaNode, FigmaStyle

logger = logging.getLogger(__name__)

McpCallFn = Callable[[str, dict[str, Any]], Coroutine[Any, Any, Any]]


class FigmaDesignClient:
    """High-level async Figma client backed by MCP tools.

    Parameters
    ----------
    mcp_call:
        Async callable ``(tool_name, arguments) -> Any`` provided by the
        agent runtime.
    tool_prefix:
        Prefix applied to Figma MCP tool names.
    """

    def __init__(
        self,
        mcp_call: McpCallFn,
        tool_prefix: str = "mcp__figma__",
    ) -> None:
        self._call = mcp_call
        self._prefix = tool_prefix

    def _tool(self, name: str) -> str:
        return f"{self._prefix}{name}"

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    async def get_file(self, file_key: str) -> FigmaFile:
        """Fetch full Figma file metadata and document tree."""
        raw = await self._call(
            self._tool("get_file"),
            {"fileKey": file_key},
        )
        return _parse_file(raw)

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    async def get_node(self, file_key: str, node_id: str) -> FigmaNode:
        """Fetch a specific node from a Figma file.

        Parameters
        ----------
        file_key:
            The Figma file key (from the URL).
        node_id:
            The node ID (e.g. ``"1:23"``).
        """
        raw = await self._call(
            self._tool("get_node"),
            {"fileKey": file_key, "nodeId": node_id},
        )
        node_data = _extract_node(raw, node_id)
        return _parse_node(node_data)

    # ------------------------------------------------------------------
    # Styles
    # ------------------------------------------------------------------

    async def get_styles(self, file_key: str) -> list[FigmaStyle]:
        """Return all published styles in a Figma file."""
        raw = await self._call(
            self._tool("get_file_styles"),
            {"fileKey": file_key},
        )
        return _parse_styles(raw)

    # ------------------------------------------------------------------
    # Components
    # ------------------------------------------------------------------

    async def get_components(self, file_key: str) -> list[FigmaComponent]:
        """Return all published components in a Figma file."""
        raw = await self._call(
            self._tool("get_file_components"),
            {"fileKey": file_key},
        )
        return _parse_components(raw)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_file(raw: Any) -> FigmaFile:
    if isinstance(raw, dict):
        return FigmaFile.model_validate(raw)
    return FigmaFile.model_validate_json(str(raw))


def _extract_node(raw: Any, node_id: str) -> dict[str, Any]:
    """Pull the target node out of a ``GET /files/:key/nodes`` response."""
    if isinstance(raw, dict):
        nodes = raw.get("nodes", {})
        if node_id in nodes:
            node_wrapper = nodes[node_id]
            if isinstance(node_wrapper, dict) and "document" in node_wrapper:
                return node_wrapper["document"]  # type: ignore[no-any-return]
            return node_wrapper  # type: ignore[no-any-return]
        # Might already be the node itself
        if "id" in raw:
            return raw  # type: ignore[return-value]
    return {"id": node_id}


def _parse_node(raw: Any) -> FigmaNode:
    if isinstance(raw, dict):
        return FigmaNode.model_validate(raw)
    return FigmaNode.model_validate_json(str(raw))


def _parse_styles(raw: Any) -> list[FigmaStyle]:
    items: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        meta = raw.get("meta", raw)
        items = meta.get("styles", [])
    elif isinstance(raw, list):
        items = raw
    return [FigmaStyle.model_validate(s) for s in items]


def _parse_components(raw: Any) -> list[FigmaComponent]:
    items: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        meta = raw.get("meta", raw)
        items = meta.get("components", [])
    elif isinstance(raw, list):
        items = raw
    return [FigmaComponent.model_validate(c) for c in items]
