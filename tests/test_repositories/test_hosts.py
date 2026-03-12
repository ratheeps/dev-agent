"""Tests for HostManager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.repositories.hosts import _MARKER, HostManager


def _make_manager(entries: list[str], hosts_content: str = "") -> tuple[HostManager, Path]:
    """Create a HostManager with a temp hosts file."""
    import tempfile

    hosts_file = Path(tempfile.mktemp())  # noqa: S306
    if hosts_content:
        hosts_file.write_text(hosts_content)

    infra = MagicMock()
    infra.host_entries = entries
    return HostManager(infra_config=infra, hosts_file=hosts_file), hosts_file


class TestHostManagerCheckHosts:
    def test_all_present(self) -> None:
        content = "127.0.0.1 wallet.giftbee.test myaccount.giftbee.test\n"
        manager, hosts_file = _make_manager(
            ["127.0.0.1 wallet.giftbee.test", "127.0.0.1 myaccount.giftbee.test"],
            content,
        )
        try:
            status = manager.check_hosts()
            assert status["wallet.giftbee.test"] is True
            assert status["myaccount.giftbee.test"] is True
        finally:
            hosts_file.unlink(missing_ok=True)

    def test_none_present(self) -> None:
        manager, hosts_file = _make_manager(
            ["127.0.0.1 wallet.giftbee.test"],
            "127.0.0.1 localhost\n",
        )
        try:
            status = manager.check_hosts()
            assert status["wallet.giftbee.test"] is False
        finally:
            hosts_file.unlink(missing_ok=True)

    def test_comment_line_ignored(self) -> None:
        content = "# 127.0.0.1 wallet.giftbee.test\n127.0.0.1 localhost\n"
        manager, hosts_file = _make_manager(
            ["127.0.0.1 wallet.giftbee.test"],
            content,
        )
        try:
            status = manager.check_hosts()
            assert status["wallet.giftbee.test"] is False
        finally:
            hosts_file.unlink(missing_ok=True)

    def test_missing_hosts_file(self) -> None:
        manager, _ = _make_manager(["127.0.0.1 wallet.giftbee.test"])
        # No file created
        status = manager.check_hosts()
        assert status["wallet.giftbee.test"] is False


class TestHostManagerGetMissing:
    def test_all_missing(self) -> None:
        manager, hosts_file = _make_manager(
            ["127.0.0.1 wallet.giftbee.test", "127.0.0.1 pim.giftbee.test"],
            "127.0.0.1 localhost\n",
        )
        try:
            missing = manager.get_missing_entries()
            assert len(missing) == 2
        finally:
            hosts_file.unlink(missing_ok=True)

    def test_none_missing(self) -> None:
        content = "127.0.0.1 wallet.giftbee.test pim.giftbee.test\n"
        manager, hosts_file = _make_manager(
            ["127.0.0.1 wallet.giftbee.test", "127.0.0.1 pim.giftbee.test"],
            content,
        )
        try:
            missing = manager.get_missing_entries()
            assert missing == []
        finally:
            hosts_file.unlink(missing_ok=True)


class TestHostManagerEnsureHosts:
    @pytest.mark.asyncio
    async def test_no_action_when_all_present(self) -> None:
        content = "127.0.0.1 wallet.giftbee.test\n"
        manager, hosts_file = _make_manager(
            ["127.0.0.1 wallet.giftbee.test"],
            content,
        )
        try:
            result = await manager.ensure_hosts()
            assert result is True
        finally:
            hosts_file.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_adds_missing_entries(self) -> None:
        manager, hosts_file = _make_manager(
            ["127.0.0.1 wallet.giftbee.test"],
            "127.0.0.1 localhost\n",
        )
        try:
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.communicate.return_value = (b"", b"")
                mock_proc.returncode = 0
                mock_exec.return_value = mock_proc

                result = await manager.ensure_hosts()
            assert result is True
        finally:
            hosts_file.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_returns_false_on_sudo_failure(self) -> None:
        manager, hosts_file = _make_manager(
            ["127.0.0.1 wallet.giftbee.test"],
            "127.0.0.1 localhost\n",
        )
        try:
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.communicate.return_value = (b"", b"permission denied")
                mock_proc.returncode = 1
                mock_exec.return_value = mock_proc

                result = await manager.ensure_hosts()
            assert result is False
        finally:
            hosts_file.unlink(missing_ok=True)


class TestHostManagerInstructions:
    def test_instructions_when_missing(self) -> None:
        manager, hosts_file = _make_manager(
            ["127.0.0.1 wallet.giftbee.test"],
            "127.0.0.1 localhost\n",
        )
        try:
            instructions = manager.get_hosts_instructions()
            assert "wallet.giftbee.test" in instructions
        finally:
            hosts_file.unlink(missing_ok=True)

    def test_instructions_when_all_present(self) -> None:
        manager, hosts_file = _make_manager(
            ["127.0.0.1 wallet.giftbee.test"],
            "127.0.0.1 wallet.giftbee.test\n",
        )
        try:
            instructions = manager.get_hosts_instructions()
            assert "already configured" in instructions
        finally:
            hosts_file.unlink(missing_ok=True)
