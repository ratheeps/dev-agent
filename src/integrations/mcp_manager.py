"""Central MCP connection manager.

Loads MCP server configuration from ``config/mcp_servers.yaml`` (preferred) or
``.mcp.json`` at the project root and exposes typed integration clients through
a singleton async context manager.

Usage::

    async with MCPManager.create(mcp_call=my_tool_invoker) as mgr:
        issue = await mgr.jira.get_issue("PROJ-123")
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Coroutine
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, Field

from src.integrations.atlassian.confluence_client import ConfluenceClient
from src.integrations.atlassian.jira_client import JiraClient
from src.integrations.figma.design_client import FigmaDesignClient
from src.integrations.github.repo_client import GitHubRepoClient
from src.integrations.playwright.ui_client import PlaywrightUIClient
from src.integrations.teams.notification_client import TeamsNotificationClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Callable protocol that every client uses to invoke an MCP tool
# ---------------------------------------------------------------------------

class MCPCallable(Protocol):
    """Signature of the function that invokes an MCP tool."""

    def __call__(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> Coroutine[Any, Any, Any]: ...


# ---------------------------------------------------------------------------
# Configuration models
# ---------------------------------------------------------------------------

McpCallFn = Callable[[str, dict[str, Any]], Coroutine[Any, Any, Any]]


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server."""

    name: str
    url: str = ""
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class MCPConfig(BaseModel):
    """Root configuration holding all MCP servers."""

    servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class MCPManager:
    """Singleton manager that owns every MCP integration client.

    The manager itself does **not** open network connections; it merely
    constructs typed client wrappers around the provided ``mcp_call``
    callable.  The callable is expected to be supplied by the agent runtime
    (e.g., Claude Code's tool-invocation layer).
    """

    _instance: MCPManager | None = None

    def __init__(self, mcp_call: McpCallFn, config: MCPConfig | None = None) -> None:
        self._mcp_call = mcp_call
        self._config = config or MCPConfig()
        self._jira: JiraClient | None = None
        self._confluence: ConfluenceClient | None = None
        self._github: GitHubRepoClient | None = None
        self._figma: FigmaDesignClient | None = None
        self._teams: TeamsNotificationClient | None = None
        self._playwright: PlaywrightUIClient | None = None

    # -- Singleton factory ---------------------------------------------------

    @classmethod
    def create(
        cls,
        mcp_call: McpCallFn,
        config_path: str | Path | None = None,
    ) -> MCPManager:
        """Return (or create) the singleton manager instance.

        Parameters
        ----------
        mcp_call:
            Async callable that the agent runtime provides for invoking MCP
            tools.  Signature: ``async (tool_name, arguments) -> Any``.
        config_path:
            Optional explicit path to the YAML / JSON config file.  When
            *None* the manager searches ``config/mcp_servers.yaml`` then
            ``.mcp.json`` relative to the project root.
        """
        if cls._instance is not None:
            return cls._instance

        config = cls._load_config(config_path)
        instance = cls(mcp_call=mcp_call, config=config)
        cls._instance = instance
        logger.info("MCPManager initialised with %d server(s)", len(config.servers))
        return instance

    @classmethod
    def reset(cls) -> None:
        """Tear down the singleton (useful in tests)."""
        cls._instance = None

    # -- Config loading ------------------------------------------------------

    @staticmethod
    def _load_config(config_path: str | Path | None = None) -> MCPConfig:
        search_paths: list[Path] = []

        if config_path is not None:
            search_paths.append(Path(config_path))
        else:
            project_root = Path(__file__).resolve().parents[2]
            search_paths.append(project_root / "config" / "mcp_servers.yaml")
            search_paths.append(project_root / ".mcp.json")

        for path in search_paths:
            if not path.is_file():
                continue
            logger.debug("Loading MCP config from %s", path)
            raw_text = path.read_text(encoding="utf-8")

            if path.suffix in {".yaml", ".yml"}:
                raw = yaml.safe_load(raw_text) or {}
            else:
                raw = json.loads(raw_text)

            servers: dict[str, MCPServerConfig] = {}
            raw_servers = raw.get("servers") or raw.get("mcpServers") or {}
            for name, srv_data in raw_servers.items():
                if isinstance(srv_data, dict):
                    srv_data.setdefault("name", name)
                    servers[name] = MCPServerConfig(**srv_data)

            return MCPConfig(servers=servers)

        logger.warning("No MCP config file found; using empty configuration")
        return MCPConfig()

    # -- Typed client accessors ----------------------------------------------

    @property
    def jira(self) -> JiraClient:
        if self._jira is None:
            self._jira = JiraClient(mcp_call=self._mcp_call)
        return self._jira

    @property
    def confluence(self) -> ConfluenceClient:
        if self._confluence is None:
            self._confluence = ConfluenceClient(mcp_call=self._mcp_call)
        return self._confluence

    @property
    def github(self) -> GitHubRepoClient:
        if self._github is None:
            self._github = GitHubRepoClient(mcp_call=self._mcp_call)
        return self._github

    @property
    def figma(self) -> FigmaDesignClient:
        if self._figma is None:
            self._figma = FigmaDesignClient(mcp_call=self._mcp_call)
        return self._figma

    @property
    def teams(self) -> TeamsNotificationClient:
        if self._teams is None:
            self._teams = TeamsNotificationClient(mcp_call=self._mcp_call)
        return self._teams

    @property
    def playwright(self) -> PlaywrightUIClient:
        if self._playwright is None:
            self._playwright = PlaywrightUIClient(mcp_call=self._mcp_call)
        return self._playwright

    # -- Async context manager -----------------------------------------------

    async def __aenter__(self) -> MCPManager:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        MCPManager.reset()
