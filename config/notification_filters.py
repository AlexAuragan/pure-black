from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from gi.repository import Gio
from loguru import logger

if TYPE_CHECKING:
    from services.notifications import Notification

CONFIG_PATH = Path(__file__).parent / "notifications.toml"

Action = Literal["drop", "transient"]


class _Rule:
    __slots__ = ("match_app", "match_summary", "match_body", "action")

    def __init__(self, raw: dict):
        self.match_app: str = (raw.get("match_app") or "").lower()
        self.match_summary: str = (raw.get("match_summary") or "").lower()
        self.match_body: str = (raw.get("match_body") or "").lower()
        self.action: Action = raw.get("action", "drop")

    def matches(self, notif: Notification) -> bool:
        if self.match_app and self.match_app not in notif["app_name"].lower():
            return False
        if self.match_summary and self.match_summary not in notif["summary"].lower():
            return False
        if self.match_body and self.match_body not in notif["body"].lower():
            return False
        return True


class NotificationFilters:
    def __init__(self):
        self._rules: list[_Rule] = []
        self._monitor: Gio.FileMonitor | None = None
        self._load()
        self._watch()

    def apply(self, notif: Notification) -> Action | None:
        """Return the action for this notification, or None if no rule matches."""
        for rule in self._rules:
            if rule.matches(notif):
                return rule.action
        return None

    def _load(self) -> None:
        if not CONFIG_PATH.exists():
            self._rules = []
            return
        try:
            with open(CONFIG_PATH, "rb") as f:
                data = tomllib.load(f)
            self._rules = [_Rule(r) for r in data.get("rules", [])]
            logger.info(f"[NotificationFilters] loaded {len(self._rules)} rule(s)")
        except Exception as e:
            logger.warning(f"[NotificationFilters] failed to load config: {e}")

    def _watch(self) -> None:
        try:
            gfile = Gio.File.new_for_path(str(CONFIG_PATH))
            self._monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self._monitor.connect("changed", self._on_file_changed)
        except Exception as e:
            logger.warning(f"[NotificationFilters] could not watch config file: {e}")

    def _on_file_changed(
        self, _monitor: Gio.FileMonitor, _file: Gio.File, _other: Gio.File | None, event: Gio.FileMonitorEvent
    ) -> None:
        if event in (
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
            Gio.FileMonitorEvent.CREATED,
        ):
            logger.info("[NotificationFilters] config changed, reloading…")
            self._load()
