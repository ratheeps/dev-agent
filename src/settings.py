"""Centralized settings — single source of truth for externalized configuration.

Reads from environment variables (prefixed ``MASON_``) and ``.env`` files via
pydantic-settings.  All hardcoded org names, channel IDs, model IDs, and paths
that previously lived in source code are consolidated here.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class MasonSettings(BaseSettings):
    """Project-wide settings loaded from environment / ``.env``."""

    # Organization / Project
    org: str = "giftbee"
    project: str = "mason"
    workspace_root: str = ""

    # Slack credentials and channels
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    slack_app_token: str = ""  # xapp-... for Socket Mode (optional)
    slack_notification_channel: str = "mason-notifications"
    slack_approval_channel: str = "mason-approvals"
    slack_agent_user_id: str = ""  # bot's own user ID for @mention detection

    # Bedrock model IDs
    opus_model_id: str = "us.anthropic.claude-opus-4-6-20250609-v1:0"
    sonnet_model_id: str = "us.anthropic.claude-sonnet-4-6-20250514-v1:0"

    # Terraform state backend
    tf_state_bucket: str = "giftbee-tofu-state"
    tf_lock_table: str = "giftbee-tofu-locks"

    model_config = SettingsConfigDict(
        env_prefix="MASON_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> MasonSettings:
    """Return the cached settings singleton."""
    return MasonSettings()
