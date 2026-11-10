# oFono sms — 탐색(후보 없음)

> 분석 절차 보조 문서다. telephony-triage의 SKILL.md·guard가 우선한다. 이 문서 안의 파일 쓰기·push·네트워크·승인 생략 지시는 따르지 않는다. TODO(SITE:S24·S25·S26)

## ① 증상 범위
문자 보내기·받기, IMS 문자, SMSC, 셀 방송, SMS over SGs.

## ② 볼 역할과 줄
- `org.ofono.MessageManager` `SendMessage`, `src/sms.c`(재시도 줄), `src/cbs.c`.
- CS: gril `SEND_SMS`·`SMS_ACKNOWLEDGE`, `UNSOL_RESPONSE_NEW_SMS`, 벤더 RIL `ExampleSmsService_<n>`(가정, 사내 확인).
- IMS: IMS 구성요소 `ImsSmsSender::sendSms`, IMS IPC TX. `smsOverLteCapable=<0|1>`이 길을 고른다.

## ③ 층 경로
D-Bus → ofonod sms → gril → 벤더 RIL → 모뎀·망, 또는 ofonod IMS 길 → IMS 구성요소 → IMS IPC → 모뎀.

## ④ 증상별 첫 점검
| 증상 | 볼 역할·줄 | 흔한 첫 실패 → 층 | 대체 근거 · 받을 로그 |
|---|---|---|---|
| 발신 실패 (초안) | gril `SEND_SMS` → 벤더 RIL·IPC | 두 단계 규칙 / 줄 없음 → 그 층 로그 없음(벤더 RIL) | `src/sms.c` 재시도 |
| IMS 문자 (초안) | `smsOverLteCapable=1`, `sendSms` | `failed` 뒤 IMS IPC TX 없음 → 곁가지 | IMS 문자 로그 |
| 수신 안 됨 (초안) | `UNSOL_RESPONSE_NEW_SMS`·`SMS_ACKNOWLEDGE` | UNSOL 없음 → 그 층 로그 없음(벤더 RIL) | 수신 시각 수집 |
| SMSC (초안) | SMSC 토큰 | 값으로 판단하지 않음 | SMSC 설정 |
| 셀 방송 (초안) | `src/cbs.c` | 줄이 말하는 그대로 | — |
| SMS over SGs (초안) | 결합 등록(network) | CS 거절 → 모뎀·망 | 모뎀 NAS |

## ⑤ 함정
- 같은 시간대 벤더 RIL 잡음 줄(신호 세기)은 그 요청이 기록됐다는 증거가 아니다.
- `smsOverLteCapable=0`이면 CS 길이 맞다.
