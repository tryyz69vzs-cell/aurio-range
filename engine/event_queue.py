"""Monotonic event recorder used as the simulation clock."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RecordedEvent:
    step_index: int
    event_type: str
    message_id: int | None
    account_id: int | None
    payload: dict[str, Any]


class EventQueue:
    def __init__(self, connection: sqlite3.Connection, match_id: int):
        self._connection = connection
        self.match_id = match_id
        self._step = -1
        self._started = time.perf_counter()

    @property
    def current_step(self) -> int:
        return self._step

    def record(
        self,
        event_type: str,
        message_id: int | None = None,
        account_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RecordedEvent:
        self._step += 1
        safe_payload = payload or {}
        wall_ms = int((time.perf_counter() - self._started) * 1000)
        self._connection.execute(
            """INSERT INTO events(
                 match_id, step_index, event_type, message_id,
                 account_id, payload_json, wall_ms
               ) VALUES(?,?,?,?,?,?,?)""",
            (
                self.match_id,
                self._step,
                event_type,
                message_id,
                account_id,
                json.dumps(safe_payload, ensure_ascii=False, sort_keys=True),
                wall_ms,
            ),
        )
        return RecordedEvent(
            self._step, event_type, message_id, account_id, safe_payload
        )
