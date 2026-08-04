# 지표·점수 의미 변경 기록

## 왜 바꿨나

경기 결과를 보다가 `credential_compromise`가 **사실상 항상 0**으로 나오는 것을 발견했다.
원인은 점수 계수가 아니라 **상태 전이와 지표 정의**에 있었다.

1. 합성 사용자가 **공식 메시지**의 링크를 눌러 제출하면, Blue의 사후 대응이
   계정을 `recovery_pending` / `revoked` 로 바꿨다.
2. 그 계정은 다음 시나리오에서도 그대로 재사용됐다.
3. 뒤이어 **위조 메시지**에 제출이 발생해도, 판정식이
   `account_status == 'active'` 를 요구했기 때문에 노출로 집계되지 않았다.

즉 정상적인 플랫폼 사용이 방어 조치를 유발하고, 그 조치가 뒤 시나리오의
공격 성공 지표를 지워버리는 구조였다. 지표가 죽어 있었을 뿐 아니라,
시나리오 결과가 **실행 순서에 의존**하고 있었다.

## 무엇을 바꿨나

### 1. 제출 목적지 분류 도입
모든 `USER_SUBMIT` 은 플랫폼이 관측 가능한 텔레메트리만으로 분류된다.

| 분류 | 의미 |
|------|------|
| `official_owned` | 링크 목적지가 공식 라우트 레지스트리에 등록됨 |
| `internal_capture` | 미등록 목적지이고 합성 캡처 페이지가 존재함 |
| `synthetic_unowned` | 미등록 목적지이고 캡처 페이지가 없음 |

Blue는 `is_forged` 나 GroundTruth를 읽지 않는다. 예전에는 `is_phish_page`
(정답에서 파생된 값)가 사용자 여정에 전달되고 있었는데, 이 경로를 제거했다.

### 2. 사후 대응 조건 축소
`official_owned` 제출·클릭은 **정상 플랫폼 행동**으로 간주해 아무 상태도 바꾸지 않는다
(`no_action_official_destination`). 계정 잠금·세션 폐기·페이지 차단은
`synthetic_unowned` / `internal_capture` 이거나 사용자 신고일 때만 실행된다.

### 3. 노출과 탈취 분리

```
credential_exposure = 유효한 합성 제출 행동이 캡처 지점에 도달함
                      (계정 상태와 무관)

takeover_success    = credential_exposure
                      AND 제출 시점 계정이 active
                      AND 제출 시점 세션이 revoked/stepup_required 가 아님
```

계정이 이미 보호 상태였다면 `credential_exposure = 1, takeover_success = 0`
이 되고, 그 차이는 `exposure_prevented_by_prior_lock` 으로 따로 집계된다.

### 4. 제출 순간 스냅샷
`account_status_at_submit`, `session_state_at_submit`, `submission_target` 을
**제출 이벤트 시점에** 기록한다. 경기 종료 후 계정을 다시 조회해 과거 결과를
계산하지 않는다.

### 5. 시나리오 격리
시나리오(프로필 × 난이도)마다 **독립된 합성 계정**(`accounts.scenario_key`)을 만들고,
RNG도 `Random(f"{seed}|{profile}-{level}")` 로 시나리오마다 분리했다.
Hard의 공식·위조 메시지 쌍은 같은 계정과 사건 상태를 공유하지만,
그 계정은 다음 시나리오로 넘어가지 않는다.

### 6. 새 지표
`credential_exposure`, `takeover_success`, `exposure_prevented_by_prior_lock`,
`official_submission`, `forged_submission`, `overreaction` 을 독립 집계한다.
대시보드의 모호했던 `Synthetic Compromise` 카드는
`Synthetic Credential Exposure` 와 `Simulated Takeover Success` 두 장으로 나눴다.

### 7. 점수 계수
| 항목 | 이전 | 현재 |
|------|------|------|
| Red 노출 | `red_compromise` +3 | `red_credential_exposure` +3 |
| Red 탈취 | 없음 | `red_takeover_success` +5 |
| Blue 탈취 저지 | 없음 | `blue_takeover_prevented` +2 |
| Blue 과잉 대응 | 없음 | `blue_overreaction` −4 |

`overreaction` 은 Judge 전용 판정이다. Blue는 메시지의 출처를 알 수 없지만,
**정품 플랫폼 메시지 때문에 계정 상태를 바꾼 것**은 방어 비용으로 계산한다.

## 고정 기대값이 왜 바뀌었나

`tests/test_app_smoke.py` (시드 `20260731`, mixed, balanced)

| 값 | 이전 | 현재 |
|----|------|------|
| RED SCORE | 0 | 0 |
| BLUE SCORE | **33** | **29** |

바뀐 이유는 두 가지다.

1. **RNG 분리**: 시나리오마다 독립 시드를 쓰므로 사용자 행동 난수 스트림이
   이전과 다르다. 같은 시드라도 개별 시나리오의 행동 결과가 달라진다.
2. **과잉 대응 감점 신설**: 이 시드에서는 공식 메시지 제출 3건 중 1건이
   드리프트 목적지(등록되지 않은 신규 경로)로 향해 Blue가 계정 상태를 바꿨다.
   `overreaction = 1` 이 잡히면서 `blue_overreaction` −4 가 적용됐다.

RED는 이 시드에서 모든 위조 시도가 사전 격리돼 이전과 같이 0이다.

## 회귀 테스트

`tests/test_submission_semantics.py`

- **시드 1088**: 공식 목적지 제출이 계정을 잠그지 않고, 모든 제출 스냅샷이
  `status = active` 임을 검증(앞 시나리오 오염 없음).
- **시드 1010**: 노출 2건 중 1건은 탈취 성공, 1건은 선행 방어로 차단됨을 검증.
  후자는 `account_status_at_submit != 'active'` 이면서
  `credential_exposure = 1, takeover_success = 0`.
- **순서 독립성**: 난이도를 단독 실행한 결과가 mixed 실행의 해당 구간과
  완전히 일치함을 4개 시드 × 3개 엄격도로 검증.
- **혼합 집계 금지**: `official_submission` 과 `forged_submission` 이 같은
  메시지에서 동시에 1이 되지 않음을 검증.
