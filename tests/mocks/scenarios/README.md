# 합성 logcat 시나리오 형식

`tests/mocks/logcat_gen.py`가 읽는다 (`15-local-draft.md §15.2`).
같은 시나리오는 항상 같은 출력을 낸다(난수 없음).

```yaml
name: DATA-001-01            # 기본 파일명 (--name으로 덮어쓸 수 있다)
start: "2026-09-20T14:30:00+09:00"   # 첫 줄의 시각
default_phone: 0             # 슬롯 기본값. null이면 슬롯 표기 없음
phone_prefix: true           # 메시지 앞에 [PHONE<n>] 을 붙인다 (TODO(SITE:S20))
pid: 1234                    # 기본 pid
tid: 1244                    # 기본 tid
build:                       # --bugreport 로 감쌀 때 헤더에 들어간다
  fingerprint: "mock/mocka56/a56:16/MOCKBUILD/MOCKA56_U1_20260915:user/release-keys"
  build: MOCKA56_U1_20260915
expect:                      # 있으면 <name>.expect.yaml 을 함께 쓴다
  expect_top: DATA-001-01    # origin: synthetic 은 생성기가 항상 더한다
entries:
  - {at: 0,     tag: "DSM-{phone}", msg: "..."}
  - {after: 2,  tag: "DNC-{phone}", msg: "...", level: W}
  - {after: 1,  ril_request: SETUP_DATA_CALL, serial: 41, args: "apn=<APN>"}
  - {after: 0.8, ril_response: SETUP_DATA_CALL, serial: 41, result: "error=OP_NOT_ALLOWED"}
  - {after: 1,  ril_unsol: UNSOL_DATA_CALL_LIST_CHANGED, args: "[]"}
  - {after: 5,  tag: "DNC-{phone}", msg: "...", phone: 1}        # 다른 슬롯
  - {after: 1,  tag: RILJ, msg: "...", clock_jump_sec: -8}       # 시계 이상
  - {after: 1,  tag: "DRM-{phone}", msg: "재시도 {i}", repeat: 3, every: 2}
```

| 필드 | 뜻 |
|---|---|
| `at` | 시작 시각으로부터 몇 초 (절대) |
| `after` | 앞 항목으로부터 몇 초 (상대) |
| `tag`, `msg` | 태그와 메시지. `{phone}`, `{serial}`을 치환한다 |
| `level` | `V D I W E F` (기본 `D`) |
| `phone` | 슬롯. `null`이면 슬롯 없음 (`phone_id: null` 이벤트) |
| `phone_prefix` | 이 항목만 메시지 접두어를 끈다 |
| `buffer` | `main radio system crash events`. 없으면 태그로 정한다 |
| `pid`, `tid` | 프로세스/스레드 id (RIL 페어링 키에 들어간다) |
| `clock_jump_sec` | 이 항목부터 시각이 튄다. 음수면 뒤로 간다 |
| `repeat`, `every` | 같은 항목을 N번, `every`초 간격으로. `msg`의 `{i}`는 1부터 |
| `ril_request` / `ril_response` / `ril_unsol` | RILJ 줄을 만든다. `serial`, `args`, `result` |

## 확정된 것과 placeholder

- **데이터 스택 태그는 확정 형식**이다: `DNC-<n>`, `DN-…`, `DPM-<n>`,
  `DRM-<n>`, `DSM-<n>`, `DCM-<n>`, `DSRM-<n>` (Android 13+).
  레거시 데이터 스택(DcTracker/DCT)은 쓰지 않는다.
- 그 밖의 태그, 로그 문구, RIL 출력 형식(`[0041]> NAME`), 슬롯 메시지 접두어
  (`[PHONE0]`), bugreport 섹션 헤더는 **placeholder**다.
  사내에서 S7·S9·S20·S21로 확인하고 바꾼다 (`14-site.md §14.2`).

## 만들어 둔 시나리오

합성 샘플 이슈 DB의 fixture와 파서 fixture(`tests/fixtures/logs/`, 목록 `tests/mocks/log_fixtures.yaml`)는 아래 시나리오에서 나온다. 어느 시나리오가 어느
fixture가 되는지는 `tests/mocks/sample_fixtures.yaml`에 있고,
`tests/helpers/make_sample_fixtures.py`가 생성·검사한다 (`11-phases.md` Phase 1).

| 파일 | 쓰임 | fixture |
|---|---|---|
| `data-001-01-positive.yaml` | DATA-001-01(데이터 설정 꺼짐) 양성. 슬롯 0 | `DATA-001-01.log` |
| `data-001-02-roaming.yaml` | DATA-001-02(로밍 꺼짐) 양성. 슬롯 1 | `DATA-001-02.log` |
| `data-001-02-extra.yaml` | DATA-001-02 추가 표본 | `DATA-001-02.extra.1.log` |
| `data-001-none.yaml` | 음성(정상 데이터 연결) | `DATA-001.none.log` |
| `data-001-none-cross-slot.yaml` | **교차 슬롯 음성**: 슬롯 1의 설정 OFF → 슬롯 0의 거부 → 슬롯 0 정상 연결. `same_phone`(false 사본에서는 원인 충족)과 `must_not_match`를 함께 시험한다 | `DATA-001.none.2.log`, 파서 `dual-sim-cross-slot.log` |
| `call-001-01-positive.yaml` | CALL-001-01(VoLTE 실패) 양성. IMS 등록 실패도 있어 `also_allowed` 예시가 된다 | `CALL-001-01.log` |
| `call-001-01-fixed.yaml` | 수정 빌드에서 정상 (verify-fix 통과) | `CALL-001-01.fixed.<build>.log` |
| `call-001-01-resolved.yaml` | 해결책 적용 후 정상 | `CALL-001-01.resolved.1.log` |
| `call-001-none.yaml` | 음성(정상 VoLTE 통화, 발신 시도 있음) | `CALL-001.none.log` |
| `call-001-none-2.yaml` | 음성(IMS 등록만, 발신 시도 없음). 흔적 시그니처가 음성 fixture **전부**에서 충족되지 않게 한다 | `CALL-001.none.2.log` |
| `network-001-01-positive.yaml` | NETWORK-001-01(등록 거절) 양성 | `NETWORK-001-01.log` |
| `network-001-none.yaml` | 음성(정상 등록) | `NETWORK-001.none.log` |
| `sim-001-01-positive.yaml` | SIM-001-01(UICC 초기화 실패) 양성. 슬롯 1 | `SIM-001-01.log` |
| `sim-001-none.yaml` | 음성(정상 SIM 인식) | `SIM-001.none.log` |
| `sim-001-none-2.yaml` | 음성(SIM 상태 조회 없음) | `SIM-001.none.2.log` |
| `sms-001-01-positive.yaml` | SMS-001-01(SMSC 주소 없음) 양성 | `SMS-001-01.log` |
| `sms-001-none.yaml` | 음성(정상 전송) | `SMS-001.none.log` |
| `ims-001-01-positive.yaml` | IMS-001-01(403 거절) 양성 | `IMS-001-01.log` |
| `ims-001-01-recurrence.yaml` | 수정 빌드에서 재발 (verify-fix 실패) | `IMS-001-01.recurrence.<build>.log` |
| `ims-001-none.yaml` | 음성(정상 IMS 등록) | `IMS-001.none.log` |
| `data-setup-error.yaml` | SETUP_DATA_CALL 에러 응답 (`ril_error`) | 파서 `data-setup-error.log` |
| `call-drop.yaml` | 연결된 VoLTE 통화 끊김 | 파서 `call-drop.log` |
| `sim-absent.yaml` | SIM 없음 (슬롯 1) | 파서 `sim-absent.log` |
| `dual-sim-ril.yaml` | 같은 serial을 두 슬롯이 씀, 지연(`ril_timeout`), 응답 없음(`ril_no_response`), pid 변경, 슬롯 없는 줄 | 파서 `dual-sim-ril.log` |
| `clock-anomaly.yaml` | 시계 역행(-8초)·점프(+2시간, 판정 기준 3600초 이상) (`coverage.clock_anomalies` 시험) | 파서 `clock-anomaly.log` |
| `bugreport-wrap.yaml` | `--bugreport txt|zip` 래핑과 `extract-bugreport` 시험 (system·radio·main·events 버퍼 + 가짜 dumpsys) | — |
