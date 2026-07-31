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
