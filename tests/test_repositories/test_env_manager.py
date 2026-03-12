"""Tests for EnvFileManager."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.repositories.env_manager import EnvFileManager, _read_env, _write_env


class TestReadEnv:
    def test_reads_basic_vars(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("DB_HOST=mysql\nDB_PORT=3306\n")
        result = _read_env(env_file)
        assert result["DB_HOST"] == "mysql"
        assert result["DB_PORT"] == "3306"

    def test_skips_comments_and_blank_lines(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("# Comment\n\nDB_HOST=mysql\n")
        result = _read_env(env_file)
        assert "# Comment" not in result
        assert result["DB_HOST"] == "mysql"

    def test_strips_quotes(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text('APP_URL="https://wallet.giftbee.test"\n')
        result = _read_env(env_file)
        assert result["APP_URL"] == "https://wallet.giftbee.test"

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = _read_env(tmp_path / ".nonexistent")
        assert result == {}


class TestWriteEnv:
    def test_updates_existing_key(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("DB_HOST=localhost\nDB_PORT=3306\n")
        _write_env(env_file, {"DB_HOST": "mysql"})
        result = _read_env(env_file)
        assert result["DB_HOST"] == "mysql"
        assert result["DB_PORT"] == "3306"

    def test_adds_new_key(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("DB_HOST=mysql\n")
        _write_env(env_file, {"REDIS_HOST": "redis"})
        result = _read_env(env_file)
        assert result["REDIS_HOST"] == "redis"
        assert result["DB_HOST"] == "mysql"

    def test_creates_file_if_missing(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        _write_env(env_file, {"NEW_VAR": "value"})
        result = _read_env(env_file)
        assert result["NEW_VAR"] == "value"


class TestEnvFileManagerEnsureEnv:
    def _make_manager(self, infra_path: Path) -> EnvFileManager:
        infra = MagicMock()
        infra.local_infra_path = infra_path
        return EnvFileManager(infra_config=infra)

    def test_copies_template_when_env_missing(self, tmp_path: Path) -> None:
        repo_path = tmp_path / "wallet-service"
        repo_path.mkdir()
        template = repo_path / ".env.example"
        template.write_text("DB_HOST=mysql\nDB_DATABASE=wallet\n")

        repo = MagicMock()
        repo.local_path = repo_path
        repo.env_template = ".env.example"
        repo.required_env_vars = ["DB_HOST", "DB_DATABASE"]

        manager = self._make_manager(tmp_path)
        issues = manager.ensure_env(repo)

        assert (repo_path / ".env").exists()
        assert issues == []

    def test_validates_missing_required_var(self, tmp_path: Path) -> None:
        repo_path = tmp_path / "wallet-service"
        repo_path.mkdir()
        env_file = repo_path / ".env"
        env_file.write_text("DB_HOST=mysql\n")  # DB_DATABASE missing

        repo = MagicMock()
        repo.local_path = repo_path
        repo.env_template = ".env.example"
        repo.required_env_vars = ["DB_HOST", "DB_DATABASE"]
        repo.name = "wallet-service"

        manager = self._make_manager(tmp_path)
        issues = manager.validate_env(repo)

        assert any("DB_DATABASE" in i for i in issues)

    def test_no_issues_when_all_vars_set(self, tmp_path: Path) -> None:
        repo_path = tmp_path / "wallet-service"
        repo_path.mkdir()
        env_file = repo_path / ".env"
        env_file.write_text("DB_HOST=mysql\nDB_DATABASE=wallet\n")

        repo = MagicMock()
        repo.local_path = repo_path
        repo.env_template = ".env.example"
        repo.required_env_vars = ["DB_HOST", "DB_DATABASE"]
        repo.name = "wallet-service"

        manager = self._make_manager(tmp_path)
        issues = manager.validate_env(repo)

        assert issues == []


class TestEnvFileManagerTestEnv:
    def _make_manager(self, infra_path: Path) -> EnvFileManager:
        infra = MagicMock()
        infra.local_infra_path = infra_path
        return EnvFileManager(infra_config=infra)

    def test_copies_test_template(self, tmp_path: Path) -> None:
        repo_path = tmp_path / "store-front"
        repo_path.mkdir()
        template = repo_path / ".env.test.example"
        template.write_text("TEST_BASE_URL=https://account-dev.giftbee.com\n")

        repo = MagicMock()
        repo.local_path = repo_path
        repo.env_test_template = ".env.test.example"
        repo.dev_url = "https://myaccount.giftbee.test"

        manager = self._make_manager(tmp_path)
        issues = manager.ensure_test_env(repo)

        assert issues == []
        test_env = repo_path / ".env.test"
        assert test_env.exists()
        result = _read_env(test_env)
        assert result["TEST_BASE_URL"] == "https://myaccount.giftbee.test"

    def test_no_op_when_no_test_template(self, tmp_path: Path) -> None:
        repo = MagicMock()
        repo.env_test_template = None

        manager = self._make_manager(tmp_path)
        issues = manager.ensure_test_env(repo)
        assert issues == []


class TestEnvFileManagerInfraEnv:
    def _make_manager(self, infra_path: Path) -> EnvFileManager:
        infra = MagicMock()
        infra.local_infra_path = infra_path
        return EnvFileManager(infra_config=infra)

    def test_updates_mismatched_paths(self, tmp_path: Path) -> None:
        infra_path = tmp_path / "local-infra"
        infra_path.mkdir()
        env_file = infra_path / ".env"
        env_file.write_text(
            "WALLET_SERVICE_DIR=/old/path/wallet-service\n"
            "STORE_FRONT_DIR=/old/path/store-front\n"
            "ADMIN_PORTAL=/old/path/admin-portal\n"
            "PIM_DIR=/old/path/pim\n"
        )

        repos = {
            "wallet-service": MagicMock(local_path=Path("/new/wallet-service")),
            "store-front": MagicMock(local_path=Path("/new/store-front")),
            "admin-portal": MagicMock(local_path=Path("/new/admin-portal")),
            "pim": MagicMock(local_path=Path("/new/pim")),
        }

        infra = MagicMock()
        infra.local_infra_path = infra_path
        manager = EnvFileManager(infra_config=infra)
        warnings = manager.ensure_infra_env(repos)

        assert len(warnings) > 0
        result = _read_env(env_file)
        assert result["WALLET_SERVICE_DIR"] == "/new/wallet-service"

    def test_no_changes_when_paths_correct(self, tmp_path: Path) -> None:
        infra_path = tmp_path / "local-infra"
        infra_path.mkdir()
        env_file = infra_path / ".env"
        env_file.write_text(
            "WALLET_SERVICE_DIR=/correct/wallet-service\n"
            "STORE_FRONT_DIR=/correct/store-front\n"
            "ADMIN_PORTAL=/correct/admin-portal\n"
            "PIM_DIR=/correct/pim\n"
        )

        repos = {
            "wallet-service": MagicMock(local_path=Path("/correct/wallet-service")),
            "store-front": MagicMock(local_path=Path("/correct/store-front")),
            "admin-portal": MagicMock(local_path=Path("/correct/admin-portal")),
            "pim": MagicMock(local_path=Path("/correct/pim")),
        }

        infra = MagicMock()
        infra.local_infra_path = infra_path
        manager = EnvFileManager(infra_config=infra)
        warnings = manager.ensure_infra_env(repos)

        assert warnings == []
