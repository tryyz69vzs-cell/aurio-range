# Aurio Range

실제 계정·실제 자격증명·실제 서비스 연결 없이 실행되는 폐쇄형 계정탈취 방어 시뮬레이터입니다.
시뮬레이션 자체는 네트워크 없이 동작하며, 선택적인 운영 보고 전송만 예외입니다.

## 핵심 안전 설계

- Red는 구조화된 시나리오 변수만 만들고, HTML은 자동 escaping이 켜진 고정 Jinja2 템플릿이 렌더합니다.
- `accounts`에는 자격증명 비밀값이 없습니다. 제출은 네 개의 불리언 행동 상태로만 기록됩니다.
- User는 `RECEIVED`부터 시작하는 다단계 상태 머신이며, 모든 전환이 별도 이벤트와 `step_index`를 가집니다.
- 한 경기는 `sqlite3.connect(":memory:")`로 만든 독립 DB에서 실행됩니다.
- 단계 지연은 참고용으로 표시할 뿐 MVP 점수에는 반영하지 않습니다.
- Red, Blue, User, Judge, Renderer, Safety Engine은 네트워크 이그레스가 없습니다.
- `reporting/telegram_sender.py` 만, 사용자가 명시적으로 활성화했을 때
  `api.telegram.org` 로 정제된 보고서를 전송합니다. 기본값은 꺼짐입니다.
- LLM 및 그 밖의 외부 API는 사용하지 않습니다.

## 로컬 실행

Python 3.11 이상에서 프로젝트 폴더를 연 뒤 의존성을 설치하고 Streamlit을 실행합니다.

```text
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

전체 자동 검증:

```text
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## 구성

- `app.py`: 경기 실행 패널과 결과 대시보드
- `engine/`: Red·Blue·User·Judge와 인메모리 경기 엔진
- `brandkit/`: 고정 Jinja2 템플릿과 신뢰 렌더러
- `safety/`: 해시 잠금, 시작 게이트, 구조화 Red 검증
- `tests/`: 안전·격리·점수·분포 및 재현성 검증

자세한 웹 배포 절차는 `DEPLOY.md`에 있습니다.

## Red Team 보고서

경기가 끝나면 대시보드의 **Red Team 보고서** 탭에서 각 위조 시도별 카드를 볼 수 있습니다.
카드는 모바일 세로 화면에 맞춰 여섯 개 구역으로 구성됩니다.

- Red 가설 / 공격 시뮬레이션 개요 / Blue 탐지 결과 / User 반응 / 최종 결과 / 연구 메모

보고서는 `reporting/` 패키지가 생성하며, 해시 잠금된 `reporting/sanitizer.py` 가
본문·URL·서명 토큰·계정 식별자·실제 도메인·실제 서비스 이름을 fail-closed 로 차단합니다.

## 네트워크 경계

| 구성요소 | 네트워크 |
|----------|----------|
| `engine/` (Red · Blue · User · Judge) | 이그레스 없음 |
| `brandkit/` (Renderer) | 이그레스 없음 |
| `safety/` (Safety Engine) | 이그레스 없음 |
| `app.py` | 이그레스 없음 |
| `reporting/` (models · sanitizer · red_report · formatter · delivery) | 이그레스 없음 |
| `reporting/telegram_sender.py` | **`api.telegram.org` 전용, 기본 비활성** |

전송 모듈의 제약:

- 목적지 호스트는 해시 잠금된 `safety/constitution.py` 의 정책 상수에서만 읽습니다.
  모듈 전역을 바꿔도 목적지가 바뀌지 않습니다.
- HTTP 301·302·303·307·308 리다이렉트를 따라가지 않습니다. 리다이렉트 응답을 받으면
  대상이 `api.telegram.org` 이더라도 즉시 실패 처리하며, 두 번째 요청을 보내지 않습니다.
- 이미 정제된 `SafeRedReport` 객체만 받습니다. 다른 타입은 `TypeError` 입니다.
- 봇 토큰과 Chat ID는 결과·예외·로그·데이터베이스·보고서 어디에도 남지 않습니다.
- 전송 실패는 경기 결과에 영향을 주지 않고 화면에 상태만 표시됩니다.

앱 상단 배지가 현재 상태를 보여줍니다.

- `SIMULATION ENGINE · NO EGRESS` — 시뮬레이션 엔진은 항상 네트워크를 쓰지 않습니다.
- `REPORTING · OFFLINE` — Telegram이 비활성이거나 설정이 없습니다.
- `REPORTING · TELEGRAM ONLY` — Telegram이 활성화되어 있습니다.
- `● 안전 게이트 통과` / `● 안전 게이트 차단` — 안전 게이트 결과입니다.
  차단 상태에서는 경기 실행과 보고서 전송이 모두 비활성화됩니다.

## Telegram 보고 형식

경기 종료 시 Telegram으로 가는 것은 두 건뿐입니다.

- `sendMessage` 짧은 요약 1건
- `sendDocument` 보고서 ZIP 1건 (`aurio-report-<seed>-<시각>.zip`)

긴 텍스트를 여러 메시지로 나눠 보내지 않습니다. 상세 분석·원시 지표·정적
미리보기 이미지는 모두 첨부 ZIP 안에 있습니다.

## 지표 의미 변경

`credential_compromise` 는 `credential_exposure` 와 `takeover_success` 로 분리됐습니다.
변경 이유와 고정 기대값이 바뀐 근거는 `docs/SCORING_CHANGELOG.md` 에 있습니다.
