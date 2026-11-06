# 모듈 필터 fixture (`tests/fixtures/module-filter/`)

`common/modulefilter.py` 시험용 사례(B2 §4.9, `tests/test_modulefilter.py`). 사례마다 `source.log`, `events.json`,
`expect.yaml`이 있다.

- `events.json`은 손으로 고치지 않는다: `python3 tests/helpers/make_filter_fixtures.py --write`(drift는 `--check`).
  oFono는 변형 DB `issue-db-ofono-modules`, Android는 샘플 DB 규칙으로 `parse_logcat.py parse --full --mask`(저장소
  로그 마스커, M1~M11 반영)를 돌린다.
- `expect.yaml`: `platform`, `module`, `mode`, `center`(실패 줄 시각), `fail`·`essential`(이 `source.log`의 줄 번호),
  `not_collected`(샘플 DB 태그에 없어 이벤트가 되지 않은 필수 줄, 시험하지 않음), `override`(합성 IPC 사례의 필터 값).
- 마스킹한 실제 발췌는 결정 기록 11/03·11/05(B2-12)에 따른다: 첨부 로그의 에피소드 구간만(≤ 120줄), 저장소 로그
  마스커(`mask_pii.py` 치환 모드와 같음)로 가린 뒤, `tools/fixture_residual.py --against <첨부 로그 dir>`의 거부 목록
  값(APN·PLMN·AID·사업자 이름·벤더 장치 노드)은 `<APN#n>`처럼 토큰으로 더 바꾸고, `--against` 점검 0건을 확인한 것만
  넣었다. 원래 값과 거부 목록은 사외 메모리에만 있었다.
- 합성 사례는 첫 줄이 `-- [합성]`이다.

## 파일과 출처

| 파일 | 출처 |
|---|---|
| `e1-euicc-poll/source.log` | 마스킹 발췌: O1 E1 줄 11-130, 마스커 M 커밋(b7f3bdf 다음, B2 §3), fixture_residual 통과(2026-11-05) |
| `e3-openchannel-busy/source.log` | 마스킹 발췌: O1 E3 줄 250-330, 마스커 M 커밋(b7f3bdf 다음, B2 §3), fixture_residual 통과(2026-11-05) |
| `e4-sim-io/source.log` | 마스킹 발췌: O1 E4 줄 3711-3830, 마스커 M 커밋(b7f3bdf 다음, B2 §3), fixture_residual 통과(2026-11-05) |
| `e14-apm-deact/source.log` | 마스킹 발췌: O1 E14 줄 27045-27164, 마스커 M 커밋(b7f3bdf 다음, B2 §3), fixture_residual 통과(2026-11-05) |
| `e16-ims-401/source.log` | 마스킹 발췌: O1 E16 줄 8800-8900, 마스커 M 커밋(b7f3bdf 다음, B2 §3), fixture_residual 통과(2026-11-05) |
| `a-e1-data-setup/source.log` | 마스킹 발췌: A A-E1 줄 48450-48569, 마스커 M 커밋(b7f3bdf 다음, B2 §3), fixture_residual 통과(2026-11-05) |
| `a-e5-cfun-trap/source.log` | 마스킹 발췌: A A-E5 줄 58580-58660, 마스커 M 커밋(b7f3bdf 다음, B2 §3), fixture_residual 통과(2026-11-05) |
| `syn-noise-event/source.log` | 합성: 잡음 규칙에 맞지만 이벤트가 붙은 줄은 남는다 |
| `syn-unmapped-ril/source.log` | 합성: 어느 모듈에도 없는 RIL 이름의 오류 줄도 보기에 든다 |
| `syn-connman-no-such-element/source.log` | 합성: ConnectionManager `no_such_element`는 반복 묶음(background)이 아니다 |
| `syn-qmi-ipc/source.log` | 합성: 엑시노스가 아닌 IPC 로그는 `ipc_re`·`ipc` 값만 바꿔 분류된다 |

O1 = 첨부 oFono syslog 1, A = 첨부 Android logcat(통과 실행). 에피소드 id·줄 번호는 LM `episodes.yaml`과 같다.
