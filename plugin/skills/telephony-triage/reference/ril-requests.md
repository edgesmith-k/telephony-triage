# RIL 요청·unsol 참고

`RILJ` 로그를 해석할 때 참고한다. **판별 기준은 이슈 DB `parser-rules/ril.yaml`이다** — 여기 없는 요청을 시그니처에 쓰려면
`ril.yaml`에 이름·카테고리·timeout을 추가하는 `add-parser-rule` op가 필요하다(`db-authoring.md` 6절).
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

- 요청이 **아예 나가지 않은** 문제(예: SETUP_DATA_CALL 미발생)는 프레임워크 평가 단계(DNC)에서 막힌 것이다. RIL 에러와 구분한다.
- 에러 응답·timeout은 원인이 모뎀·망 쪽일 가능성을 시사하지만, AP/CP 판단은 코드와 함께 본다. 모뎀 쪽이면 원인의 `cp_evidence`에
  DM/silent log 위치와 CP 분석 요약을 적는다(CP 로그 파싱은 범위 밖).
