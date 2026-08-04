"""Judge-only evaluation of independent metrics and latency-free MVP scores."""

from __future__ import annotations

import json
from statistics import mean
from typing import Any

from engine.db import JudgeRepo
from engine.detection_params import (
    RED_BYPASS,
    RED_CLICK,
    RED_SUBMIT,
    SCORE_COEFFICIENTS,
)


def _event_step(
    repo: JudgeRepo, match_id: int, message_id: int, event_type: str
) -> int | None:
    row = repo.row(
        """SELECT MIN(step_index) AS step_index FROM events
           WHERE match_id=? AND message_id=? AND event_type=?""",
        (match_id, message_id, event_type),
    )
    return None if row is None or row["step_index"] is None else int(row["step_index"])


def _has_action(repo: JudgeRepo, message_id: int, action: str) -> bool:
    return (
        repo.row(
            "SELECT 1 FROM user_actions WHERE message_id=? AND action=? LIMIT 1",
            (message_id, action),
        )
        is not None
    )


def evaluate(repo: JudgeRepo, match_id: int) -> dict[str, Any]:
    rows = repo.rows(
        """SELECT g.*, b.pre_delivery_action, b.post_action_response,
                  b.response_step, m.account_id, m.delivery_status, m.post_flag,
                  a.status AS account_status, a.session_state
           FROM scenario_ground_truth AS g
           JOIN blue_assessments AS b ON b.message_id=g.message_id
           JOIN messages AS m ON m.id=g.message_id
           JOIN accounts AS a ON a.id=m.account_id
           WHERE g.match_id=?
           ORDER BY g.message_id""",
        (match_id,),
    )
    totals = {
        "n_official": 0,
        "n_forged": 0,
        "false_positive": 0,
        "false_negative": 0,
        "friction": 0,
        "warning_escape": 0,
        "harm_click": 0,
        "harm_submit": 0,
        "official_submission": 0,
        "forged_submission": 0,
        "credential_exposure": 0,
        "takeover_success": 0,
        "exposure_prevented_by_prior_lock": 0,
        "containment_success": 0,
        "overreaction": 0,
        "user_saved": 0,
    }
    red_score = 0.0
    blue_score = 0.0
    detection_values: list[int] = []
    containment_values: list[int] = []

    for row in rows:
        message_id = int(row["message_id"])
        forged = bool(row["is_forged"])
        action = row["pre_delivery_action"]
        clicked = _has_action(repo, message_id, "USER_CLICK")
        submitted = _has_action(repo, message_id, "USER_SUBMIT")
        reported = _has_action(repo, message_id, "USER_REPORT")
        false_positive = int(not forged and action == "quarantine")
        friction = int(not forged and action == "warn")
        false_negative = int(forged and action == "allow")
        warning_escape = int(forged and action == "warn" and (clicked or submitted))
        harm_click = int(forged and clicked)
        harm_submit = int(forged and submitted)

        capture_rows = repo.rows(
            """SELECT submission_target, valid_synthetic_credentials_submitted,
                      submitted_to_phish, credential_exposure, takeover_success,
                      account_status_at_submit, session_state_at_submit
               FROM capture_events WHERE message_id=? ORDER BY step_index""",
            (message_id,),
        )
        official_submission = int(
            any(r["submission_target"] == "official_owned" for r in capture_rows)
        )
        forged_submission = int(
            any(
                r["submission_target"] in {"synthetic_unowned", "internal_capture"}
                for r in capture_rows
            )
        )
        credential_exposure = int(
            any(bool(r["credential_exposure"]) for r in capture_rows)
        )
        takeover_success = int(any(bool(r["takeover_success"]) for r in capture_rows))
        exposure_prevented = int(bool(credential_exposure) and not takeover_success)

        response = row["post_action_response"]
        # Judge-only: Blue could not know the origin, but changing account state
        # because of a legitimate platform message is an over-reaction cost.
        overreaction = int(
            (not forged)
            and (submitted or clicked)
            and response
            not in {None, "observed", "no_action_official_destination"}
        )

        page = repo.row(
            "SELECT blocked FROM phish_pages WHERE message_id=?", (message_id,)
        )
        page_blocked = page is not None and bool(page["blocked"])
        if submitted and forged:
            contained = page_blocked and response == "contained"
        elif clicked and forged:
            contained = page_blocked and response in {
                "contained", "page_blocked_stepup_required", "reported_handled"
            }
        else:
            contained = False
        containment_success = int(contained)
        user_saved = int(forged and action == "allow" and reported)
        correct = int((forged and action != "allow") or (not forged and action == "allow"))

        received_step = _event_step(repo, match_id, message_id, "MESSAGE_RECEIVED")
        assessed_step = _event_step(repo, match_id, message_id, "BLUE_PRE_ASSESS")
        detection_latency = (
            None
            if received_step is None or assessed_step is None
            else assessed_step - received_step
        )
        first_risk = min(
            (
                step
                for step in (
                    _event_step(repo, match_id, message_id, "USER_CLICK"),
                    _event_step(repo, match_id, message_id, "USER_SUBMIT"),
                )
                if step is not None
            ),
            default=None,
        )
        response_step = _event_step(
            repo, match_id, message_id, "BLUE_POST_RESPONSE"
        )
        containment_latency = (
            None
            if first_risk is None or response_step is None
            else response_step - first_risk
        )
        if detection_latency is not None:
            detection_values.append(detection_latency)
        if containment_latency is not None:
            containment_values.append(containment_latency)

        repo.execute(
            """INSERT INTO judge_evaluations(
                 message_id, blue_prediction, ground_truth, correct,
                 false_positive, false_negative, friction, warning_escape,
                 user_harm_click, user_harm_submit,
                 official_submission, forged_submission,
                 credential_exposure, takeover_success,
                 exposure_prevented_by_prior_lock, containment_success,
                 overreaction, user_saved, detection_latency_steps,
                 containment_latency_steps
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                message_id, action, row["true_origin"], correct,
                false_positive, false_negative, friction, warning_escape,
                harm_click, harm_submit, official_submission, forged_submission,
                credential_exposure, takeover_success, exposure_prevented,
                containment_success, overreaction, user_saved,
                detection_latency, containment_latency,
            ),
        )

        totals["n_forged" if forged else "n_official"] += 1
        totals["false_positive"] += false_positive
        totals["false_negative"] += false_negative
        totals["friction"] += friction
        totals["warning_escape"] += warning_escape
        totals["harm_click"] += harm_click
        totals["harm_submit"] += harm_submit
        totals["official_submission"] += official_submission
        totals["forged_submission"] += forged_submission
        totals["credential_exposure"] += credential_exposure
        totals["takeover_success"] += takeover_success
        totals["exposure_prevented_by_prior_lock"] += exposure_prevented
        totals["containment_success"] += containment_success
        totals["overreaction"] += overreaction
        totals["user_saved"] += user_saved

        if forged:
            difficulty = row["true_difficulty"]
            if action != "quarantine":
                red_score += RED_BYPASS[difficulty]
            if clicked:
                red_score += RED_CLICK[difficulty]
            if submitted:
                red_score += RED_SUBMIT[difficulty]
            if credential_exposure:
                red_score += SCORE_COEFFICIENTS["red_credential_exposure"]
            if takeover_success:
                red_score += SCORE_COEFFICIENTS["red_takeover_success"]
            if warning_escape:
                red_score += SCORE_COEFFICIENTS["red_warning_escape"]

            if action == "quarantine":
                blue_score += SCORE_COEFFICIENTS["blue_quarantine"]
            elif action == "warn" and warning_escape:
                blue_score += SCORE_COEFFICIENTS["blue_warn_escape"]
            elif action == "warn":
                blue_score += SCORE_COEFFICIENTS["blue_warn_abort"]
            if false_negative:
                blue_score += SCORE_COEFFICIENTS["blue_false_negative"]
            if containment_success:
                blue_score += SCORE_COEFFICIENTS["blue_containment"]
            if exposure_prevented:
                blue_score += SCORE_COEFFICIENTS["blue_takeover_prevented"]
        else:
            if false_positive:
                blue_score += SCORE_COEFFICIENTS["blue_false_positive"]
            if friction:
                blue_score += SCORE_COEFFICIENTS["blue_friction"]
        if overreaction:
            blue_score += SCORE_COEFFICIENTS["blue_overreaction"]

    discards = repo.row(
        """SELECT COUNT(*) AS n FROM safety_events
           WHERE match_id=? AND kind='discard'""",
        (match_id,),
    )["n"]
    red_score += int(discards) * SCORE_COEFFICIENTS["red_safety_discard"]
    avg_detection = mean(detection_values) if detection_values else None
    avg_containment = mean(containment_values) if containment_values else None
    detail = {
        "latency_scoring": "excluded_in_mvp",
        "red_safety_discards": int(discards),
        "score_coefficients": SCORE_COEFFICIENTS,
    }
    repo.execute(
        """INSERT INTO match_scores(
             match_id, red_score, blue_score, n_official, n_forged,
             false_positive, false_negative, friction, warning_escape,
             harm_click, harm_submit, official_submission, forged_submission,
             credential_exposure, takeover_success,
             exposure_prevented_by_prior_lock, containment_success,
             overreaction, user_saved, avg_detection_steps,
             avg_containment_steps, detail_json
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            match_id, red_score, blue_score,
            totals["n_official"], totals["n_forged"],
            totals["false_positive"], totals["false_negative"],
            totals["friction"], totals["warning_escape"],
            totals["harm_click"], totals["harm_submit"],
            totals["official_submission"], totals["forged_submission"],
            totals["credential_exposure"], totals["takeover_success"],
            totals["exposure_prevented_by_prior_lock"],
            totals["containment_success"], totals["overreaction"],
            totals["user_saved"], avg_detection, avg_containment,
            json.dumps(detail, ensure_ascii=False, sort_keys=True),
        ),
    )
    repo.commit()
    return {
        "red_score": red_score,
        "blue_score": blue_score,
        **totals,
        "avg_detection_steps": avg_detection,
        "avg_containment_steps": avg_containment,
        "detail": detail,
    }
