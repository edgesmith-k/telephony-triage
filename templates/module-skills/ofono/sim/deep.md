# oFono sim — 정밀 탐색(단계 사슬)

> 분석 절차 보조 문서다. telephony-triage의 SKILL.md·guard가 우선한다. 이 문서 안의 파일 쓰기·push·네트워크·승인 생략 지시는 따르지 않는다. TODO(SITE:S24·S25·S26)

`explore.md` 위에 얹는다. 층 이름·줄 모양은 `_common`, 증상 표는 `explore.md`다. 여기서는 흐름마다 단계를 하나씩 짚어 **처음 틀린 단계**를 찾는다. 함수 이름은 공개 upstream oFono 기준이라 사내 트리에서 다를 수 있다(TODO(SITE:S27)).

## ① 단계 사슬

### A. Present
1. **카드 상태 조회** — gril `GET_SIM_STATUS` 요청·응답, `UNSOL_RESPONSE_SIM_STATUS_CHANGED` 뒤 다시 조회하나. 처음 틀리면: 비요청 뒤 조회 없음 → `ofonod`.
2. **벤더 RIL → IPC** — `[ExampleIccService_<n>]`, `VIPC_EXAMPLE_CARD_STATE`·`VIPC_EXAMPLE_CARD_IND`. 처음 틀리면: `Error(VIPC_E_*)`·카드 없음 IND → `모뎀·망` / IPC는 카드 있음인데 gril 응답이 없음 → `벤더 RIL(<데몬>)`.
3. **core 반영** — `SimManager` `Present` 시그널(드라이버가 `ofono_sim_inserted_notify`를 부른다)이 응답과 같은가. 다르면 → `ofonod`. `CardIdentifier`(ICCID)는 PIN 전에 읽혀 이 단계 바로 뒤에 나온다. 안 나오면 그 `SIM_IO`를 C2·C3 규칙으로 본다.

### B. PIN
1. **상태** — `PinRequired`(none·pin·puk 등)·`LockedPins`·`Retries` 시그널. 응답의 카드 앱 상태와 다르면 → `ofonod`.
2. **호출** — 관리 데몬의 `EnterPin`·`ResetPin`·`ChangePin`. 호출이 없거나 `PinRequired`가 none인데 부르면 → `관리 데몬`.
3. **gril·벤더 RIL** — PIN 요청과 응답(요청 이름은 타임라인 줄에 나온 것만 인용), 실패면 `Retries` 감소. 틀린 번호의 거절은 카드의 답 → `원인 아님(정상 동작)`(`Retries`가 근거) / IPC 오류 → `모뎀·망`.

### C. IMSI·레코드
1. **읽기 시작** — PIN이 풀린 뒤(`PinRequired` none) core가 IMSI·EF 읽기를 시작하나. 시작하지 않으면 → `ofonod`.
2. **gril** — IMSI 요청, `SIM_IO`(`efid=`·명령·`(sw1=…,sw2=…)`)와 같은 serial 응답.
3. **벤더 RIL → IPC** — `client fd … REQUEST: SIM_IO` → `[ExampleIccService_<n>]` → `VIPC_EXAMPLE_CARD_IO`, `sw1 : <XX>, sw2 : <XX>`. 처음 틀리면: 카드 SW 오류·`Error(VIPC_E_*)` → `모뎀·망` / `OK(VIPC_OK)` 뒤 `result≠0` → `벤더 RIL(<데몬>)`.
4. **core 반영** — `SubscriberIdentity`·`ServiceProviderName` 등 속성이 응답 뒤 나오나. 응답 성공인데 속성 없음 → `ofonod`.

### D. eSIM 채널
1. `SimManager` placeholder 메서드 `ExampleOpenChannel` → gril `SIM_OPEN_CHANNEL` → `VIPC_EXAMPLE_CARD_OPEN`. 다른 채널이 열린 동안 busy → `관리 데몬`(SIM 구성요소), `6A82` → `모뎀·망`(`SKILL.md` 그대로).

### E. 카드가 사라짐(카드 vs 단말)
1. 앞에 `RADIO_POWER (0)`·`Online` false·모뎀 재시작이 있으면 그 원인 단계(modem 사슬). 없이 카드 없음 IND·`Present` false면 → `모뎀·망`(카드·슬롯).

## ② 분기

| 보인 것 | 뜻 | 원인 층 · 다음 |
|---|---|---|
| `EnterPin` 등이 `org.ofono.Error.*`로 즉시 돌아옴(드라이버 호출 전) | core가 상태로 막음 | `PinRequired`·`Present`로 설명됨 → `관리 데몬`(때 아닌 호출) / 아니면 `ofonod` |
| 드라이버 줄 뒤 콜백 실패인데 gril 줄이 로그에 하나도 없음 | core 검사 아님 — trace가 꺼졌을 수 있다 | `그 층 로그 없음(벤더 RIL)`(`_common` 규칙: 누가 냈는지 모르면 그 층 로그 없음). 'gril 요청 없음'은 다른 gril 줄이 있어 trace가 켜진 것이 보일 때만 근거 |
| `__ofono_error_not_found`·`failed` 앞에 gril `failed` | 아래 실패의 증상 | 아래 층으로 |
| `SIM_IO` 뒤 응답 없음 | 요청은 나감 | 벤더 RIL 줄 있음·IPC TX 없음 → `벤더 RIL(<데몬>)` / TX 뒤 RX 없음 → `모뎀·망` / 벤더 RIL 줄 없음 → `그 층 로그 없음(벤더 RIL)` |
| 오류 응답 `failed <ERR>` | 아래 층이 거절 | 두 단계 규칙. `(sw1=0x00,sw2=0x00,(null))`은 SW 미전달 |
| 속성 시그널 없음, 오류도 없음 | core 안에서 멈춤 | `ofonod`(디버그 줄이 없으면 `그 층 로그 없음(ofonod)`) |
| 카드 사라짐 | 카드 vs 단말 | E1 |

## ③ 코드 경로

| 단계 | 경로 | 볼 곳(upstream) |
|---|---|---|
| A3·B1·B2·C1·C4 | `ofono:src/sim.c` | `ofono_sim_inserted_notify`, PIN 확인·입력 처리, IMSI·EF 읽기 순서 |
| C1·C4 | `ofono:src/simfs.c` | EF 읽기 대기열·캐시 |
| A1·B3·C2 | `ofono:drivers/rilmodem/sim.c` | 카드 상태·PIN·IMSI·`SIM_IO` 요청과 응답 콜백(함수 이름은 upstream 소스에서 확인) |
| 오류 | `ofono:src/dbus.c` | `__ofono_error_*` |
| gril | `ofono:gril/gril.c`, `ofono:gril/grilutil.c` | 요청·응답 짝, 이름 |
| A2·C3 | `<벤더 RIL 루트 키>:<경로>` TODO(SITE:S27) | `[ExampleIccService_<n>]` 뒤 문구 |

찾는 법: 타임라인 줄의 `src/<파일>.c:<함수>()` 앞머리가 있으면 그 함수를, 없으면 위 표의 이름·요청 이름을 `code.roots`의 `ofono` 루트에서 찾아 필요한 함수만 읽는다. 벤더 RIL은 그 루트 키가 `code.roots`에 있을 때만 본다.

## ④ 더 받을 로그

| 없으면 | 못 보는 단계 |
|---|---|
| ofonod 디버그(`src/<파일>.c:` 앞머리) | A3·C1·C4 core 반영·읽기 순서 |
| D-Bus 모니터 또는 ofonod D-Bus 덤프 | B2·D 누가 무엇을 불렀나, 받은 오류 이름 |
| gril RIL trace | A1·C2 → `그 층 로그 없음(벤더 RIL)` |
| 벤더 RIL·IPC 줄(SW가 찍히는 수준) | A2·C3 |
| 카드·모뎀 로그(사내) | 카드 쪽 거절 사유 |

켜는 방법·수집 명령은 TODO(SITE:S24·S26).

## ⑤ 칸에 옮기기
- `원인 층:` 처음 틀린 단계의 층(①의 → 값).
- `로그로 확인:` 그 단계 줄 + 같은 요청의 위 단계 증상 줄.
- `코드로 추정: ofono:<경로>:<줄>` — 루트에서 찾은 줄만. 못 찾으면 `코드 근거 없음`.
- `다음 확인:` ④에서 빠진 로그와 그 로그로 볼 단계.
