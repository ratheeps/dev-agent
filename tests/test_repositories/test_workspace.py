"""Tests for WorkspaceManager."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.repositories.workspace import WorkspaceManager, _run_git


class TestRunGit:
    @pytest.mark.asyncio
    async def test_successful_command(self, tmp_path: Path) -> None:
        # Just test that _run_git wraps subprocess correctly
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b"main\n", b"")
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            rc, stdout, stderr = await _run_git(["branch", "--show-current"], tmp_path)
            assert rc == 0
            assert stdout == "main"

    @pytest.mark.asyncio
    async def test_failed_command_raises(self, tmp_path: Path) -> None:
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b"", b"fatal: not a git repository")
            mock_proc.returncode = 128
            mock_exec.return_value = mock_proc

            with pytest.raises(RuntimeError, match="fatal: not a git repository"):
                await _run_git(["status"], tmp_path)

    @pytest.mark.asyncio
    async def test_failed_command_no_raise_when_check_false(self, tmp_path: Path) -> None:
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b"", b"error")
            mock_proc.returncode = 1
            mock_exec.return_value = mock_proc

            rc, _, _ = await _run_git(["status"], tmp_path, check=False)
            assert rc == 1


class TestWorkspaceManagerEnsureRepo:
    @pytest.mark.asyncio
    async def test_ensure_repo_existing(self, tmp_path: Path) -> None:
        repo_cfg = MagicMock()
        repo_cfg.local_path = tmp_path
        (tmp_path / ".git").mkdir()

        with patch("src.repositories.workspace._run_git") as mock_git:
            mock_git.return_value = (0, str(tmp_path), "")
            manager = WorkspaceManager()
            path = await manager.ensure_repo(repo_cfg)
        assert path == tmp_path

    @pytest.mark.asyncio
    async def test_ensure_repo_missing_raises(self, tmp_path: Path) -> None:
        repo_cfg = MagicMock()
        repo_cfg.local_path = tmp_path / "nonexistent"

        manager = WorkspaceManager()
        with pytest.raises(RuntimeError, match="not found"):
            await manager.ensure_repo(repo_cfg)


class TestWorkspaceManagerBranching:
    @pytest.mark.asyncio
    async def test_create_branch_new(self, tmp_path: Path) -> None:
        repo_cfg = MagicMock()
        repo_cfg.local_path = tmp_path
        repo_cfg.base_branch = "dev"

        call_args: list[list[str]] = []

        async def fake_git(args: list[str], cwd: Path, **kwargs: object) -> tuple[int, str, str]:
            call_args.append(args)
            if args[0] == "branch" and "--list" in args:
                return 0, "", ""  # branch doesn't exist
            return 0, "", ""

        with patch("src.repositories.workspace._run_git", side_effect=fake_git):
            manager = WorkspaceManager()
            branch = await manager.create_branch(repo_cfg, "GIFT-1234")

        assert branch == "dev-ai/GIFT-1234"
        # Should have called checkout -b
        checkout_calls = [a for a in call_args if "checkout" in a]
        assert any("-b" in c for c in checkout_calls)

    @pytest.mark.asyncio
    async def test_create_branch_existing(self, tmp_path: Path) -> None:
        repo_cfg = MagicMock()
        repo_cfg.local_path = tmp_path
        repo_cfg.base_branch = "dev"

        async def fake_git(args: list[str], cwd: Path, **kwargs: object) -> tuple[int, str, str]:
            if args[0] == "branch" and "--list" in args:
                return 0, "  dev-ai/GIFT-1234", ""
            return 0, "", ""

        with patch("src.repositories.workspace._run_git", side_effect=fake_git):
            manager = WorkspaceManager()
            branch = await manager.create_branch(repo_cfg, "GIFT-1234")

        assert branch == "dev-ai/GIFT-1234"


class TestWorkspaceManagerCommit:
    @pytest.mark.asyncio
    async def test_commit_with_changes(self, tmp_path: Path) -> None:
        async def fake_git(args: list[str], cwd: Path, **kwargs: object) -> tuple[int, str, str]:
            if "diff" in args and "--cached" in args:
                return 1, "", ""  # There are staged changes (rc != 0 means changes exist)
            if args[0:2] == ["rev-parse", "HEAD"]:
                return 0, "abc123", ""
            return 0, "", ""

        with patch("src.repositories.workspace._run_git", side_effect=fake_git):
            manager = WorkspaceManager()
            sha = await manager.commit(tmp_path, "feat: test commit")

        assert sha == "abc123"

    @pytest.mark.asyncio
    async def test_commit_nothing_to_commit(self, tmp_path: Path) -> None:
        async def fake_git(args: list[str], cwd: Path, **kwargs: object) -> tuple[int, str, str]:
            if "diff" in args and "--cached" in args:
                return 0, "", ""  # No staged changes
            if args[0:2] == ["rev-parse", "HEAD"]:
                return 0, "abc123", ""
            return 0, "", ""

        with patch("src.repositories.workspace._run_git", side_effect=fake_git):
            manager = WorkspaceManager()
            sha = await manager.commit(tmp_path, "empty commit")

        assert sha == "abc123"


class TestWorkspaceManagerStatus:
    @pytest.mark.asyncio
    async def test_get_status_parses_output(self, tmp_path: Path) -> None:
        status_output = " M src/foo.py\nA  src/new.py\n?? untracked.txt"

        async def fake_git(args: list[str], cwd: Path, **kwargs: object) -> tuple[int, str, str]:
            return 0, status_output, ""

        with patch("src.repositories.workspace._run_git", side_effect=fake_git):
            manager = WorkspaceManager()
            status = await manager.get_status(tmp_path)

        assert "src/foo.py" in status["modified"]
        assert "src/new.py" in status["added"]
        assert "untracked.txt" in status["untracked"]
