from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date

from bot_app.config import STATE_FILE, Settings


@dataclass
class RuntimeState:
    auto_mode: bool
    interval_days: int
    sends_per_day: int
    random_time_mode: bool
    send_time: str
    images_enabled: bool
    target_chat_ids: list[int]
    schedule_source: str
    scheduled_custom_message: str | None
    last_sent_on: str | None
    scheduled_times_date: str | None
    scheduled_times_today: list[str]
    sent_times_date: str | None
    sent_times_today: list[str]

    @classmethod
    def from_settings(cls, settings: Settings) -> "RuntimeState":
        return cls(
            auto_mode=settings.auto_mode,
            interval_days=settings.interval_days,
            sends_per_day=settings.sends_per_day,
            random_time_mode=settings.random_time_mode,
            send_time=settings.send_time,
            images_enabled=settings.images_enabled,
            target_chat_ids=list(settings.partner_chat_ids),
            schedule_source="api",
            scheduled_custom_message=None,
            last_sent_on=None,
            scheduled_times_date=None,
            scheduled_times_today=[],
            sent_times_date=None,
            sent_times_today=[],
        )

    @property
    def last_sent_date(self) -> date | None:
        return date.fromisoformat(self.last_sent_on) if self.last_sent_on else None

    def mark_sent(self, sent_on: date, send_time: str) -> None:
        self.last_sent_on = sent_on.isoformat()
        if self.sent_times_date != self.last_sent_on:
            self.sent_times_date = self.last_sent_on
            self.sent_times_today = []
        if send_time not in self.sent_times_today:
            self.sent_times_today.append(send_time)


class StateStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def load(self) -> RuntimeState:
        if not STATE_FILE.exists():
            state = RuntimeState.from_settings(self.settings)
            self.save(state)
            return state

        with STATE_FILE.open("r", encoding="utf-8") as file:
            raw_state = json.load(file)

        schedule_source = raw_state.get("schedule_source", "api")
        if schedule_source not in {"api", "custom"}:
            schedule_source = "api"

        return RuntimeState(
            auto_mode=raw_state.get("auto_mode", self.settings.auto_mode),
            interval_days=max(1, int(raw_state.get("interval_days", self.settings.interval_days))),
            sends_per_day=max(1, min(24, int(raw_state.get("sends_per_day", self.settings.sends_per_day)))),
            random_time_mode=bool(raw_state.get("random_time_mode", self.settings.random_time_mode)),
            send_time=raw_state.get("send_time", self.settings.send_time),
            images_enabled=bool(raw_state.get("images_enabled", self.settings.images_enabled)),
            target_chat_ids=_load_runtime_chat_ids(raw_state.get("target_chat_ids"), self.settings),
            schedule_source=schedule_source,
            scheduled_custom_message=raw_state.get("scheduled_custom_message"),
            last_sent_on=raw_state.get("last_sent_on"),
            scheduled_times_date=raw_state.get("scheduled_times_date"),
            scheduled_times_today=list(raw_state.get("scheduled_times_today", [])),
            sent_times_date=raw_state.get("sent_times_date"),
            sent_times_today=list(raw_state.get("sent_times_today", [])),
        )

    def save(self, state: RuntimeState) -> None:
        with STATE_FILE.open("w", encoding="utf-8") as file:
            json.dump(asdict(state), file, indent=2)


def _load_runtime_chat_ids(raw_value: object, settings: Settings) -> list[int]:
    if not isinstance(raw_value, list):
        return list(settings.partner_chat_ids)

    chat_ids: list[int] = []
    for value in raw_value:
        try:
            chat_id = int(value)
        except (TypeError, ValueError):
            continue
        if chat_id not in chat_ids:
            chat_ids.append(chat_id)

    if not chat_ids:
        return list(settings.partner_chat_ids)
    return chat_ids
