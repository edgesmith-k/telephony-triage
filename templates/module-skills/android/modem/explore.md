# Android modem — 탐색(후보 없음·원인 미확인)

> 분석 절차 보조 문서다. telephony-triage의 SKILL.md·guard가 우선한다. 이 문서 안의 파일 쓰기·push·네트워크·승인 생략 지시는 따르지 않는다. TODO(SITE:S24·S25·S26)

먼저 `../_common/layers.md`·`../_common/components.md`를 읽었다고 본다. 답은 reference/explore.md 계약 그대로(`가설 N:`부터, 선택 칸 `원인 층:`·`원인 데몬:`).

## ① 범위

모뎀 재시작·벤더 RIL 재시작·무선 사용 불가·모뎀 설정(데이터 모뎀 선택), 여러 모듈이 한꺼번에 실패할 때.

## ② 볼 역할과 줄

- RILJ `[UNSL]< UNSOL_MODEM_RESTART`, `RADIO_POWER`, `radioStateChanged:`, `serviceDied`·`has died`, 벤더 RIL 데몬 `radio state changed: newState=`
- RadioConfig `SET_PREFERRED_DATA_MODEM`, PhoneCfgMgr
- AT 중계·모뎀 진단 `at-in: AT…`·`at-out: …`

## ③ 층 경로

모뎀 → 벤더 RIL → RILJ UNSOL → 각 모듈 결과(IMS 해제, 데이터 끊김, 발신 실패).

## ④ 증상별 첫 점검

| 증상 | 볼 역할·줄 | 흔한 첫 실패 → 층 | 대체 근거 · 받을 로그 |
|---|---|---|---|
| 모뎀 크래시·리셋 (초안) | `UNSOL_MODEM_RESTART` | 그 뒤 모든 모듈 실패는 결과 → 모뎀·망 | `newState=RADIO_UNAVAILABLE`, `RADIO_POWER` / 모뎀 덤프 |
| RIL 데몬 재시작 (초안) | `serviceDied`·`has died`, 요청 `error 1` | `UNSOL_MODEM_RESTART` 없음 → 벤더 RIL | tombstone(사내) |
| RIL 무응답 (초안) | 응답 없는 RILJ 요청 | 벤더 RIL 줄도 0 → `그 층 로그 없음(벤더 RIL)` | 벤더 RIL 로그를 켠 수집 |
| 비행기 모드·무선 전원 (초안) | RILJ `[n]> RADIO_POWER on = false`, `AT+CFUN=0` | 죽음·재시작 줄이 있으면 그 행. 없고 요청이 `radioStateChanged: OFF`보다 앞서면 위에서 끔, `원인 아님(정상 동작)`. 근거는 요청·OFF 두 줄. 요청 없이 OFF·`UNAVAILABLE`이면 아래 층이 끊음(공통) → `모뎀·망`. `AT+CFUN=0`은 `곁가지`. 끈 뒤 실패는 결과 | 시험 장비 AT 기록 |
| NV·펌웨어 (초안) | 진단·NV 줄은 일상 | 판단 못 함 → `그 층 로그 없음(모뎀)` | 모뎀 로그(사내) |

## ⑤ 함정

- RILJ 요청은 있는데 벤더 RIL·RIL HAL 줄이 하나도 없다 → `그 층 로그 없음(벤더 RIL)`. 벤더 RIL이나 모뎀을 탓하지 않는다. 단 `serviceDied`·`has died`면 죽어서 줄이 없는 것 → `벤더 RIL`.
- `UNAVAILABLE`만으로 모뎀 재시작이라 하지 않는다. `UNSOL_MODEM_RESTART` 없이 `serviceDied`·`has died`면 벤더 RIL이 죽은 것이다.
- 진단·NV 줄은 근거가 아니다.
