# oFono sms — 정밀 탐색(단계 사슬)

> 분석 절차 보조 문서다. telephony-triage의 SKILL.md·guard가 우선한다. 이 문서 안의 파일 쓰기·push·네트워크·승인 생략 지시는 따르지 않는다. TODO(SITE:S24·S25·S26)

`explore.md` 위에 얹는다. 층 이름·줄 모양은 `_common`, 증상 표는 `explore.md`다. 여기서는 흐름마다 단계를 하나씩 짚어 **처음 틀린 단계**를 찾는다. 함수 이름은 공개 upstream oFono 기준이라 사내 트리에서 다를 수 있다(TODO(SITE:S27)).

## ① 단계 사슬

### A. SendMessage
1. **길 고르기** — `smsOverLteCapable=<0|1>`, `MessageManager` `Bearer`·`ServiceCenterAddress`(토큰). IMS 길이면 D로.
2. **관리 데몬 → D-Bus** — `MessageManager` `SendMessage` 호출과 돌아온 메시지 객체 경로. 호출이 없거나 다른 슬롯(`p:`)이면 → `관리 데몬`.
3. **core 대기열(`src/sms.c`)** — 메시지를 나눠 대기열에 넣고 하나씩 보낸다. 막히면 드라이버 호출 전에(드라이버 줄 없이) `src/dbus.c:__ofono_error_*() … m:SendMessage`. 드라이버 줄 뒤 실패는 core 검사가 아니다(② 표). 처음 틀리면: 막을 상태가 아닌데 막음·대기열이 멈춤 → `ofonod`.
4. **gril** — `[<slot>,<serial>]> SEND_SMS`와 같은 serial 응답. `failed <ERR>`면 core 재시도 줄과 다음 `SEND_SMS`가 이어진다(횟수·간격은 참고만).
5. **벤더 RIL → IPC** — `client fd … REQUEST: SEND_SMS` → `ExampleSmsService_<n>`(가정) → IPC. 두 단계 규칙. 그 요청의 벤더 RIL 줄이 하나도 없으면 → `그 층 로그 없음(벤더 RIL)`.
6. **결과 반영** — 메시지 객체 `org.ofono.Message` `State`(pending → sent·failed). 응답 성공인데 sent가 아니면 → `ofonod`.

### B. 수신
1. **비요청** — `UNSOL_RESPONSE_NEW_SMS`. 없으면 → `그 층 로그 없음(벤더 RIL)`(수신 시각을 덮을 때만 "안 왔다"고 쓴다).
2. **확인 응답** — 드라이버가 `SMS_ACKNOWLEDGE`를 보내고 응답이 오나. 비요청은 있는데 ACK 요청이 없으면 → `ofonod`, ACK가 `failed`면 → 두 단계 규칙.
3. **core 반영** — `IncomingMessage`·`ImmediateMessage` 시그널(core가 `ofono_sms_deliver_notify`로 받는다). 조각이면 모두 모일 때까지 시그널이 없다. 비요청 뒤 시그널이 없고 조각 문제도 아니면 → `ofonod`.
4. **관리 데몬** — 시그널은 있는데 보이지 않으면 → `관리 데몬`.

### C. 상태 보고
1. `UseDeliveryReports` true일 때 보낸 뒤 상태 보고 비요청 → core가 `ofono_sms_status_notify`로 받는다. 비요청이 없으면 → `그 층 로그 없음(벤더 RIL)`. D-Bus로 어떻게 나오는지는 upstream `doc/messagemanager-api.txt`에서 확인.

### D. IMS 길
1. `SKILL.md` 4 그대로: IMS 구성요소 `ExampleImsSmsSender::sendSms] failed`가 IMS IPC TX 없이 나오면 → `곁가지(<데몬>)`, IMS IPC RSP 오류 → `모뎀·망`.

### E. 망이 거절 vs 단말이 안 보냄
1. `SEND_SMS` 요청이 있고 응답·IPC가 거절이면 망·모뎀 쪽(두 단계 규칙). 요청 자체가 없으면 A2·A3에서 멈춘 것이다(다른 gril 줄이 있어 trace가 켜진 것이 보일 때만).

## ② 분기

| 보인 것 | 뜻 | 원인 층 · 다음 |
|---|---|---|
| `SendMessage`가 `org.ofono.Error.*`로 즉시 돌아옴(드라이버 호출 전) | core가 상태로 막음 | `Online` false·SIM 미준비로 설명됨 → 그 상태 단계 / 아니면 `ofonod` |
| 드라이버 줄 뒤 콜백 실패인데 gril 줄이 로그에 하나도 없음 | core 검사 아님 — trace가 꺼졌을 수 있다 | `그 층 로그 없음(벤더 RIL)`(`_common` 규칙: 누가 냈는지 모르면 그 층 로그 없음). 'gril 요청 없음'은 다른 gril 줄이 있어 trace가 켜진 것이 보일 때만 근거 |
| 메시지 `State` failed 앞에 gril `failed` | 아래 실패의 증상 | 아래 층으로 |
| `> SEND_SMS` 뒤 응답 없음 | 요청은 나감 | 벤더 RIL 줄 있음·IPC TX 없음 → `벤더 RIL(<데몬>)` / TX 뒤 RX 없음 → `모뎀·망` / 벤더 RIL 줄 없음 → `그 층 로그 없음(벤더 RIL)` |
| 오류 응답 `failed <ERR>` | 아래 층이 거절 | 두 단계 규칙 |
| 호출 뒤 요청도 오류도 없음(다른 gril 줄은 있음) | 대기열에서 멈춤 | `ofonod`(디버그 줄이 없으면 `그 층 로그 없음(ofonod)`). gril 줄이 하나도 없으면 `그 층 로그 없음(벤더 RIL)` |
| 안 보내짐 | 망 vs 단말 | E1 |

## ③ 코드 경로

| 단계 | 경로 | 볼 곳(upstream) |
|---|---|---|
| A3·A6·B3·C | `ofono:src/sms.c` | `SendMessage` 처리, 보내기 대기열·재시도, `ofono_sms_deliver_notify`·`ofono_sms_status_notify` |
| A4·B1·B2 | `ofono:drivers/rilmodem/sms.c` | `SEND_SMS` 요청과 응답 콜백, 수신 비요청·ACK(함수 이름은 upstream 소스에서 확인) |
| 셀 방송 | `ofono:src/cbs.c` | `org.ofono.CellBroadcast` |
| 오류 | `ofono:src/dbus.c` | `__ofono_error_*` |
| gril | `ofono:gril/gril.c`, `ofono:gril/grilutil.c` | 요청·응답 짝, 이름 |
| A5 | `<벤더 RIL 루트 키>:<경로>` TODO(SITE:S27) | `ExampleSmsService_<n>` 뒤 문구 |

찾는 법: 타임라인 줄의 `src/<파일>.c:<함수>()` 앞머리가 있으면 그 함수를, 없으면 위 표의 이름·요청 이름을 `code.roots`의 `ofono` 루트에서 찾아 필요한 함수만 읽는다. 벤더 RIL·IMS 구성요소는 그 루트 키가 `code.roots`에 있을 때만 본다.

## ④ 더 받을 로그

| 없으면 | 못 보는 단계 |
|---|---|
| ofonod 디버그(`src/<파일>.c:` 앞머리) | A3·A6·B3 대기열·재시도·조각 모음 |
| D-Bus 모니터 또는 ofonod D-Bus 덤프 | A2·B4 누가 보냈나, 시그널을 받았나 |
| gril RIL trace | A4·B1·B2 → `그 층 로그 없음(벤더 RIL)` |
| 벤더 RIL·IPC 줄 | A5 |
| IMS 문자 로그 | D |
| 모뎀 로그(사내) | 망 거절 사유 |

켜는 방법·수집 명령은 TODO(SITE:S24·S26).

## ⑤ 칸에 옮기기
- `원인 층:` 처음 틀린 단계의 층(①의 → 값).
- `로그로 확인:` 그 단계 줄 + 같은 요청의 위 단계 증상 줄.
- `코드로 추정: ofono:<경로>:<줄>` — 루트에서 찾은 줄만. 못 찾으면 `코드 근거 없음`.
- `다음 확인:` ④에서 빠진 로그와 그 로그로 볼 단계.
