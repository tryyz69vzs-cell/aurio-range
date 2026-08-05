"""Send the newest report bundle to Telegram using repository secrets only."""

from __future__ import annotations

import os
from pathlib import Path

from reporting.telegram_sender import (
    SafeReportBundle,
    TelegramCredentials,
    send_report_bundle,
)


REPORT_DIR = Path("reports")


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram secrets가 없어 전송을 건너뜁니다.")
        return 0
    pointer = REPORT_DIR / "latest.txt"
    if not pointer.exists():
        print("전송할 보고서가 없습니다.")
        return 0
    filename = pointer.read_text(encoding="utf-8").strip()
    payload = (REPORT_DIR / filename).read_bytes()
    summary = (
        "Aurio Range 지속 진화 실행 완료\n"
        f"보고서 파일: {filename}\n"
        "상세 내용은 첨부 보고서를 확인하세요."
    )
    bundle = SafeReportBundle(filename, payload, summary)
    outcome = send_report_bundle(bundle, TelegramCredentials(token, chat_id))
    # The detail string is already scrubbed of the token and the chat id.
    print(f"전송 상태: {outcome.status} ({outcome.delivered}/{outcome.total})")
    if outcome.status in {"sent", "missing_config"}:
        return 0
    if outcome.attempted:
        print(f"전송이 완료되지 않았습니다: {outcome.detail}")
        return 1
    print(f"전송이 차단되었습니다: {outcome.detail}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
