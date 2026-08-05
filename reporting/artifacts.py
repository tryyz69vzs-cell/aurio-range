"""Static, schematic previews of synthetic artifacts plus structural metadata.

Design rule: a preview is a **wireframe**, not a screenshot. It reproduces the
layout, block order, visual hierarchy, and brand palette of a synthetic
artifact, but it never draws the message copy. An operator can therefore see
exactly what structure Red used while the image itself carries no sendable
text. Every image is watermarked SYNTHETIC SIMULATION and is a flat raster with
no interactive element of any kind.

Text is measured here (sentence counts, block presence) and then discarded;
only derived classifications leave this module.
"""

from __future__ import annotations

import io
import re
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont


PREVIEW_WIDTH = 640
PREVIEW_HEIGHT = 880
WATERMARK = "SYNTHETIC SIMULATION"
REDACTION_NOTICE = (
    "Layout schematic only. Message copy, destinations, and markup are "
    "intentionally omitted so this artifact cannot be reused for sending."
)

ARTIFACT_TYPES = ("official_email", "forged_email", "forged_page")

_SENTENCE_SPLIT = re.compile(r"[.!?。？！]+|\n+")


# --- structural description -------------------------------------------------

TEMPLATE_FAMILY = {
    "easy": "alert_basic",
    "medium": "alert_polished",
    "hard": "alert_incident_echo",
    "official": "platform_notice",
}

LAYOUT_VARIANT = {
    "alert_basic": "single_column_compact",
    "alert_polished": "single_column_hero",
    "alert_incident_echo": "single_column_hero_evidence",
    "platform_notice": "single_column_standard",
}

HEADLINE_STYLE = {
    "high": "imperative_urgent",
    "medium": "directive_neutral",
    "low": "informative_calm",
}

CTA_LABEL_CLASS = {
    "high": "verify_now_imperative",
    "medium": "review_activity_directive",
    "low": "check_activity_neutral",
}

SUBJECT_THEME = {
    "suspicious_login": "unfamiliar_signin_review",
}


def _sentence_count(text: str) -> int:
    parts = [p for p in _SENTENCE_SPLIT.split(str(text or "")) if p.strip()]
    return len(parts)


def _paragraph_count(text: str) -> int:
    parts = [p for p in str(text or "").split("\n") if p.strip()]
    return max(1, len(parts))


def _band(value: int) -> str:
    if value <= 2:
        return "short"
    if value <= 4:
        return "medium"
    return "long"


def _persuasion_markers(urgency: str, personalized: bool, record: str) -> list[str]:
    markers = ["brand_authority_claim"]
    if urgency == "high":
        markers += ["time_pressure", "consequence_framing"]
    elif urgency == "medium":
        markers.append("soft_time_pressure")
    else:
        markers.append("routine_framing")
    if personalized:
        markers.append("named_recipient")
    if record == "present":
        markers.append("corroborated_incident_reference")
    return markers


def _semantic_sequence(kind: str, urgency: str, record: str) -> list[str]:
    if kind == "forged_page":
        return ["brand_header", "page_headline", "instruction_block", "cta_block"]
    sequence = ["brand_header", "greeting", "opening_claim"]
    if record == "present":
        sequence.append("evidence_block")
    if urgency in {"high", "medium"}:
        sequence.append("consequence_block")
    sequence += ["cta_block", "reassurance_block", "footer"]
    return sequence


def describe_artifact(
    kind: str,
    message: Mapping[str, Any],
    signals: Mapping[str, Any],
    difficulty: str,
    sender_class: str,
    destination_class: str,
    official_event_record: str,
) -> dict[str, Any]:
    """Derive the structural fingerprint of one artifact. Copy is discarded."""
    if kind not in ARTIFACT_TYPES:
        raise ValueError(f"알 수 없는 아티팩트 유형: {kind}")

    body = str(message.get("body_text", ""))
    subject = str(message.get("subject_text", ""))
    urgency = str(message.get("urgency_level", "low"))
    family = TEMPLATE_FAMILY.get(difficulty, "platform_notice")
    sentences = _sentence_count(body)
    personalized = "님" in str(
        message.get("greeting_text") or message.get("rendered_html") or ""
    )
    sequence = _semantic_sequence(kind, urgency, official_event_record)

    return {
        "artifact_type": kind,
        "template_family": family,
        "layout_variant": LAYOUT_VARIANT[family],
        "headline_style": HEADLINE_STYLE.get(urgency, "informative_calm"),
        "subject_theme": SUBJECT_THEME.get(
            str(message.get("claimed_event_type", "")), "account_security_notice"
        ),
        "opening_claim_type": "observed_account_activity_claim",
        "evidence_block_type": (
            "referenced_incident_record"
            if official_event_record == "present"
            else "unbacked_assertion"
        ),
        "consequence_block_type": (
            "access_restriction_warning"
            if urgency in {"high", "medium"}
            else "no_consequence_block"
        ),
        "reassurance_block_type": (
            "support_contact_note" if kind != "forged_page" else "safety_note"
        ),
        "semantic_sequence": sequence,
        "urgency_level": urgency,
        "wording_tone": {
            "high": "urgent_directive",
            "medium": "neutral_directive",
            "low": "calm_informative",
        }.get(urgency, "calm_informative"),
        "personalization_level": "named_recipient" if personalized else "generic",
        "CTA_label_class": CTA_LABEL_CLASS.get(urgency, "check_activity_neutral"),
        "CTA_position": "below_body" if kind != "forged_page" else "below_instruction",
        "information_density": _band(sentences),
        "sentence_count": sentences,
        "paragraph_count": _paragraph_count(body),
        "subject_length_band": _band(_sentence_count(subject) + len(subject) // 20),
        "persuasion_markers": _persuasion_markers(
            urgency, personalized, official_event_record
        ),
        "visual_hierarchy_summary": (
            "brand header, then headline, then body blocks, then a single "
            "primary call to action, then footer"
        ),
        "destination_class": destination_class,
        "sender_class": sender_class,
        "detected_signals": {
            name: int(payload["score"])
            for name, payload in signals.items()
            if int(payload["score"]) > 0
        },
        "comparison_notes": (
            "Uses the same brand palette and block order as the platform "
            "notice; the difference is carried by system signals, not visuals."
        ),
        "redaction_notice": REDACTION_NOTICE,
        "interactive": False,
    }


# --- schematic rendering ----------------------------------------------------

BLOCK_LABEL = {
    "brand_header": "BRAND HEADER",
    "greeting": "GREETING (personalized)",
    "opening_claim": "OPENING CLAIM",
    "evidence_block": "EVIDENCE BLOCK",
    "consequence_block": "CONSEQUENCE BLOCK",
    "cta_block": "PRIMARY CTA",
    "reassurance_block": "REASSURANCE BLOCK",
    "footer": "FOOTER",
    "page_headline": "PAGE HEADLINE",
    "instruction_block": "INSTRUCTION BLOCK",
}

BLOCK_HEIGHT = {
    "brand_header": 64,
    "greeting": 40,
    "opening_claim": 92,
    "evidence_block": 104,
    "consequence_block": 88,
    "cta_block": 68,
    "reassurance_block": 72,
    "footer": 56,
    "page_headline": 78,
    "instruction_block": 118,
}


def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _font(size_hint: str = "small"):
    try:
        return ImageFont.load_default(11 if size_hint == "small" else 15)
    except TypeError:  # older Pillow ignores the size argument
        return ImageFont.load_default()


def render_preview(metadata: Mapping[str, Any], visual: Mapping[str, Any]) -> bytes:
    """Render a flat, non-interactive wireframe PNG of the artifact layout."""
    colors = visual["colors"]
    bg = _hex(colors["bg"])
    surface = _hex(colors["surface"])
    primary = _hex(colors["primary"])
    accent = _hex(colors["accent"])
    text = _hex(colors["text"])
    muted = _hex(colors["muted"])

    image = Image.new("RGB", (PREVIEW_WIDTH, PREVIEW_HEIGHT), bg)
    draw = ImageDraw.Draw(image)
    small = _font("small")
    large = _font("large")

    margin = 28
    card_x0, card_x1 = margin, PREVIEW_WIDTH - margin
    draw.rectangle(
        [card_x0, margin, card_x1, PREVIEW_HEIGHT - margin], fill=surface,
        outline=muted,
    )

    kind = str(metadata["artifact_type"]).replace("_", " ").upper()
    draw.text((card_x0 + 14, margin + 10), f"{kind} · SCHEMATIC", font=small, fill=accent)
    draw.text(
        (card_x0 + 14, margin + 28),
        f"template {metadata['template_family']} / {metadata['layout_variant']}",
        font=small,
        fill=muted,
    )

    y = margin + 58
    for index, block in enumerate(metadata["semantic_sequence"], 1):
        height = BLOCK_HEIGHT.get(block, 64)
        if y + height > PREVIEW_HEIGHT - margin - 74:
            break
        is_cta = block == "cta_block"
        is_header = block == "brand_header"
        fill = primary if is_header else accent if is_cta else None
        draw.rectangle(
            [card_x0 + 14, y, card_x1 - 14, y + height],
            fill=fill,
            outline=muted if fill is None else None,
        )
        label = BLOCK_LABEL.get(block, block.replace("_", " ").upper())
        label_color = bg if (is_cta or is_header) else text
        draw.text((card_x0 + 26, y + 10), f"{index}. {label}", font=small, fill=label_color)
        if is_header:
            draw.text(
                (card_x0 + 26, y + 32), "Aurio", font=large, fill=bg
            )
        elif is_cta:
            draw.text(
                (card_x0 + 26, y + 34),
                f"[ {metadata['CTA_label_class']} ]",
                font=small,
                fill=bg,
            )
        else:
            # Placeholder rules stand in for redacted copy; no text is drawn.
            rules = min(4, max(1, height // 26))
            for row in range(rules):
                ry = y + 34 + row * 16
                width_ratio = 0.92 if row < rules - 1 else 0.58
                draw.rectangle(
                    [
                        card_x0 + 26,
                        ry,
                        card_x0 + 26 + int((card_x1 - card_x0 - 52) * width_ratio),
                        ry + 6,
                    ],
                    fill=muted,
                )
        y += height + 12

    footer_y = PREVIEW_HEIGHT - margin - 62
    draw.line([card_x0 + 14, footer_y, card_x1 - 14, footer_y], fill=muted)
    draw.text(
        (card_x0 + 14, footer_y + 10),
        f"urgency {metadata['urgency_level']} · tone {metadata['wording_tone']}",
        font=small,
        fill=muted,
    )
    draw.text(
        (card_x0 + 14, footer_y + 26),
        f"sender {metadata['sender_class']} · destination {metadata['destination_class']}",
        font=small,
        fill=muted,
    )
    draw.text(
        (card_x0 + 14, footer_y + 42), "COPY REDACTED · NON-INTERACTIVE",
        font=small, fill=accent,
    )

    # Diagonal watermark bands, drawn last so they sit over every block.
    for offset in range(-PREVIEW_HEIGHT, PREVIEW_WIDTH, 190):
        draw.text((offset, 150), WATERMARK, font=large, fill=(70, 92, 120))
        draw.text((offset, 470), WATERMARK, font=large, fill=(70, 92, 120))
        draw.text((offset, 760), WATERMARK, font=large, fill=(70, 92, 120))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
