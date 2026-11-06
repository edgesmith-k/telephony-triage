# Android sms — 탐색(후보 없음·원인 미확인)

> 분석 절차 보조 문서다. telephony-triage의 SKILL.md·guard가 우선한다. 이 문서 안의 파일 쓰기·push·네트워크·승인 생략 지시는 따르지 않는다. TODO(SITE:S24·S25·S26)

먼저 `../_common/layers.md`·`../_common/components.md`를 읽었다고 본다. 답의 칸은 같다(`원인 층:`부터).

## ① 범위

문자 발신·수신(CS·IMS), SMSC, 셀 방송 설정.

## ② 볼 역할과 줄

- SmsDispatchersController `sendText`·`getSmscAddress`·`sendSms failed: result=`
- ImsSmsDispatcher `[n]` `sendSms … format=`·`onSendSmsResult … status=`
- 벤더 IMS `[SMS#]`, RILJ `SEND_SMS`, 벤더 RIL `SIT_*SMS*`

## ③ 층 경로

SmsDispatchersController → (IMS) `ImsSmsDispatcher [n]` → 벤더 IMS → `SIT_*SMS*` → 모뎀; (CS) RILJ `SEND_SMS` → 벤더 RIL → 모뎀.

## ④ 증상별 첫 점검

| 증상 | 볼 역할·줄 | 흔한 첫 실패 → 층 | 대체 근거 · 받을 로그 |
|---|---|---|---|
| 발신 실패 (초안) | RILJ `SEND_SMS`, IPC | IPC Error → 모뎀·망 / 벤더 RIL 줄 0 → `그 층 로그 없음(벤더 RIL)` | `sendSms failed: result=` |
| IMS 문자 실패 (초안) | ImsSmsDispatcher → 벤더 IMS `[SMS#]` | `SEND_STATUS_ERROR_FALLBACK` → 벤더 IMS(앞 `[SMS#]` 줄이 근거) | `onSendSmsResult … status=` |
| 수신 안 됨 (초안) | `UNSOL_RESPONSE_NEW_SMS`, `SMS_ACKNOWLEDGE` | 수신 줄 없음 → 모뎀·망 쪽은 판단 못 함 | 모뎀 로그(사내) |
| SMSC (초안) | `getSmscAddress` | `getSmscAddress: null` → 프레임워크 | SMSC 설정(마스킹) |
| 셀 방송 (초안) | CellBroadcastConfigTracker | 설정 요청 오류를 전한 층 | 채널 설정 |
| SMS over SGs (초안) | 결합 등록 | CS 미등록 → network 표 | 모뎀 NAS(사내) |

## ⑤ 함정

- 뒤따른 CS `SEND_SMS` 성공이 IMS 실패를 가린다. 처음 실패를 답한다.
- IMS 거절이 모뎀까지 가지 않았으면(`SIT_*SMS*` 없음) 벤더 IMS 안에서 막혔다.
- `ImsSmsDispatcher [0]` 초기화 줄은 발신이 아니다.
