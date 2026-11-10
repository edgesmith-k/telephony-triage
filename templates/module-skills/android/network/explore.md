# Android network — 탐색(후보 없음·원인 미확인)

> 분석 절차 보조 문서다. telephony-triage의 SKILL.md·guard가 우선한다. 이 문서 안의 파일 쓰기·push·네트워크·승인 생략 지시는 따르지 않는다. TODO(SITE:S24·S25·S26)

먼저 `../_common/layers.md`·`../_common/components.md`를 읽었다고 본다. 답은 reference/explore.md 계약 그대로(`가설 N:`부터, 선택 칸 `원인 층:`·`원인 데몬:`).

## ① 범위

망 등록·서비스 상태·거절 사유·NR 모드·무선 상태에 따른 서비스 없음.

## ② 볼 역할과 줄

- SST `pollState`, `Poll ServiceState done: newSS=`, `hasRegistered = true`
- RILJ `VOICE_REGISTRATION_STATE`·`DATA_REGISTRATION_STATE` → `RegStateResult{regState:…, reasonForDenial:…}`
- NRM-C `onRequestNetworkRegistrationInfoComplete`, 벤더 RIL `VIPC_EXAMPLE_*_REG`, 벤더 RIL 데몬·AT 중계·모뎀 진단(무선)

## ③ 층 경로

SST → RILJ 등록 상태 요청 → RIL HAL → 벤더 RIL IPC → 모뎀·망 → RILJ `RegStateResult` → NRM → SST 새 상태.

## ④ 증상별 첫 점검

| 증상 | 볼 역할·줄 | 흔한 첫 실패 → 층 | 대체 근거 · 받을 로그 |
|---|---|---|---|
| 등록 안 됨·서비스 없음 | `RegStateResult`, SST | `REG_DENIED`·`reasonForDenial≠NONE` → 모뎀·망 / 거절 없는 긴 미등록은 찾는 중 | NRM-C `rejectCause=` / 모뎀 NAS(사내) |
| 무선 꺼진 뒤 서비스 없음 | `RADIO_POWER`, `AT+CFUN=0`, `RADIO_OFF`·`radioStateChanged: OFF` | 끈 뒤 실패는 결과 → 끈 쪽(AT 중계면 곁가지) | 벤더 RIL 데몬 줄 |
| NR(SA/NSA) 모드 | NetworkTypeController, `UNSOL_PHYSICAL_CHANNEL_CONFIG` | IPC Error → 모뎀·망 (세부 초안) | 모뎀 로그(사내) |
| CSFB 쪽 결합 등록 (초안) | `VOICE_`(CS)·`DATA_REGISTRATION_STATE`(PS) | PS만 등록·CS 거절 → 모뎀·망(call 증상의 원인) | 모뎀 NAS(사내) |
| 로밍·제한 서비스 (초안) | 등록 상태 값 | 값이 말하는 그대로 | — |

## ⑤ 함정

- 첫 RILJ 줄이 응답(`[n]<`)이다 → radio 버퍼가 늦게 시작했다. 그 전 요청과 무선 켜짐은 RILJ에 없다 → `그 층 로그 없음(RILJ)`. 벤더 RIL 데몬 `RADIO_ON`이 더 이른 것은 벤더 줄이 먼저 남은 것뿐이다.
- `reasonForDenial: NONE`·`rejectCause=0`은 사유가 없다는 뜻일 뿐이다. 거절인지는 `regState`·`registrationState`로 본다: DENIED가 아니면 거절이 아니고, DENIED면 모뎀·망(사유를 안 준 것은 벤더 RIL).
- 셀·사업자 값은 마스킹 토큰이다.
