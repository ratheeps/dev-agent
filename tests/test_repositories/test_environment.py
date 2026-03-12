"""Tests for DevEnvironmentManager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.repositories.environment import DevEnvironmentManager, _run_cmd


class TestRunCmd:
    @pytest.mark.asyncio
    async def test_successful_command(self, tmp_path: Path) -> None:
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b"PONG\n", b"")
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            rc, stdout, _ = await _run_cmd(["redis-cli", "ping"], tmp_path)
            assert rc == 0
            assert stdout == "PONG"

    @pytest.mark.asyncio
    async def test_failed_command_raises_by_default(self, tmp_path: Path) -> None:
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b"", b"connection refused")
            mock_proc.returncode = 1
            mock_exec.return_value = mock_proc

            with pytest.raises(RuntimeError):
                await _run_cmd(["redis-cli", "ping"], tmp_path)

    @pytest.mark.asyncio
    async def test_failed_command_no_raise_when_check_false(self, tmp_path: Path) -> None:
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b"", b"error")
            mock_proc.returncode = 1
            mock_exec.return_value = mock_proc

            rc, _, _ = await _run_cmd(["cmd"], tmp_path, check=False)
            assert rc == 1


def _make_manager() -> DevEnvironmentManager:
    infra = MagicMock()
    infra.local_infra_path = Path("/tmp/local-infra")
    infra.task_binary = "task"
    mysql = MagicMock()
    mysql.name = "mysql"
    mysql.health_check = "docker compose exec mysql mysqladmin ping"
    redis = MagicMock()
    redis.name = "redis"
    redis.health_check = None
    registry = MagicMock()
    registry.get_transitive_deps.return_value = []
    return DevEnvironmentManager(
        infra_config=infra,
        shared_services=[mysql, redis],
        registry=registry,
    )


class TestDevEnvironmentManagerTests:
    @pytest.mark.asyncio
    async def test_run_tests_success(self) -> None:
        manager = _make_manager()
        repo = MagicMock()
        repo.name = "wallet-service"
        repo.test_cmd = "docker compose exec wallet php artisan test"

        with patch("src.repositories.environment._run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "OK: 42 passed", "")
            result = await manager.run_tests(repo)

        assert result["success"] is True
        assert result["returncode"] == 0

    @pytest.mark.asyncio
    async def test_run_tests_failure(self) -> None:
        manager = _make_manager()
        repo = MagicMock()
        repo.name = "wallet-service"
        repo.test_cmd = "docker compose exec wallet php artisan test"

        with patch("src.repositories.environment._run_cmd") as mock_cmd:
            mock_cmd.return_value = (1, "", "FAILED 2 tests")
            result = await manager.run_tests(repo)

        assert result["success"] is False
        assert result["returncode"] == 1

    @pytest.mark.asyncio
    async def test_run_tests_no_cmd(self) -> None:
        manager = _make_manager()
        repo = MagicMock()
        repo.name = "wallet-service"
        repo.test_cmd = None
        result = await manager.run_tests(repo)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_run_e2e_tests_success(self) -> None:
        manager = _make_manager()
        repo = MagicMock()
        repo.name = "store-front"
        repo.e2e_test_cmd = "docker compose exec store-front npm run test:e2e"

        with patch("src.repositories.environment._run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "25 passed", "")
            result = await manager.run_e2e_tests(repo)

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_run_e2e_tests_with_grep(self) -> None:
        manager = _make_manager()
        repo = MagicMock()
        repo.name = "store-front"
        repo.e2e_test_cmd = "docker compose exec store-front npm run test:e2e"

        captured_args: list[list[str]] = []

        async def mock_cmd(args: list[str], **kwargs: object) -> tuple[int, str, str]:
            captured_args.append(args)
            return (0, "1 passed", "")

        with patch("src.repositories.environment._run_cmd", side_effect=mock_cmd):
            await manager.run_e2e_tests(repo, grep="balance")

        # Check grep was included in command
        full_cmd = " ".join(captured_args[0])
        assert "grep" in full_cmd or "balance" in full_cmd

    @pytest.mark.asyncio
    async def test_run_e2e_tests_no_cmd(self) -> None:
        manager = _make_manager()
        repo = MagicMock()
        repo.name = "store-front"
        repo.e2e_test_cmd = None
        result = await manager.run_e2e_tests(repo)
        assert result["success"] is True


class TestDevEnvironmentManagerHealth:
    @pytest.mark.asyncio
    async def test_check_health_pass(self) -> None:
        manager = _make_manager()
        svc = MagicMock()
        svc.health_check = "docker compose exec mysql mysqladmin ping"

        with patch("src.repositories.environment._run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "mysqld is alive", "")
            result = await manager.check_health(svc)

        assert result is True

    @pytest.mark.asyncio
    async def test_check_health_fail(self) -> None:
        manager = _make_manager()
        svc = MagicMock()
        svc.health_check = "docker compose exec mysql mysqladmin ping"

        with patch("src.repositories.environment._run_cmd") as mock_cmd:
            mock_cmd.return_value = (1, "", "connection refused")
            result = await manager.check_health(svc)

        assert result is False

    @pytest.mark.asyncio
    async def test_check_health_no_check(self) -> None:
        manager = _make_manager()
        svc = MagicMock()
        svc.health_check = None
        result = await manager.check_health(svc)
        assert result is True
