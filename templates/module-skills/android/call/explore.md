# Android call — 탐색(후보 없음·원인 미확인)

> 분석 절차 보조 문서다. telephony-triage의 SKILL.md·guard가 우선한다. 이 문서 안의 파일 쓰기·push·네트워크·승인 생략 지시는 따르지 않는다. TODO(SITE:S24·S25·S26)

먼저 `../_common/layers.md`·`../_common/components.md`를 읽었다고 본다. 답의 칸은 같다(`원인 층:`부터).

## ① 범위

발신·수신·통화 끊김(CS·VoLTE)과 부가서비스(착신 전환 등, UT).

## ② 볼 역할과 줄

- AIMS SIT: 벤더 RIL `SIT_*AIMS*`, 벤더 IMS `SOL TX/RX{RILC_REQ_AIMS_*}`·통화 SIP 응답 `status-code`
- ImsPhoneCallTracker `dial: … imsRegistered=`·`call state changed:`, ImsPhoneMmiCode·ImsUt
- RILJ `DIAL`·`GET_CURRENT_CALLS`·`LAST_CALL_FAIL_CAUSE causeCode=`

## ③ 층 경로

CS: RILJ `DIAL` → 벤더 RIL → 모뎀 → `LAST_CALL_FAIL_CAUSE`. VoLTE: ImsPhoneCallTracker → 벤더 IMS(SIP) → 망. UT: ImsUt → 벤더 IMS `[UT##]` → `SIT_AIMS_*` → `State=`.

## ④ 증상별 첫 점검

| 증상 | 볼 역할·줄 | 흔한 첫 실패 → 층 | 대체 근거 · 받을 로그 |
|---|---|---|---|
| 발신 실패 | RILJ `DIAL`, IPC `SIT_DIAL` | IPC Error → 모뎀·망 / OK 뒤 `errorCode≠0` → 벤더 RIL | `LAST_CALL_FAIL_CAUSE` |
| CSFB 실패 | 발신 전 `VOICE_REGISTRATION_STATE` | CS 미등록(결합 등록 실패) → 모뎀·망(network 표) | 모뎀 NAS(사내) |
| VoLTE 호 설정 실패(SIP) | AIMS SIT, `imsRegistered=true`, 벤더 IMS SIP 응답 | SIP 4xx·5xx → 모뎀·망 / `imsRegistered=false` → ims 등록부터 | `call state changed:` |
| EPS fallback·VoNR (초안) | 비행기 모드·IMS 해제 시각 | 그 뒤 fallback 실패 → 원인 아님 | — |
| eCall(MSD 전송 실패) | eCall 줄(이름 TODO(SITE:S24)) | eCall·MSD 줄이 없으면 → `그 층 로그 없음(eCall)` | eCall·모뎀 IVS 로그(사내) |
| 통화 끊김·착신 안 됨 (초안) | `UNSOL_RESPONSE_CALL_STATE_CHANGED`, `causeCode=` | 원인 코드를 전한 층 | — |
| 통화 중 소리 없음 (초안) | 통화 상태가 정상인지만 | 판단 못 함 → `그 층 로그 없음(오디오)` | 오디오 HAL·RTP(사내) |
| 부가서비스(UT) (초안) | 벤더 IMS `[UT##]`, `State=` | RILJ 없음이 정상 | — |

## ⑤ 함정

- UT에는 RILJ 요청이 없다 — `그 층 로그 없음`이 아니다. `State=COMPLETE`면 `원인 아님(정상 동작)`.
- `imsRegistered=true`의 SIP 거절은 ImsPhoneCallTracker 탓이 아니다(결과를 옮김).
- AT 중계 `UsbAgent: ATD…`는 시험 장비 입력이다.
