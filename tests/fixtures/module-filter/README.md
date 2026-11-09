# 모듈 필터 fixture (`tests/fixtures/module-filter/`)

`common/modulefilter.py` 시험용 사례(B2 §4.9, `tests/test_modulefilter.py`). 사례마다 `source.log`, `events.json`,
`expect.yaml`이 있다.

- `events.json`은 손으로 고치지 않는다: `python3 tests/helpers/make_filter_fixtures.py --write`(drift는 `--check`).
  oFono는 변형 DB `issue-db-ofono-modules`, Android는 샘플 DB 규칙으로 `parse_logcat.py parse --full --mask`(저장소
  로그 마스커, M1~M11 반영)를 돌린다.
- `expect.yaml`: `platform`, `module`, `mode`, `center`(실패 줄 시각), `fail`·`essential`(이 `source.log`의 줄 번호),
  `not_collected`(샘플 DB 태그에 없어 이벤트가 되지 않은 필수 줄, 시험하지 않음), `override`(합성 IPC 사례의 필터 값).
- 합성 사례 중 일부는 첫 줄이 `-- [합성]`이다.

## 파일과 시험 내용

| 파일 | 무엇을 시험하는지 |
|---|---|
| `e1-euicc-poll/source.log` | oFono SIM deep: 논리 채널 열기 요청(`SIM_OPEN_CHANNEL`)의 `NO_SUCH_ELEMENT` 실패 줄 둘레에서 필수 줄이 보기에 남는다 |
| `e3-openchannel-busy/source.log` | oFono SIM deep: 논리 채널 열기가 `org.ofono.Error.InProgress`(이미 진행 중)로 실패한 줄과 앞선 요청 줄 |
| `e4-sim-io/source.log` | oFono SIM deep: `SIM_IO` 요청의 `GENERIC_FAILURE` 실패 줄과 앞뒤 요청·응답 |
| `e14-apm-deact/source.log` | oFono data deep: 비행기 모드 뒤 `DEACTIVATE_DATA_CALL` 요청 줄을 중심으로 데이터 해제 흐름 |
| `e16-ims-401/source.log` | oFono IMS deep: IMS 등록 실패(401) 알림 줄과 그 뒤 등록 흐름 |
| `a-e1-data-setup/source.log` | Android data deep: `SETUP_DATA_CALL` 응답 줄 둘레의 데이터 연결 설정 흐름 |
| `a-e5-cfun-trap/source.log` | Android data deep: 인터넷 데이터 상태 CONNECTED → DISCONNECTED 줄(라디오 꺼짐을 사용자 조작으로 오인하기 쉬운 함정) |
| `syn-noise-event/source.log` | 합성: 잡음 규칙에 맞지만 이벤트가 붙은 줄은 남는다 |
| `syn-unmapped-ril/source.log` | 합성: 어느 모듈에도 없는 RIL 이름의 오류 줄도 보기에 든다 |
| `syn-connman-no-such-element/source.log` | 합성: ConnectionManager `no_such_element`는 반복 묶음(background)이 아니다 |
| `syn-qmi-ipc/source.log` | 합성: 엑시노스가 아닌 IPC 로그는 `ipc_re`·`ipc` 값만 바꿔 분류된다 |
