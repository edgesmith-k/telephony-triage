# oFono ims — 탐색(후보 없음)

> 분석 절차 보조 문서다. telephony-triage의 SKILL.md·guard가 우선한다. 이 문서 안의 파일 쓰기·push·네트워크·승인 생략 지시는 따르지 않는다. TODO(SITE:S24·S25·S26)

## ① 증상 범위
IMS(VoLTE) 등록·해제, IMS PDN. 통화·문자 자체는 `call`·`sms`다.

## ② 볼 역할과 줄
- 1순위: AIMS SIT — 벤더 RIL `SIT_IND_AIMS_REG*`·`SIT_AIMS_*`.
- IMS 서비스 데몬 `[SLOT_<n>]` `registered:<0|1>`·`[IMS_REGISTERED]`, `[SID_0] UNSOL {RILC_UNSOL_AIMS_REG_FAIL…} … [fail-code : <n>]`.
- ofonod `src/ims.c`·`drivers/rilmodem/ims.c`, `IMS_UNSOL_UPDATE_IMS_REG_FAIL fail_code=<n>`, `IMS_REQUEST_*`.

## ③ 층 경로
IMS 서비스 데몬 `IMS_UNSOL_REQUEST_ACT_PDN` → ofonod `SETUP_DATA_CALL (…ims…)` → `SIT_AIMS_ADD_PDN_INFO` → 모뎀 AIMS → `SIT_IND_AIMS_REG*`.

## ④ 증상별 첫 점검
| 증상 | 볼 역할·줄 | 흔한 첫 실패 → 층 | 대체 근거 · 받을 로그 |
|---|---|---|---|
| IMS 등록 실패 | `SIT_IND_AIMS_REG*` → fail-code → ofonod | 거절 반복 → 모뎀·망 / 401 뒤 1초 안 등록 → 원인 아님 | `fail_code=`·`registered:0` |
| IMS PDN 연결·끊김 | `IMS_UNSOL_REQUEST_ACT_PDN`·`SIT_AIMS_ADD_PDN_INFO` | data 규칙 | `SETUP_DATA_CALL (…ims…)` |
| 재등록 안 됨 (초안) | 거절 뒤 다음 시도 | 로그 밖 → 그 층 로그 없음(<층>) | 재시도 구간 수집 |
| VoWiFi·entitlement (초안) | — | 판단 못 함 → 그 층 로그 없음(<층>) | entitlement 로그 |

## ⑤ 함정
- 401 뒤 약 1초 안에 `[IMS_REGISTERED]`면 인증 요청 뒤 등록이다 → `원인 아님(정상 동작)`.
- 시작 때 `ctxOperatorInfo is NULL`, 비행기 모드 뒤 "no ApnEntity for IMS"는 순서 문제다.
