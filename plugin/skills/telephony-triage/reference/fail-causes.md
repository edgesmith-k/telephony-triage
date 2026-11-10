# 실패 원인 코드 참고

> Android 플랫폼 기준이다. 다른 플랫폼(예: oFono)은 그 플랫폼 이슈 DB의 `parser-rules`를 본다.

로그의 원인 코드를 사람이 읽는 말로 옮길 때 참고한다. 표준 값(3GPP)은 안정적이지만 Android 열거 이름과 벤더 확장 코드는 버전·벤더마다
다르므로, 결론에 쓸 때는 대상 버전 소스(`DataFailCause`, `CallFailCause`, `ImsReasonInfo`, `SmsManager`)로 확인한다.
원인 시그니처에 코드를 쓸 때는 extractor가 뽑은 필드(`fields: {cause: '^31$'}`)로 쓴다.

## 데이터 setup 실패 (DataFailCause, 3GPP 24.301/24.008 ESM/SM cause 기반)

| 값 | 이름 | 뜻 |
|---|---|---|
| 0 | NONE | 성공 |
| 8 | OPERATOR_BARRED | 사업자 차단 |
| 26 | INSUFFICIENT_RESOURCES | 망 자원 부족 |
| 27 | MISSING_UNKNOWN_APN | APN 없음/모름 (APN 설정 확인) |
| 28 | UNKNOWN_PDP_ADDRESS_TYPE | IP 타입 불일치 (IPv4/IPv6/IPv4v6) |
| 29 | USER_AUTHENTICATION | PDN 인증 실패 |
| 30 | ACTIVATION_REJECT_GGSN | 게이트웨이 거절 |
| 31 | ACTIVATION_REJECT_UNSPECIFIED | 사유 없는 거절 |
| 32 | SERVICE_OPTION_NOT_SUPPORTED | 서비스 옵션 미지원 |
| 33 | SERVICE_OPTION_NOT_SUBSCRIBED | 가입 안 된 서비스 |
| 50 / 51 | ONLY_IPV4_ALLOWED / ONLY_IPV6_ALLOWED | 한쪽 IP 타입만 허용 |
| 55 | MULTI_CONN_TO_SAME_PDN_NOT_ALLOWED | 같은 PDN 중복 연결 불가 |
| 65 / 66 | MAX_ACTIVE_PDP_CONTEXT_REACHED / UNSUPPORTED_APN_IN_CURRENT_PLMN | PDN 수 초과 / 현재 망에서 미지원 APN |
| 0x10000 이상 등 | 벤더·프레임워크 확장 (예: RADIO_NOT_AVAILABLE, SIGNAL_LOST 류) | 버전 소스로 확인 |

## 음성 통화 종료 (CallFailCause, 3GPP 24.008 CC cause)

| 값 | 뜻 |
|---|---|
| 1 | Unassigned number |
| 16 | Normal clearing (정상 종료) |
| 17 | User busy |
| 18 / 19 | No user responding / No answer |
| 21 | Call rejected |
| 31 | Normal, unspecified |
| 34 | No circuit/channel available |
| 38 | Network out of order |
| 41 / 42 | Temporary failure / Switching equipment congestion |
| 47 | Resources unavailable |
| 65535(ERROR_UNSPECIFIED) 등 | 프레임워크 확장. 소스로 확인 |

- "통화 중 끊김"(call drop)과 "연결 실패"(call fail)를 구분한다. 16은 정상 종료다.
- VoLTE 호는 `ImsReasonInfo` 코드(예: 등록 안 됨, SIP 응답 코드 매핑)로 본다.

## IMS 등록·SIP

| 코드 | 뜻 |
|---|---|
| SIP 401/407 | 인증 필요(정상 절차의 일부. 반복되면 인증 실패) |
| SIP 403 | 금지(가입·정책 문제) |
| SIP 404 | 사용자 없음 |
| SIP 408 / 504 | 타임아웃 |
| SIP 480 / 503 | 일시 불가 / 서비스 불가 |
| SIP 500 | 서버 오류 |

## 망 등록 거절 (EMM/MM reject cause, 3GPP 24.301/24.008)

| 값 | 뜻 |
|---|---|
| 2 | IMSI unknown in HSS/HLR |
| 3 | Illegal UE |
| 6 | Illegal ME |
| 7 | EPS services not allowed |
| 11 | PLMN not allowed |
| 12 | Tracking/Location area not allowed |
| 13 | Roaming not allowed in this TA/LA |
| 15 | No suitable cells in TA/LA |
| 17 | Network failure |
| 22 | Congestion |

## SMS

| 코드 | 뜻 |
|---|---|
| RP cause 1 / 21 / 38 / 41 / 42 | Unassigned number / Short message transfer rejected / Network out of order / Temporary failure / Congestion |
| `RESULT_ERROR_GENERIC_FAILURE`, `RESULT_ERROR_RADIO_OFF`, `RESULT_ERROR_NO_SERVICE`, `RESULT_RIL_*` | `SmsManager` 전송 결과(프레임워크) |

## RIL 응답 오류 숫자 (RadioError)

`RILJ … error <n>`: 1 RADIO_NOT_AVAILABLE · 2 GENERIC_FAILURE · 6 REQUEST_NOT_SUPPORTED · 17 NO_SUCH_ELEMENT. 이름은 같은 serial의 `RilRequest` 줄(`CommandException: <이름>`)과 파서 이벤트에도 있다. 그 밖은 버전 소스로 확인한다.

## IMS 해제 사유 (ImsReasonInfo)

121 CODE_LOCAL_NETWORK_NO_SERVICE: 단말 쪽 서비스 없음(무선 꺼짐·OOS)의 결과다. 원인은 그 앞 무선 상태에서 찾는다. 0 CODE_UNSPECIFIED.

## 벤더 IPC 결과 (VIPC_E_*, placeholder — 사내 확인 TODO(SITE:S9))

`Error(VIPC_E_*)`는 모뎀이 준 결과다(접두어·성공 값은 site-defaults `vendor_ipc`, 성공 `VIPC_OK`는 이벤트로 내지 않는다): GENERIC_FAILURE 일반 실패 · NO_SUCH_ELEMENT 대상(AID·파일) 없음 · UNDEFINED_CMD 모뎀이 모르는 명령(미지원).
