"""Per-match in-memory schema plus strictly separated Blue and Judge repositories."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]

SCHEMA_SQL = """
CREATE TABLE matches(
  id INTEGER PRIMARY KEY,
  seed TEXT NOT NULL,
  difficulty_mix TEXT NOT NULL,
  strictness TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  status TEXT NOT NULL
);

CREATE TABLE accounts(
  id INTEGER PRIMARY KEY,
  match_id INTEGER NOT NULL,
  username TEXT NOT NULL,
  email TEXT NOT NULL,
  profile TEXT NOT NULL CHECK(profile IN ('cautious','average','careless')),
  scenario_key TEXT NOT NULL,
  mfa_enabled INTEGER NOT NULL CHECK(mfa_enabled IN (0,1)),
  status TEXT NOT NULL,
  session_state TEXT NOT NULL
);

CREATE TABLE official_events(
  id INTEGER PRIMARY KEY,
  match_id INTEGER NOT NULL,
  account_id INTEGER NOT NULL,
  event_ref TEXT NOT NULL,
  event_type TEXT NOT NULL,
  description TEXT NOT NULL,
  created_step INTEGER NOT NULL
);

CREATE TABLE messages(
  id INTEGER PRIMARY KEY,
  match_id INTEGER NOT NULL,
  account_id INTEGER NOT NULL,
  channel TEXT NOT NULL,
  display_sender_name TEXT NOT NULL,
  auth_sender_address TEXT NOT NULL,
  sender_auth_result TEXT NOT NULL,
  signature_token TEXT,
  claimed_event_type TEXT NOT NULL,
  claimed_event_ref TEXT,
  link_destination TEXT NOT NULL,
  ingress_channel TEXT NOT NULL,
  subject_text TEXT NOT NULL,
  body_text TEXT NOT NULL,
  rendered_html TEXT NOT NULL,
  created_step INTEGER NOT NULL,
  delivery_status TEXT,
  post_flag TEXT
);

CREATE TABLE phish_pages(
  id INTEGER PRIMARY KEY,
  match_id INTEGER NOT NULL,
  message_id INTEGER NOT NULL,
  url_path TEXT NOT NULL,
  html TEXT NOT NULL,
  created_step INTEGER NOT NULL,
  blocked INTEGER NOT NULL DEFAULT 0 CHECK(blocked IN (0,1)),
  blocked_step INTEGER
);

CREATE TABLE events(
  id INTEGER PRIMARY KEY,
  match_id INTEGER NOT NULL,
  step_index INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  message_id INTEGER,
  account_id INTEGER,
  payload_json TEXT NOT NULL,
  wall_ms INTEGER NOT NULL,
  UNIQUE(match_id, step_index)
);

CREATE TABLE blue_assessments(
  id INTEGER PRIMARY KEY,
  message_id INTEGER NOT NULL UNIQUE,
  risk_total INTEGER NOT NULL,
  band TEXT NOT NULL,
  pre_delivery_action TEXT NOT NULL,
  post_action_response TEXT,
  signals_json TEXT NOT NULL,
  assessment_step INTEGER NOT NULL,
  response_step INTEGER
);

CREATE TABLE user_actions(
  id INTEGER PRIMARY KEY,
  match_id INTEGER NOT NULL,
  account_id INTEGER NOT NULL,
  message_id INTEGER NOT NULL,
  profile TEXT NOT NULL,
  action TEXT NOT NULL,
  from_state TEXT NOT NULL,
  to_state TEXT NOT NULL,
  step_index INTEGER NOT NULL
);

CREATE TABLE capture_events(
  id INTEGER PRIMARY KEY,
  match_id INTEGER NOT NULL,
  message_id INTEGER NOT NULL,
  account_id INTEGER NOT NULL,
  submission_target TEXT NOT NULL
    CHECK(submission_target IN ('official_owned','synthetic_unowned','internal_capture')),
  account_status_at_submit TEXT NOT NULL,
  session_state_at_submit TEXT NOT NULL,
  attempted_username INTEGER NOT NULL CHECK(attempted_username IN (0,1)),
  attempted_password INTEGER NOT NULL CHECK(attempted_password IN (0,1)),
  valid_synthetic_credentials_submitted INTEGER NOT NULL
    CHECK(valid_synthetic_credentials_submitted IN (0,1)),
  submitted_to_phish INTEGER NOT NULL CHECK(submitted_to_phish IN (0,1)),
  credential_exposure INTEGER NOT NULL CHECK(credential_exposure IN (0,1)),
  takeover_success INTEGER NOT NULL CHECK(takeover_success IN (0,1)),
  step_index INTEGER NOT NULL
);

CREATE TABLE scenario_ground_truth(
  message_id INTEGER PRIMARY KEY,
  match_id INTEGER NOT NULL,
  true_origin TEXT NOT NULL,
  true_difficulty TEXT NOT NULL,
  generator TEXT NOT NULL,
  red_tactic_id TEXT,
  scenario_goal TEXT NOT NULL,
  is_forged INTEGER NOT NULL CHECK(is_forged IN (0,1)),
  expected_classification TEXT NOT NULL
);

CREATE TABLE judge_evaluations(
  id INTEGER PRIMARY KEY,
  message_id INTEGER NOT NULL UNIQUE,
  blue_prediction TEXT NOT NULL,
  ground_truth TEXT NOT NULL,
  correct INTEGER NOT NULL,
  false_positive INTEGER NOT NULL,
  false_negative INTEGER NOT NULL,
  friction INTEGER NOT NULL,
  warning_escape INTEGER NOT NULL,
  user_harm_click INTEGER NOT NULL,
  user_harm_submit INTEGER NOT NULL,
  official_submission INTEGER NOT NULL,
  forged_submission INTEGER NOT NULL,
  credential_exposure INTEGER NOT NULL,
  takeover_success INTEGER NOT NULL,
  exposure_prevented_by_prior_lock INTEGER NOT NULL,
  containment_success INTEGER NOT NULL,
  overreaction INTEGER NOT NULL,
  user_saved INTEGER NOT NULL,
  detection_latency_steps INTEGER,
  containment_latency_steps INTEGER
);

CREATE TABLE match_scores(
  match_id INTEGER PRIMARY KEY,
  red_score REAL NOT NULL,
  blue_score REAL NOT NULL,
  n_official INTEGER NOT NULL,
  n_forged INTEGER NOT NULL,
  false_positive INTEGER NOT NULL,
  false_negative INTEGER NOT NULL,
  friction INTEGER NOT NULL,
  warning_escape INTEGER NOT NULL,
  harm_click INTEGER NOT NULL,
  harm_submit INTEGER NOT NULL,
  official_submission INTEGER NOT NULL,
  forged_submission INTEGER NOT NULL,
  credential_exposure INTEGER NOT NULL,
  takeover_success INTEGER NOT NULL,
  exposure_prevented_by_prior_lock INTEGER NOT NULL,
  containment_success INTEGER NOT NULL,
  overreaction INTEGER NOT NULL,
  user_saved INTEGER NOT NULL,
  avg_detection_steps REAL,
  avg_containment_steps REAL,
  detail_json TEXT NOT NULL
);

CREATE TABLE safety_events(
  id INTEGER PRIMARY KEY,
  match_id INTEGER,
  kind TEXT NOT NULL,
  detail TEXT NOT NULL,
  ts TEXT NOT NULL
);

CREATE INDEX idx_events_match_step ON events(match_id, step_index);
CREATE INDEX idx_user_actions_message ON user_actions(message_id, step_index);
CREATE INDEX idx_official_events_lookup ON official_events(account_id, event_ref);
"""


def create_match_database() -> sqlite3.Connection:
    """Create an isolated database. A file path is intentionally unsupported."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA_SQL)
    return connection


def table_columns(connection: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    allowed = {
        "accounts", "official_events", "messages", "phish_pages", "events",
        "blue_assessments", "user_actions", "capture_events",
        "scenario_ground_truth", "judge_evaluations", "matches",
        "match_scores", "safety_events",
    }
    if table not in allowed:
        raise ValueError("알 수 없는 테이블입니다.")
    return list(connection.execute(f"PRAGMA table_info({table})"))


class BlueRepo:
    """Blue-visible telemetry and response-state access only."""

    def __init__(self, connection: sqlite3.Connection, registry: dict[str, Any]):
        self._connection = connection
        self.registry = registry

    def official_event_exists(self, account_id: int, event_ref: str | None) -> bool:
        if not event_ref:
            return False
        row = self._connection.execute(
            "SELECT 1 FROM official_events WHERE account_id=? AND event_ref=? LIMIT 1",
            (account_id, event_ref),
        ).fetchone()
        return row is not None

    def account_snapshot(self, account_id: int) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT id, status, session_state FROM accounts WHERE id=?",
            (account_id,),
        ).fetchone()
        if row is None:
            raise KeyError(account_id)
        return row

    def message_telemetry(self, message_id: int) -> sqlite3.Row:
        row = self._connection.execute(
            """SELECT id, account_id, channel, display_sender_name,
                      auth_sender_address, sender_auth_result, signature_token,
                      claimed_event_type, claimed_event_ref, link_destination,
                      ingress_channel, body_text, created_step
               FROM messages WHERE id=?""",
            (message_id,),
        ).fetchone()
        if row is None:
            raise KeyError(message_id)
        return row

    def save_assessment(
        self,
        message_id: int,
        risk_total: int,
        band: str,
        action: str,
        signals: dict[str, Any],
        assessment_step: int,
    ) -> None:
        self._connection.execute(
            """INSERT INTO blue_assessments(
                 message_id, risk_total, band, pre_delivery_action,
                 signals_json, assessment_step
               ) VALUES(?,?,?,?,?,?)""",
            (
                message_id, risk_total, band, action,
                json.dumps(signals, ensure_ascii=False, sort_keys=True),
                assessment_step,
            ),
        )

    def set_delivery_status(self, message_id: int, status: str) -> None:
        self._connection.execute(
            "UPDATE messages SET delivery_status=? WHERE id=?", (status, message_id)
        )

    def mark_report_handled(self, message_id: int) -> None:
        self._connection.execute(
            "UPDATE messages SET post_flag='reported_handled' WHERE id=?", (message_id,)
        )

    def block_page(self, message_id: int, step_index: int) -> bool:
        cursor = self._connection.execute(
            """UPDATE phish_pages SET blocked=1, blocked_step=?
               WHERE message_id=?""",
            (step_index, message_id),
        )
        return cursor.rowcount > 0

    def protect_account(self, account_id: int, status: str, session_state: str) -> None:
        self._connection.execute(
            "UPDATE accounts SET status=?, session_state=? WHERE id=?",
            (status, session_state, account_id),
        )

    def save_post_response(self, message_id: int, response: str, step_index: int) -> None:
        self._connection.execute(
            """UPDATE blue_assessments
               SET post_action_response=?, response_step=? WHERE message_id=?""",
            (response, step_index, message_id),
        )

    def commit(self) -> None:
        self._connection.commit()


class JudgeRepo:
    """Judge-only whole-match access, including the isolated truth table."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def rows(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return list(self._connection.execute(sql, tuple(params)))

    def row(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        return self._connection.execute(sql, tuple(params)).fetchone()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self._connection.execute(sql, tuple(params))

    def commit(self) -> None:
        self._connection.commit()
