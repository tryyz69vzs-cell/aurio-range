# Aurio Range

실제 네트워크·실제 계정·실제 자격증명 없이 실행되는 폐쇄형 계정탈취 방어 시뮬레이터입니다.

## 핵심 안전 설계

- Red는 구조화된 시나리오 변수만 만들고, HTML은 자동 escaping이 켜진 고정 Jinja2 템플릿이 렌더합니다.
- `accounts`에는 자격증명 비밀값이 없습니다. 제출은 네 개의 불리언 행동 상태로만 기록됩니다.
- User는 `RECEIVED`부터 시작하는 다단계 상태 머신이며, 모든 전환이 별도 이벤트와 `step_index`를 가집니다.
- 한 경기는 `sqlite3.connect(":memory:")`로 만든 독립 DB에서 실행됩니다.
- 단계 지연은 참고용으로 표시할 뿐 MVP 점수에는 반영하지 않습니다.
- 외부 API와 LLM을 사용하지 않습니다.

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
