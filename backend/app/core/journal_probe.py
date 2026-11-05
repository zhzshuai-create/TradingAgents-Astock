"""Trade-journal probe for ``GET /api/v1/meta/options`` (api-v1.md 1.8).

Availability is a TCP connect to the journal port followed by a Streamlit
identity check (``/_stcore/health`` must answer ``ok``), both bounded by 300ms.
The probe never starts the journal: a missing install is reported as
``not_installed`` and a cold port as ``not_running``, so the page can offer the
manual start action instead of spawning a process behind the user's back.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

DEFAULT_ENTRY_URL = "http://127.0.0.1:8502"
ENTRY_URL_ENV = "TA_JOURNAL_URL"
INSTALL_DIR_ENV = "TA_JOURNAL_DIR"
HEALTH_PATH = "/_stcore/health"
PROBE_TIMEOUT = 0.3
JOURNAL_REASONS = ("not_running", "not_installed", "probe_failed")


@dataclass(frozen=True)
class JournalStatus:
    available: bool
    entry_url: str
    reason: str | None

    def as_payload(self) -> dict[str, object]:
        return {
            "available": self.available,
            "entry_url": self.entry_url,
            "reason": self.reason,
        }


def _tcp_connect(host: str, port: int, timeout: float) -> None:
    with socket.create_connection((host, port), timeout=timeout):
        pass


def _http_health(url: str, timeout: float) -> str:
    with urlopen(url, timeout=timeout) as response:
        if response.status != 200:
            raise OSError(f"health status {response.status}")
        return response.read(64).decode("utf-8", "replace")


class JournalProbe:
    def __init__(
        self,
        *,
        entry_url: str | None = None,
        install_dir: Path | str | None = None,
        timeout: float = PROBE_TIMEOUT,
        connect: Callable[[str, int, float], None] | None = None,
        health: Callable[[str, float], str] | None = None,
    ) -> None:
        self.entry_url = entry_url or os.environ.get(ENTRY_URL_ENV, DEFAULT_ENTRY_URL)
        if install_dir is None:
            configured = os.environ.get(INSTALL_DIR_ENV)
            install_dir = (
                Path(configured).expanduser()
                if configured
                else Path.home() / "trade-journal"
            )
        self.install_dir = Path(install_dir)
        self._timeout = timeout
        self._connect = connect or _tcp_connect
        self._health = health or _http_health

    @property
    def installed(self) -> bool:
        return (self.install_dir / "run.bat").is_file() or (
            self.install_dir / "app.py"
        ).is_file()

    def probe(self) -> JournalStatus:
        try:
            return self._probe()
        except Exception:
            # A probe is advisory: it must never fail the meta response.
            return JournalStatus(False, self.entry_url, "probe_failed")

    def _probe(self) -> JournalStatus:
        split = urlsplit(self.entry_url)
        host = split.hostname
        port = split.port or (443 if split.scheme == "https" else 80)
        if not host:
            return JournalStatus(False, self.entry_url, "probe_failed")

        try:
            self._connect(host, port, self._timeout)
        except (ConnectionRefusedError, TimeoutError):
            # A closed loopback port either refuses or black-holes the SYN;
            # both mean nothing is accepting, i.e. the journal is not running.
            return JournalStatus(
                False, self.entry_url, self._down_reason("not_running")
            )
        except OSError:
            return JournalStatus(
                False, self.entry_url, self._down_reason("probe_failed")
            )

        try:
            body = self._health(self._health_url(), self._timeout)
        except Exception:
            return JournalStatus(False, self.entry_url, "probe_failed")
        if body.strip() == "ok":
            return JournalStatus(True, self.entry_url, None)
        return JournalStatus(False, self.entry_url, "probe_failed")

    def _down_reason(self, reason: str) -> str:
        return "not_installed" if not self.installed else reason

    def _health_url(self) -> str:
        return self.entry_url.rstrip("/") + HEALTH_PATH


def load_journal_probe() -> JournalProbe:
    return JournalProbe()
