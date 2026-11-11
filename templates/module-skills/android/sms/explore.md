# Android sms — 탐색(후보 없음·원인 미확인)

> 분석 절차 보조 문서다. telephony-triage의 SKILL.md·guard가 우선한다. 이 문서 안의 파일 쓰기·push·네트워크·승인 생략 지시는 따르지 않는다. TODO(SITE:S24·S25·S26)

먼저 `../_common/layers.md`·`../_common/components.md`를 읽었다고 본다. 답은 reference/explore.md 계약 그대로(`가설 N:`부터, 선택 칸 `원인 층:`·`원인 데몬:`).

## ① 범위

문자 발신·수신(CS·IMS), SMSC, 셀 방송 설정.

## ② 볼 역할과 줄

- SmsDispatchersController `sendTextInternal:` · GsmSMSDispatcher `sendSms:  isIms()=false … SS=<n>`(CS 발신, `SS=1~3` 서비스 없음)
- ImsSmsDispatcher `[n]` `sendSms:  mRetryCount=…`·`onSendSmsResult … status=<n>`·`sendSms failed. Falling back to PSTN.`
- 벤더 IMS `[sms]`, RILJ `SEND_SMS`, 벤더 RIL `VIPC_*SMS*`

## ③ 층 경로

SmsDispatchersController → (도메인 선택이면 `DomainSelectionConnection-SMS`) → (IMS) `ImsSmsDispatcher [n]` → 벤더 IMS → `VIPC_*SMS*` → 모뎀; (CS) RILJ `SEND_SMS` → 벤더 RIL → 모뎀.

## ④ 증상별 첫 점검

| 증상 | 볼 역할·줄 | 흔한 첫 실패 → 층 | 대체 근거 · 받을 로그 |
|---|---|---|---|
| 발신 실패 (초안) | RILJ `SEND_SMS`, IPC | IPC Error → 모뎀·망 / 벤더 RIL 줄 0 → `그 층 로그 없음(벤더 RIL)` | RILJ `< SEND_SMS error <n>` |
| IMS 문자 실패 (초안) | ImsSmsDispatcher → 벤더 IMS `[sms]` | `onSendSmsResult … status=4`(FALLBACK) → 벤더 IMS(앞 `[sms]` 줄이 근거) | `sendSms failed. Falling back to PSTN.` |
| 수신 안 됨 (초안) | `UNSOL_RESPONSE_NEW_SMS`, `SMS_ACKNOWLEDGE` | 수신 줄 없음 → 모뎀·망 쪽은 판단 못 함 | 모뎀 로그(사내) |
| SMSC (초안) | 발신 요청 유무 | AOSP 발신 경로는 SMSC 값을 찍지 않는다. 요청이 없으면 → 프레임워크(`SS=1~3`이면 SMSC가 아니라 서비스 없음) | SMSC 설정(마스킹) |
| 셀 방송 (초안) | CellBroadcastConfigTracker | 설정 요청 오류를 전한 층 | 채널 설정 |
| SMS over SGs (초안) | 결합 등록 | CS 미등록 → network 표 | 모뎀 NAS(사내) |

## ⑤ 함정

- 뒤따른 CS `SEND_SMS` 성공이 IMS 실패를 가린다. 처음 실패를 답한다.
- IMS 거절이 모뎀까지 가지 않았으면(`VIPC_*SMS*` 없음) 벤더 IMS 안에서 막혔다.
- `ImsSmsDispatcher [0]` 초기화 줄은 발신이 아니다.
