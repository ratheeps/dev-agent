"""Platform-agnostic notification client protocol.

Both ``SlackNotificationClient`` and any future notification clients satisfy
this protocol structurally — no explicit subclassing required.
"""

from __future__ import annotations

from typing import Any, Protocol


class NotificationClient(Protocol):
    """Structural protocol for sending messages and approval requests."""

    async def send_message(self, channel_id: str, message: str) -> Any: ...

    async def send_approval_request(
        self,
        channel_id: str,
        title: str,
        description: str,
        callback_id: str | None = None,
        extra_facts: list[dict[str, str]] | None = None,
    ) -> Any: ...

    async def send_direct_message(self, user_id: str, message: str) -> Any: ...

    async def send_threaded_reply(
        self, channel_id: str, thread_id: str, message: str
    ) -> Any: ...

    async def send_status_card(
        self,
        channel_id: str,
        *,
        jira_key: str,
        current_state: str,
        task_title: str = "",
        pr_url: str = "",
        repo: str = "",
        branch: str = "",
        cost_usd: float = 0.0,
        progress_pct: int = 0,
    ) -> Any: ...
