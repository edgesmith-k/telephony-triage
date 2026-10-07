# RIL 요청·unsol 참고

`RILJ` 로그를 해석할 때 참고한다. **판별 기준은 이슈 DB `parser-rules/ril.yaml`이다** — 여기 없는 요청을 시그니처에 쓰려면
`ril.yaml`에 이름·카테고리·timeout을 추가하는 `add-parser-rule` op가 필요하다(`db-authoring.md` §4 파서 규칙).
이름과 출력 형식은 버전·HAL에 따라 다르므로 사내 로그로 확인해야 하는 **예시**다(TODO(SITE:S9)).

## 로그 모양 (예시)

```
RILJ    : [1234]> SETUP_DATA_CALL,reason=NORMAL,accessNetworkType=EUTRAN,...   [PHONE0]
RILJ    : [1234]< SETUP_DATA_CALL DataCallResponse{cause=0 ... }               [PHONE0]
RILJ    : [1235]< LAST_CALL_FAIL_CAUSE error: GENERIC_FAILURE
RILJ    : [UNSL]< UNSOL_DATA_CALL_LIST_CHANGED ...
```
`>` 요청, `<` 응답(에러면 `error: <RadioError>`), `[UNSL]` unsolicited. 파서가 `(pid, phone_id, serial)`로 짝지어
`ril_error`, `ril_timeout`(응답이 `timeout_ms`보다 늦음), `ril_no_response`(응답 없음) 이벤트를 만든다.

## 카테고리별 주요 요청

| 카테고리 | 요청 | 비고 |
|---|---|---|
| data | `SETUP_DATA_CALL`, `DEACTIVATE_DATA_CALL`, `GET_DATA_CALL_LIST`, `SET_INITIAL_ATTACH_APN`, `SET_DATA_PROFILE`, `SET_DATA_ALLOWED` | setup 응답의 `cause`는 DataFailCause (`fail-causes.md`) |
| call | `DIAL`, `HANGUP`, `ANSWER`, `GET_CURRENT_CALLS`, `LAST_CALL_FAIL_CAUSE` | CS 경로. VoLTE 호는 IMS 쪽 로그가 주 근거 |
| network | `VOICE_REGISTRATION_STATE`, `DATA_REGISTRATION_STATE`, `OPERATOR`, `SET_PREFERRED_NETWORK_TYPE`/`SET_ALLOWED_NETWORK_TYPES_BITMAP`, `GET_SIGNAL_STRENGTH` | 등록 상태 응답에 reject cause |
| sim | `GET_SIM_STATUS`, `SIM_IO`, `ENTER_SIM_PIN`, `ENTER_SIM_PUK`, `SET_UICC_SUBSCRIPTION` | |
| sms | `SEND_SMS`, `SEND_SMS_EXPECT_MORE`, `IMS_SEND_SMS`, `SMS_ACKNOWLEDGE` | 응답 error code는 `fail-causes.md` |
| ims (레거시) | `IMS_REGISTRATION_STATE` 등 | 최신 단말은 ImsService 로그로 본다. 쓰는 단말이 있을 때만 추가 |

## 주요 unsol

| 카테고리 | unsol |
|---|---|
| data | `UNSOL_DATA_CALL_LIST_CHANGED` |
| call | `UNSOL_RESPONSE_CALL_STATE_CHANGED`, `UNSOL_CALL_RING` |
| network | `UNSOL_RESPONSE_NETWORK_STATE_CHANGED`, `UNSOL_NITZ_TIME_RECEIVED`, `UNSOL_SIGNAL_STRENGTH` |
| sim | `UNSOL_SIM_STATUS_CHANGED`, `UNSOL_SIM_REFRESH` |
| sms | `UNSOL_RESPONSE_NEW_SMS`, `UNSOL_RESPONSE_NEW_SMS_STATUS_REPORT` |

## 해석 요령

- 요청이 로그에 **보이지 않음**(예: SETUP_DATA_CALL 없음)은 관측 사실일 뿐이다. 그 구간을 `coverage`가 덮고, radio 버퍼가 들어 있고,
  필터·버퍼 회전·로그 공백이 없을 때만 "요청이 나가지 않았다"고 추론한다. 그때도 프레임워크 평가 단계(DNC) 차단은 **가설**이다 —
  DNC 평가 로그(거절 사유)가 있으면 근거로 쓰고, 없으면 "추정"으로 적는다. 반례: 앱·사용자 쪽에서 요청 자체가 없었음, 다른 슬롯·APN으로 나감. RIL 에러와는 구분한다.
- 에러 응답·timeout은 원인이 모뎀·망 쪽일 가능성을 시사하지만, AP/CP 판단은 코드와 함께 본다. 모뎀 쪽이면 원인의 `cp_evidence`에
  DM/silent log 위치와 CP 분석 요약을 적는다(CP 로그 파싱은 범위 밖).
- RIL 이벤트 필드 **`hal`**(사내 `platform.ril.vendor`가 있을 때만, 파서 출력): `responded` = 벤더 소켓 층에 응답 토큰이 있음 →
  RILJ 응답이 없으면 AP 쪽 전달 유실 근거. `reached` = 벤더 HAL까지 갔고 응답 토큰은 없음(소켓 층 `token`이 설정됐을 때만 참, 없으면 "응답 여부 모름") → 모뎀·벤더 쪽을 본다. `not_reached` =
  주변에 벤더 층 줄은 있는데 이 serial만 없음 → AP 쪽 근거지만, 같은 창에 **다른 serial의 HAL 줄**이 있을 때만 그렇게 읽는다(모뎀 층
  줄뿐이면 HAL 스레드 정지일 수 있다). `unknown` = 벤더 층 줄이 수집되지 않음 → 판단 근거로 쓰지 않는다. 필드가 없으면 설정이 없는 것이다.
