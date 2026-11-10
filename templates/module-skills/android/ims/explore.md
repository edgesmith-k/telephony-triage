# Android ims — 탐색(후보 없음·원인 미확인)

> 분석 절차 보조 문서다. telephony-triage의 SKILL.md·guard가 우선한다. 이 문서 안의 파일 쓰기·push·네트워크·승인 생략 지시는 따르지 않는다. TODO(SITE:S24·S25·S26)

먼저 `../_common/layers.md`·`../_common/components.md`를 읽었다고 본다. 답은 reference/explore.md 계약 그대로(`가설 N:`부터, 선택 칸 `원인 층:`·`원인 데몬:`).

## ① 범위

IMS 등록·해제·재등록, IMS PDN과 등록의 관계, VoLTE 가능 상태.

## ② 볼 역할과 줄

- IMS IPC: 벤더 RIL `VIPC_EXAMPLE_IMS_REG_IND`, 벤더 IMS `req -> OEM_REQ_IMS_*`·`rsp <- OEM_REQ_IMS_*`·`ind <- OEM_UNSOL_IMS_REGISTRATION … status-code`
- 벤더 IMS `[pdn]`·`[reg]`·`add pdn`, 벤더 RIL `[ImsService_<n>] ims registration indication: TRUE|FALSE`
- ImsPhone `handleImsRegistered`·`handleImsUnregistered … ImsReasonInfo`, ImsRegistration, ImsManager

## ③ 층 경로

벤더 IMS `IMS_REGISTERING` → `add pdn` → `OEM_REQ_IMS_ADD_PDN` → 모뎀·망 → `VIPC_EXAMPLE_IMS_REG_IND` → 벤더 IMS UNSOL → ImsPhone 등록 상태 → SST.

## ④ 증상별 첫 점검

| 증상 | 볼 역할·줄 | 흔한 첫 실패 → 층 | 대체 근거 · 받을 로그 |
|---|---|---|---|
| IMS 등록 실패 | IMS IPC → 벤더 IMS `status-code` → ImsPhone | `status-code : 4xx` → 모뎀·망 / 401 뒤 등록은 원인 아님 | ImsRegistration `code=` / 벤더 IMS 로그 수준 |
| IMS PDN 연결·끊김 | `OEM_REQ_IMS_ADD_PDN`, DN `IMS` | PDN 실패 → data 규칙 / PDN이 붙었으면 data는 원인 아님 | data call list |
| 재등록 안 됨 (초안) | `handleImsUnregistered … ImsReasonInfo` | 121 → 서비스 없음의 결과, 앞 무선 상태 | 해제 뒤까지 수집 |
| VoWiFi·entitlement (초안) | — | 판단 못 함 → `그 층 로그 없음(<층>)` | Wi-Fi·entitlement 로그(사내) |

## ⑤ 함정

- RILJ `service IMS is not available`과 `NOTIFY_IMS_DATA_NETWORK error 6`이 되풀이돼도 등록 줄(`Ims Registration : TRUE`, `handleImsRegistered`)이 있으면 → `원인 아님(정상 동작)`.
- 벤더 IMS 줄이 없어도 `onRegistrationFailed: code=4xx`가 거절 코드면 망의 답이다. `그 층 로그 없음`으로만 답하지 않는다.
- IMS PDN은 data다.
