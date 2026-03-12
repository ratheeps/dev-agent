"""/etc/hosts manager for GiftBee development domains.

Ensures *.giftbee.test domains resolve to 127.0.0.1 on the host machine
so Playwright browser (running outside Docker) can reach the nginx proxy.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from src.schemas.repository import InfraConfig

logger = logging.getLogger(__name__)

_HOSTS_FILE = Path("/etc/hosts")
_MARKER = "# dev-ai: giftbee local domains"


class HostManager:
    """Manages /etc/hosts entries for *.giftbee.test domains.

    Parameters
    ----------
    infra_config:
        InfraConfig with ``host_entries`` list from repositories.yaml.
    hosts_file:
        Override for the hosts file path (default: /etc/hosts). Useful in tests.
    """

    def __init__(
        self,
        infra_config: InfraConfig,
        hosts_file: Path = _HOSTS_FILE,
    ) -> None:
        self._infra = infra_config
        self._hosts_file = hosts_file

    def parse_hosts_file(self) -> list[str]:
        """Read and return all lines from the hosts file."""
        try:
            return self._hosts_file.read_text().splitlines()
        except FileNotFoundError:
            return []

    def check_hosts(self) -> dict[str, bool]:
        """Check which required host entries exist.

        Returns a dict mapping each required domain to True/False.
        """
        lines = self.parse_hosts_file()
        content = "\n".join(lines)

        result: dict[str, bool] = {}
        for entry in self._infra.host_entries:
            # Extract domain from "127.0.0.1 domain.name"
            parts = entry.strip().split()
            if len(parts) >= 2:
                domain = parts[1]
                # Check if domain appears in any non-comment line
                pattern = re.compile(
                    r"^(?!#)\S+\s+.*\b" + re.escape(domain) + r"\b",
                    re.MULTILINE,
                )
                result[domain] = bool(pattern.search(content))
        return result

    def get_missing_entries(self) -> list[str]:
        """Return host entries that are not yet in /etc/hosts."""
        status = self.check_hosts()
        missing = []
        for entry in self._infra.host_entries:
            parts = entry.strip().split()
            if len(parts) >= 2:
                domain = parts[1]
                if not status.get(domain, False):
                    missing.append(entry)
        return missing

    async def ensure_hosts(self) -> bool:
        """Add missing /etc/hosts entries using sudo.

        Returns True if all entries are present (or were added successfully).
        Returns False if sudo failed (user must add manually).
        """
        missing = self.get_missing_entries()
        if not missing:
            logger.info("All giftbee.test hosts already in /etc/hosts")
            return True

        logger.info("Adding %d missing host entries: %s", len(missing), missing)
        lines_to_add = "\n".join(["", _MARKER] + missing + [""])
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "tee", "-a", str(self._hosts_file),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate(input=lines_to_add.encode())
            rc = proc.returncode or 0
            if rc == 0:
                logger.info("Successfully added host entries to %s", self._hosts_file)
                return True
            else:
                logger.warning(
                    "sudo tee failed (rc=%d). Please add these lines to %s manually:\n%s",
                    rc,
                    self._hosts_file,
                    lines_to_add,
                )
                return False
        except Exception as e:
            logger.warning(
                "Could not update %s (%s). Please add these lines manually:\n%s",
                self._hosts_file,
                e,
                lines_to_add,
            )
            return False

    def get_hosts_instructions(self) -> str:
        """Return human-readable instructions for manually adding entries."""
        missing = self.get_missing_entries()
        if not missing:
            return "All giftbee.test hosts are already configured."
        lines = "\n".join(missing)
        return (
            f"Please add the following lines to {self._hosts_file}:\n\n"
            f"{_MARKER}\n{lines}\n\n"
            f"Run: echo '{lines}' | sudo tee -a {self._hosts_file}"
        )
