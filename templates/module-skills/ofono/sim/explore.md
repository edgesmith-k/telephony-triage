# oFono sim — 탐색(후보 없음)

> 분석 절차 보조 문서다. telephony-triage의 SKILL.md·guard가 우선한다. 이 문서 안의 파일 쓰기·push·네트워크·승인 생략 지시는 따르지 않는다. TODO(SITE:S24·S25·S26)

## ① 증상 범위
SIM 인식·파일 읽기, eSIM(EID·프로필·채널), PIN. IMS 인증은 `ims`다.

## ② 볼 역할과 줄
- SIM 구성요소, 관리 데몬 `GetEID`.
- `org.ofono.SimManager` Present·`ExampleOpenChannel`(placeholder 메서드), `src/sim.c`·`drivers/rilmodem/sim.c`.
- gril `SIM_IO`·`SIM_OPEN_CHANNEL`, 벤더 RIL `[ExampleIccService_<n>] …`·`… sw1 : <XX>, sw2 : <XX>`.

## ③ 층 경로
클라이언트 → SimManager → ofonod sim → gril → 벤더 RIL → IPC `VIPC_EXAMPLE_CARD_IO`·`VIPC_EXAMPLE_CARD_OPEN` → 카드.

## ④ 증상별 첫 점검
| 증상 | 볼 역할·줄 | 흔한 첫 실패 → 층 | 대체 근거 · 받을 로그 |
|---|---|---|---|
| SIM 인식 안 됨 | Present·`SIM_IO`, eSIM은 SIM 구성요소 enable | IPC Error·SW → 모뎀·망 / OK 뒤 `result≠0` → 벤더 RIL | gril `(sw1=…)` |
| 인식 느림 | gril → IPC TX → RX 시각 | TX↔RX 길면 모뎀·망 / gril↔TX 길면 벤더 RIL | 부팅부터 수집 |
| eSIM(프로필·EID·채널) | SIM 구성요소 → `ExampleOpenChannel` | 열린 채널 중 busy → 관리 데몬 / `6A82` → 모뎀·망 | 채널을 연 쪽 |
| SIM 파일 읽기 실패 (초안) | `SIM_IO` `efid=` | 하나만 실패 → 벤더 RIL | SW 로그 수준 |

## ⑤ 함정
- SIM 구성요소 `EuiccNoResponse`는 카드가 SW로 답했으면 이름과 달리 채널 경합·거절이다.
- 로그 내내 되풀이되는 6A82 조회는 배경이다(〔script: 같은 형태 N회〕). 가려진 덤프에서 SW를 짐작하지 않는다.
