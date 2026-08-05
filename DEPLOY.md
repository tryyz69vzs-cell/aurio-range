# Aurio Range 웹 배포 안내

이 문서는 코딩이나 터미널 사용 없이 GitHub 웹사이트와 Streamlit Community Cloud만으로 배포하는 절차입니다.

## 준비물

- GitHub 계정
- Streamlit Community Cloud에서 사용할 같은 GitHub 계정
- 이 `aurio_range` 폴더의 전체 파일

실제 API 키나 비밀값은 필요하지 않습니다.

## 1. GitHub에 저장소 만들기

1. 휴대폰이나 PC 브라우저에서 GitHub에 로그인합니다.
2. 오른쪽 위 `+` 버튼을 누르고 `New repository`를 선택합니다.
3. 저장소 이름에 `aurio-range`를 입력합니다.
4. 공개 배포가 목적이면 `Public`을 선택합니다.
5. `Create repository` 버튼을 누릅니다.

## 2. 프로젝트 파일 올리기

1. 새 저장소 화면에서 `uploading an existing file` 링크를 누릅니다.
2. 이 폴더 안의 파일과 폴더를 구조 그대로 모두 업로드합니다.
3. 특히 `app.py`, `requirements.txt`, `.streamlit`, `engine`, `safety`, `brandkit`가 빠지지 않았는지 확인합니다.
4. 아래쪽 `Commit changes` 버튼을 누릅니다.

GitHub 웹 업로드에서 숨김 폴더인 `.streamlit`을 선택하기 어렵다면 PC 파일 탐색기에서 폴더 전체를 압축 해제한 뒤 드래그하세요.

## 3. Streamlit Community Cloud에서 배포

1. 브라우저에서 `share.streamlit.io`에 접속합니다.
2. `Sign in with GitHub`를 선택하고 GitHub 연결을 승인합니다.
3. `Create app` 또는 `New app` 버튼을 누릅니다.
4. 방금 만든 `aurio-range` 저장소와 기본 브랜치 `main`을 선택합니다.
5. Main file path에는 `app.py`를 입력합니다.
6. `Advanced settings`에서 Python 3.12를 선택합니다.
7. 별도 비밀값 설정은 비워 둡니다.
8. `Deploy` 버튼을 누릅니다.

첫 빌드는 몇 분 걸릴 수 있습니다. 완료되면 표시된 공개 주소를 휴대폰 브라우저에서도 열 수 있습니다.

## 4. 정상 동작 확인

1. 화면 왼쪽의 안전 배지가 `SAFETY GATE · PASS`인지 확인합니다.
2. 난이도 `Mixed`, 엄격도 `balanced`, 합성 사용자 3명을 선택합니다.
3. `경기 실행` 버튼을 누릅니다.
4. Red·Blue 점수, 원시 지표, 신호 비교, 이벤트 타임라인이 나타나는지 확인합니다.
5. `감사·미리보기`에서 안전 이벤트가 없고, 페이지 미리보기에 실제 입력칸이 없는지 확인합니다.

## 업데이트 방법

GitHub 저장소에서 바꿀 파일을 열고 연필 모양 `Edit` 버튼으로 수정한 뒤 `Commit changes`를 누르면 Streamlit이 자동으로 다시 배포합니다.

`safety/constitution.py` 또는 `safety/trusted_registry.json`은 안전 해시로 잠겨 있습니다. 이 두 파일은 임의로 수정하면 앱 실행이 차단됩니다. 디자인 변경은 `brandkit/aurio_visual.json`에서 하며 안전 잠금에 영향을 주지 않습니다.

## Hugging Face Spaces 참고

Hugging Face는 새 Streamlit 앱의 기본 SDK를 제공하지 않으므로 Docker 구성이
추가로 필요합니다. 코딩을 모르는 사용자를 위한 이 MVP의 공식 배포 경로는
Streamlit Community Cloud 하나로 제한합니다.

배포 서비스의 정책이나 무료 요금제는 바뀔 수 있으므로 실제 배포 화면의 최신
안내를 함께 확인하세요.

---

## 6. Telegram 보고서 전송 (선택 사항)

경기가 끝나면 Red Team 보고서를 Telegram으로 받을 수 있습니다.
**설정하지 않아도 앱은 그대로 정상 작동합니다.** 기본값은 꺼짐입니다.

### 6-1. 준비물 두 가지

1. **봇 토큰** — Telegram에서 `@BotFather` 에게 `/newbot` 을 보내면 발급됩니다.
2. **Chat ID** — 만든 봇에게 아무 메시지나 보낸 뒤, `@userinfobot` 에게
   말을 걸면 본인 Chat ID를 알려줍니다.

### 6-2. Streamlit Cloud에 비밀값 넣기

배포된 앱 화면 오른쪽 아래 **Manage app** → **Settings** → **Secrets** 에
아래 내용을 붙여넣고 저장하세요.

```toml
[telegram]
enabled = true
bot_token = "여기에_봇_토큰"
chat_id = "여기에_챗_ID"
owner_pin = "직접_정한_숫자_PIN"
```

저장하면 앱이 자동으로 다시 시작됩니다.

> **중요**: 이 값들은 GitHub 저장소에 절대 올리지 마세요.
> 코드에는 어떤 토큰도 들어 있지 않으며, 앱은 `st.secrets` 에서만 읽습니다.

### 6-3. 사용법

앱 왼쪽 사이드바 **보고서 전송** 칸에서:

1. `TELEGRAM · 활성` 표시를 확인합니다.
   - `설정 누락` = 토큰이나 Chat ID가 없음
   - `비활성` = `enabled = false`
2. **관리자 PIN** 을 입력합니다. 맞으면 `관리자 확인됨` 이 뜹니다.
3. **경기 종료 후 자동 전송** 을 켜거나,
   **이번 경기 보고서 전송** 버튼으로 직접 보냅니다.

PIN이 필요한 이유는 공개 주소로 배포된 앱을 다른 사람이 열었을 때
내 Telegram으로 보고서가 쏟아지지 않게 하기 위해서입니다.
PIN은 세션 안에서만 쓰이고 저장되지 않습니다.

### 6-4. 무엇이 전송되나

경기가 끝나면 두 건만 옵니다.

1. **짧은 요약 메시지 1개** — 경기 시각, seed, 난이도·엄격도, Red/Blue 점수,
   위조 시도·격리·경고·허용 수, 클릭·제출·노출·탈취 수, 그리고
   "상세 내용은 첨부 보고서를 확인하세요."
2. **보고서 ZIP 파일 1개** — `aurio-report-<seed>-<시각>.zip`

전술별 장문 메시지가 채팅방에 여러 개 쌓이지 않습니다. 상세 분석과 미리보기
이미지는 전부 첨부 ZIP 안에 들어 있습니다.

보고서에는 메시지 원문, 피싱 문구, HTML, URL, 서명 토큰, 사건 참조 ID,
합성 계정 이메일, 데이터베이스 ID가 **들어가지 않습니다.**
발신자와 목적지는 `registered_official_sender`, `synthetic_unowned` 같은
분류 라벨로만 표시됩니다.

### 6-5. 전송이 실패하면

경기 결과는 그대로 남고, 사이드바에 전송 상태만 표시됩니다.
전송 실패가 경기를 실패시키지 않습니다.

---

## 7. 보고서 파일 받기

경기가 끝나면 **Red Team 보고서** 탭 위쪽에 다운로드 버튼 네 개가 생깁니다.

- `Markdown 보고서 다운로드` — 그대로 ChatGPT나 Claude에 첨부해 분석을 시킬 수 있습니다.
- `JSON 보고서 다운로드` — 같은 내용의 구조화 데이터입니다.
- `CSV 지표 다운로드` — 표 계산기로 열 수 있는 원시 지표입니다.
- `전체 보고서 ZIP 다운로드` — 위 파일 전부 + 미리보기 이미지가 들어 있습니다.

ZIP 안에는 각 위조 시도마다 **공식 메일 / 위조 메일 / 위조 페이지**의 정적 미리보기
PNG와 같은 이름의 설명 JSON이 들어 있습니다. 이미지는 클릭·입력·제출이 불가능한
그림 파일이며 `SYNTHETIC SIMULATION` 표시가 들어갑니다.

Telegram을 설정하지 않아도, 또는 전송이 실패해도 이 다운로드는 항상 동작합니다.

## 8. Telegram으로 받기

`DEPLOY.md` 6장대로 Secrets를 넣고 PIN을 입력하면, 경기가 끝날 때
**짧은 요약 메시지 1개와 보고서 ZIP 파일 1개**가 옵니다. 예전처럼 긴 메시지가
여러 개 오지 않습니다.

## 9. Adaptive Red Lab 쓰는 법

사이드바 아래쪽 **Adaptive Red Lab**에서:

1. `Adaptive Red 활성화`를 켭니다.
2. 세대 수(기본 3)와 세대당 후보 수(기본 8)를 정합니다. 처음에는 기본값 그대로
   두는 것을 권합니다.
3. `Red 진화 실행`을 누릅니다. 진행 상황과 상한이 화면에 표시됩니다.
4. 끝나면 `현재 최고 전략으로 경기 실행`을 눌러 그 전략으로 한 경기를 돌립니다.
5. 보고서 탭에 세대·부모·변경 필드·fitness·유지/폐기 이유가 카드로 나옵니다.

`진화 상태 초기화`를 누르면 이 세션의 진화 결과가 지워집니다. 앱을 닫아도
지워집니다(세션 안에서만 유지되는 Phase A 방식입니다).

## 10. GitHub Actions로 자동 진화 (선택)

휴대전화에서 GitHub 앱이나 웹으로 실행할 수 있습니다.

1. 저장소 → **Actions** 탭 → **Adaptive Red evolution** 선택
2. **Run workflow** 를 누르고 세대 수·후보 수·최대 경기 수·seed를 입력
3. 실행이 끝나면 `evolution_state/` 의 JSON과 `reports/` 의 보고서만 자동으로
   커밋됩니다.

안전 장치:

- 안전 게이트와 전체 테스트가 **먼저** 통과해야 진화가 실행됩니다.
- 진화 중 safety violation이 하나라도 나오면 상태를 저장하지 않습니다.
- 커밋 직전에 `tools/commit_guard.py` 가 변경 파일을 검사합니다. 코드·safety 파일·
  renderer·템플릿·테스트·워크플로·requirements 가 바뀌었으면 커밋하지 않고
  실패 처리합니다.

Telegram으로도 받고 싶으면 저장소 **Settings → Secrets and variables → Actions** 에
`TELEGRAM_BOT_TOKEN` 과 `TELEGRAM_CHAT_ID` 를 등록하세요. 관리자 PIN은 자동 실행에는
필요하지 않습니다.
