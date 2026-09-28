# DRAFT_NOTES — 사외 초안 진행 기록

> 사외 초안 모드의 진행 상태·가정·실험 결과를 적는 파일이다
> (`docs/design/15-local-draft.md §15.1`). 사내 Claude Code가 설계 문서를 다시
> 다 읽지 않고도 초안 상태를 파악하게 하는 것이 목적이다.
> 이 파일은 **반입 때 사내로 같이 간다**. `.local-draft`는 가지 않는다.

## 진행 상태

- 모드: **사외 초안** (`.local-draft` 있음)
- 완료 Phase: **D0, 1** (2026-09-28), **2, 3** (2026-09-29)
- 다음 Phase: **4** (마스킹)
- Phase 2~6은 사용자가 미리 승인해서 Phase마다 확인을 기다리지 않고 진행한다(각 Phase 끝에 커밋·push). 완료 기준 점검 결과는 Phase별 절에 적는다.
- 기준 문서 세트: `telephony-triage-docs-v11` (`CHANGES.md` 참고)
- 레포 루트: 이 파일이 있는 디렉토리 (`CLAUDE.md`, `docs/design/`, `plugin/`,
  `tests/`, `tools/`가 같이 있다)

### Phase D0에서 만든 것

| 산출물 | 경로 |
|---|---|
| 모의 Jira MCP (`mock-jira`, 비표준 도구 이름) | `tests/mocks/jira_mcp/server.py`, 데이터 `tests/mocks/jira/*.yaml` |
| MCP 등록 (레포 루트 `.mcp.json` 아님) | `tests/mocks/mcp.json` |
| 모의 원격 + `gh` 스텁 | `tests/helpers/make_repo.py`, `tests/mocks/bin/gh`(+`gh_stub.py`), 상태 `tests/mocks/gh-state/` |
| 합성 logcat 생성기 | `tests/mocks/logcat_gen.py`, 시나리오 `tests/mocks/scenarios/` |
| 모의 소스 트리 | `tests/mocks/src/android16`, `android17` |
| 가상 빌드명·`build_compare` | `tests/mocks/builds.yaml` |
| 모의 site 파서 백엔드 (`builtin.data.*`) | `tests/mocks/parser_backends/site/` |
| 어댑터 예시 | `tests/mocks/adapters/site_data_existing.py` |
| 골든 테스트 틀 + 모의 골든 | `tests/test_golden.py`, `tests/mocks/golden/` |
| 모의 분석 스킬 | `tests/mocks/skills/data-analyzer/` |
| 빈 플러그인 실험 | `tests/mocks/plugin-probe/` |
| 테스트 헬퍼 플러그인 루트 | `tests/helpers/make_plugin_root.py` |
| 모의 환경 PATH 헬퍼 | `tests/helpers/mock_env.py` |
| 사내 기본값 example | `plugin/site-defaults.example.yaml` |
| `site-defaults` 로드와 종료 코드 2 | `plugin/scripts/common/site_defaults.py`, `plugin/scripts/config.py` |
| `sanitize_build` | `plugin/scripts/common/buildname.py` |
| `.githooks` 스텁 (실행 비트 확인용) | `tests/fixtures/issue-db-sample/.githooks/` |
| SITE_PATHS·재반입·기준선 | `SITE_PATHS`, `tools/import_draft.py` (기준선 `.draft-manifest.json`은 사내에서 생긴다) |
| TODO(SITE) 추출 | `tools/list_site_todos.py` |
| 실행 비트 보정 | `tools/fix_exec_bits.py` |
| 줄바꿈 고정 (LF) | `.gitattributes` |
| 모드 표식 | `.local-draft` (`.gitignore` 등록) |

### D0 완료 기준 확인 결과

`python3 tests/test_mocks.py` (또는 `pytest tests`) — **18개 전부 통과**.

| 완료 기준 | 확인 | 어디서 |
|---|---|---|
| 모의 Jira MCP에서 이슈 읽기 | ✅ | `test_mock_jira_mcp_reads_issue` |
| 모의 원격 push + `gh pr create` | ✅ | `test_mock_remote_push_and_pr` |
| 합성 logcat 생성 (슬롯·시계 이상·bugreport) | ✅ | `test_logcat_generation_*`, `test_bugreport_wrapping` |
| 모의 소스 트리 심볼 검색 (16/17 경로 차이) | ✅ | `test_mock_source_tree_symbol_search` |
| 헬퍼 루트에 `site-defaults.yaml` 있음 / `plugin/`에 없음 | ✅ | `test_plugin_root_helper_and_missing_site_defaults` |
| `plugin/`을 직접 주면 `config.py` 종료 코드 2 | ✅ | 같은 테스트 |
| `.githooks` 스텁이 100755로 커밋 | ✅ | `test_githook_stubs_committed_as_100755` |
| 레포 루트에 `.mcp.json` 없음 | ✅ | `test_no_mcp_json_at_repo_root` |
| `import_draft.py` 두 번 반입 (SITE_PATHS 보존·삭제·유지·멈춤) | ✅ | `tests/test_import_draft.py` |
| 골든 테스트 틀 동작 | ✅ | `tests/test_golden.py` |

### Phase 1에서 만든 것

합성 샘플 이슈 DB `tests/fixtures/issue-db-sample/` (운영 이슈 DB와 같은 모양).

| 산출물 | 경로 |
|---|---|
| 설정 | `issue-db.config.yaml` (schema_version 1, generator_version 1, `external_parsers: {}`, `parser_backend: reference`, `matcher.pattern_timeout_ms`), `.gitignore`, `.gitattributes` |
| 스키마 6종 | `schema/{type,jira,feedback,plan,parser-rules,expect}.schema.json` |
| 템플릿 3종 | `templates/{type.md,cause.yaml,jira.yaml}` |
| 파서 규칙 | `parser-rules/{tags,ril,extractors}.yaml` (extractor 14개, 전부 placeholder 문구) |
| 협업 | `.github/CODEOWNERS`, `.github/pull_request_template.md`, `CONTRIBUTING.md`, `GLOSSARY.md`, `docs/{getting-started,review-guide,branch-protection}.md` |
| 유형 6개 | `data/DATA-001-no-setup-data-call`(원인 2), `call/CALL-001-volte-not-working`, `network/NETWORK-001-no-service`, `sim/SIM-001-sim-not-detected`, `sms/SMS-001-sms-send-failed`, `ims/IMS-001-ims-registration-failed` |
| Jira 기록 9건 | `MOCK-1101~1104`(DATA, 하나는 `unresolved`), `MOCK-2101`, `MOCK-3101`, `MOCK-4101`, `MOCK-5101`, `MOCK-6101` |
| 피드백 3건 | `feedback/2026-09/` (`accepted`, `unresolved`, `manual`) |
| fixture 20개 | 양성 6, 음성 9, `fixed` 1, `resolved` 1, `recurrence` 1, `extra` 1 + 각 `.expect.yaml`(`origin: synthetic`) |
| fixture 생성 | 시나리오 20개(`tests/mocks/scenarios/`), 목록 `tests/mocks/sample_fixtures.yaml`, 생성·검사 `tests/helpers/make_sample_fixtures.py` |
| 샘플 작업 계획 3개 | `tests/fixtures/plans/*.plan.json` (analyze / record(pending) / review) — `plan.schema.json` 검사용 |
| 운영용 뼈대 | `tools/make_db_skeleton.py` |
| Phase 1 테스트 | `tests/test_sample_db.py` (19개) |
| fixture 안내 | `tests/fixtures/README.md` (샘플 트리 안의 D0 자리표시 README는 지웠다 — 그 이름은 생성 파일이다) |

샘플이 일부러 담고 있는 상태 (뒤 Phase의 시험 대상)

- `DATA-001-01`: `sequence` + `same_phone` 시그니처, 해결책 `verified`(근거 Jira `MOCK-1102`), Android 16/17 경로가 다른 `code_refs`
- `DATA-001-02`: `android_versions: []`(전 버전), 해결책 `unverified`
- `CALL-001-01`: `fix.status: fixed` + `verification` + `verification_history`(`partial`), `scenario_signatures`·`recovery_signatures`, `related: [IMS-001-01]`(양방향), 해결책 `verified`(근거 `resolved` fixture)
- `CALL-001-01.expect.yaml`: `also_allowed: [IMS-001-01]` (같은 로그에 IMS 등록 실패도 실제로 있다)
- `NETWORK-001-01`: `cp_evidence` 예시, `resolution_type: network`
- `SIM-001-01`: `fix.status: fix-submitted`(+`ref`·`fixed_in` 빌드), `scenario_signatures`
- `SMS-001-01`: `fix.status: wont-fix`(본문에 사유)
- `IMS-001-01`: `verify-fix` 실패로 `open`으로 되돌아온 이력(`verification_history`의 `failed` + 그때의 `ref`·`fixed_in`)과 `recurrence` fixture. 코드 수정 유형인데 흔적 시그니처가 없어 월간 리뷰 "fixed 전환 불가" 대상이다
- 음성 fixture는 카테고리마다 두 개인 곳이 있다(call, sim, data). 흔적 시그니처가 **그 카테고리 음성 fixture 전부에서** 충족되면 R1이 실패해야 하기 때문이다 (`05-verification.md §5.12 (1)`)

### Phase 1 완료 기준 확인 결과

`python3 tests/test_sample_db.py` — **19개 전부 통과** (`pytest tests` 전체 37개 통과).

| 완료 기준 | 확인 | 어디서 |
|---|---|---|
| 샘플이 모든 JSON 스키마를 통과 | ✅ | `test_type_frontmatter_validates`, `test_jira_records_validate`, `test_feedback_records_validate`, `test_expect_files_validate`, `test_parser_rules_validate`, `test_sample_plans_validate` |
| 스키마 6종이 유효한 JSON Schema | ✅ | `test_schemas_are_valid_json_schema` |
| 파일 배치가 `03-issue-db.md §5.2`와 같음 | ✅ | `test_sample_tree_layout`, `test_no_generated_files_committed` |
| fixture 이름이 `contracts.md §fixture`와 같음 | ✅ | `test_fixture_names_match_contract` |
| 원인마다 양성 fixture 있음 | ✅ | `test_every_active_cause_has_positive_fixture` |
| fixture가 시나리오에서 결정적으로 재생성됨 | ✅ | `test_fixtures_match_scenarios` |
| ID·참조 정합(접두어·순서·related 양방향·Jira cause·evidence·also_allowed) | ✅ | `test_ids_and_category_prefixes`, `test_related_is_bidirectional`, `test_jira_cause_exists`, `test_verification_references_exist`, `test_also_allowed_targets_other_types`, `test_signature_references_exist_in_parser_rules` |
| 뼈대에 유형·Jira·fixture·피드백이 없고 스키마 통과 | ✅ | `test_skeleton_has_no_types_and_validates` |
| placeholder 목록 보고 | ✅ | 아래 "사내 확인 목록" |

### Phase 1에서 바꾼 D0 산출물

| 대상 | 무엇을 | 왜 |
|---|---|---|
| `tests/mocks/scenarios/data-001-none-cross-slot.yaml` | 슬롯 배치를 바꿨다: 슬롯 0에 거부 로그 + 곧 이어지는 정상 연결, 슬롯 1에 설정 OFF | D0 원본은 슬롯 1 하나에 원인 로그가 다 모여 있어 그 슬롯만으로 `DATA-001-01`이 충족됐다(양성이지 음성이 아니다). 지금 배치는 원인 시그니처의 `same_phone`(슬롯 0의 거부 + 슬롯 1의 설정 OFF로 충족되면 안 됨)과 증상의 `must_not_match`(같은 윈도우의 `SETUP_DATA_CALL`)를 함께 시험하고 `expect_top: none`이 성립한다 |
| `tests/mocks/golden/data-001-none-cross-slot.golden.json` | `tests/test_golden.py --update`로 갱신 | 위 시나리오 변경 반영 (모의 골든이다. 사내 진짜 골든은 사용자 승인 없이 갱신하지 않는다) |
| `tests/test_mocks.py::test_logcat_generation_slots_and_clock` | 슬롯 혼재 확인을 `DNC-0`+`DSM-1`로 | 같은 이유 |
| `tests/mocks/scenarios/call-001-01-positive.yaml` | `expect`에 `also_allowed: [IMS-001-01]` 추가 | 그 로그에 IMS 등록 실패도 실제로 있다 (`contracts.md §fixture`) |
| `tests/fixtures/issue-db-sample/README.md` | 지우고 `tests/fixtures/README.md`로 옮김 | 샘플 트리는 운영 이슈 DB와 같은 모양이어야 하고, 루트 `README.md`는 `db_build.py`가 만드는 생성 파일 이름이다 |

### Phase 2에서 만든 것

| 산출물 | 경로 |
|---|---|
| 파서 백엔드 인터페이스 | `plugin/scripts/parser_backends/base.py` (`parse`, `builtin_events`, `version`, 기본 구현 있는 `coverage`) |
| 백엔드 로더 | `plugin/scripts/parser_backends/__init__.py` (`load(name)` → `parser_backends.<name>.BACKEND`) |
| 공통 처리: 줄 형식·시각·슬롯 | `plugin/scripts/parser_backends/logcat.py` (threadtime / `-v year` / `-v uid` / `-v zone` / `time`, `--tz`/`--year` → UTC, 12→1월 연도 넘김, `phone_id`, `coverage`·시계 이상) |
| 공통 처리: RIL | `plugin/scripts/parser_backends/ril.py` (요청·응답·unsol 해석, 키 `(pid, phone_id, serial)` 페어링) |
| reference 백엔드 | `plugin/scripts/parser_backends/reference/` (builtin 없음, `detect()` 훅) |
| 진입점 | `plugin/scripts/parse_logcat.py` (`parse`, `extract-bugreport`, `cut`은 Phase 4 자리) |
| 규칙 로드·검증 | `plugin/scripts/common/parser_rules.py` |
| 고정 버전 비교 | `plugin/scripts/common/compat.py` (Phase 6 `config.py check`도 쓴다) |
| YAML 읽기(날짜 → 문자열) | `plugin/scripts/common/yamlio.py` (Phase 5 `db_lint`도 쓴다) |
| 마스킹 자리 | `plugin/scripts/common/masking.py` (`new_masker()`가 Phase 4 전까지 `MaskingNotReady`) |
| 브랜치 이름 검사 | `plugin/scripts/common/buildname.py`의 `is_valid_branch_name` (`git check-ref-format --branch`) |
| 어댑터 계약·로더 | `plugin/scripts/adapters/base.py`, `plugin/scripts/adapters/__init__.py` |
| 모의 기존 파서 | `tests/mocks/adapters/legacy_data_parser.py` (테스트가 `site_vendor/legacy_parser.py`로 복사) |
| 새 시나리오 4개 | `tests/mocks/scenarios/{data-setup-error,call-drop,sim-absent,dual-sim-ril}.yaml` |
| 파서 fixture | `tests/fixtures/logs/<name>.log` 12개 + `<name>.events.json` 스냅샷. 목록 `tests/mocks/log_fixtures.yaml`, 생성 `tests/helpers/make_log_fixtures.py [--check]` |
| Phase 2 테스트 | `tests/test_parse_logcat.py` (23개, `--update`로 스냅샷 갱신) |

### Phase 2 완료 기준 확인 결과

`python3 tests/test_parse_logcat.py` — **23개 전부 통과**. `python3 -m pytest tests` 전체 **61개 통과**.

| 완료 기준 | 확인 | 어디서 |
|---|---|---|
| fixture별 이벤트 JSON 스냅샷 (정상 데이터 연결, SETUP 없음+DATA_DISABLED/ROAMING_DISABLED, SETUP 에러 응답, call drop, 서비스 없음, SIM absent, SMS 전송 실패, IMS 등록 실패) | ✅ | `test_event_snapshots`, `test_log_fixtures_match_scenarios` |
| 연도 없는 threadtime + `--tz`/`--year` → UTC 기대값 | ✅ | `test_threadtime_without_year_converts_to_utc`, `test_format_variants` |
| 듀얼 SIM에서 `phone_id`가 슬롯별, 접미사 없는 태그는 `null` | ✅ | `test_phone_id_per_slot` |
| 같은 serial을 두 슬롯이 쓰는 로그에서 슬롯별 페어링 | ✅ | `test_ril_pairing_same_serial_two_slots` (+ pid 변경, 지연·무응답·에러) |
| 발생 시각이 파일 범위 밖 → `window_in_range: false` | ✅ | `test_window_in_range_values` (true / partial / false) |
| 시각 역행 로그에서 `clock_anomalies` | ✅ | `test_clock_anomalies` |
| bugreport(zip·txt) → logcat 섹션만, dumpsys 문자열 없음, `build.json` fingerprint | ✅ | `test_extract_bugreport_txt_and_zip` |
| `parser-rules/`만 바꿔도 결과가 바뀜 | ✅ | `test_rules_change_changes_output_without_code_change` |
| 규칙 스키마 검증 | ✅ | `test_rules_are_validated` |
| 모의 site 백엔드 → `builtin.data.*`가 extractor 이벤트와 함께(source 구분) | ✅ | `test_site_backend_builtin_events_with_extractors` |
| extractor의 `builtin.`/`ext.` 접두어 거부 | ✅ | `test_rules_are_validated` |
| 백엔드 이름·버전이 이슈 DB `parser_backend`와 다르면 경고 | ✅ | `test_site_backend_builtin_events_with_extractors`, `test_backend_version_mismatch_warns` |
| 이슈 DB `external_parsers` 카테고리의 어댑터가 없거나 버전이 낮으면 경고 | ✅ | `test_external_parser_pin_mismatch_warns` |
| 어댑터 실행, `${CLAUDE_PLUGIN_ROOT}` 치환, `--no-external`, merge/replace | ✅ | `test_external_parser_merge_and_no_external`, `test_external_parser_replace_mode` |
| `sanitize_build`가 `A..B`, `X.lock`, 끝 `.`을 유효한 브랜치 이름으로 | ✅ | `test_sanitize_build_and_branch_names` |
| `tests/test_golden.py`가 모의 골든으로 통과, 골든을 바꾸면 실패 | ✅ | `test_golden_matches`, `test_golden_detects_change` |
| `--mask`·`cut`은 인터페이스만 (Phase 4) | ✅ | `test_mask_and_cut_are_phase4`, `test_masking_runs_before_extractors`(마스킹이 extractor보다 앞) |
| `site-defaults.yaml` 없으면 종료 코드 2 | ✅ | `test_site_defaults_required` |

### Phase 2에서 바꾼 이전 산출물

| 대상 | 무엇을 | 왜 |
|---|---|---|
| `tests/mocks/parser_backends/site/__init__.py` | 자체 파싱을 버리고 `ReferenceBackend` 상속 + `detect()`만. `BACKEND` 객체 제공. 버전 `0.0.2-mock` | D0 가정 8 (Phase 2에서 `base.py` 상속). 시각이 UTC가 되고 `ril` 필드가 생겼다 |
| `tests/mocks/parser_backends/__init__.py` | 지움 | `tests/mocks`가 `sys.path`에 있으면 이 패키지가 `plugin/scripts/parser_backends`를 가렸다. 지금은 네임스페이스 디렉토리라 정식 패키지가 이긴다 |
| `tests/mocks/golden/*.golden.json` | `tests/test_golden.py --update` | 모의 백엔드 출력 형식 변경 반영 (모의 골든이다. 사내 진짜 골든은 사용자 승인 없이 갱신하지 않는다) |
| `tests/test_golden.py` | 모의 site 백엔드를 `parser_backends.site`로 불러 `BACKEND`를 쓴다. `test_golden_detects_change` 추가 | 위와 같음, Phase 2 완료 기준 |
| `tests/mocks/scenarios/clock-anomaly.yaml` | 앞으로 뛰는 시각 120초 → 7200초 | 점프 판정 기준(3600초, 가정 14) 이상이어야 시험이 된다 |
| `tests/mocks/scenarios/bugreport-wrap.yaml` | system 버퍼 줄 하나 추가 | `extract-bugreport`가 system·radio·main을 모두 꺼내는지 시험 |
| `tests/mocks/adapters/site_data_existing.py` | 문서만(계약 위치, 매핑 안 된 판별 처리) | 어댑터 계약을 `plugin/scripts/adapters/base.py`로 고정 |
| `plugin/site-defaults.example.yaml` | 없는 `tests/mocks/adapters/README.md` 참조를 `adapters/base.py`로 | 끊긴 참조 |

### 구현에서 정한 세부 (계약 보완 후보 — 설계 문서에는 아직 없다)

사용자 확인 없이 설계 문서(`contracts.md` 등)는 고치지 않았다. 아래는 구현이 정한 것이고, Phase 3 이후가 이것에 기대므로 사내 보완(S-1) 때 계약에 옮길지 정한다.

- **`parse` 출력 머리**: `{schema: 1, backend: {name, version}, external: [{category, adapter, version, mode}], external_disabled, rules: {path, tags, requests, unsolicited, extractors}, input: {files, tz, year, mode, window}, coverage, masked, warnings: [{code, message}], events}`. 항상 JSON을 stdout으로 낸다(`--json`은 받기만 한다). 경고는 stderr에도 한 줄씩.
- **레코드 종류**: 로그 한 줄은 `event: null`인 **줄 레코드**, extractor·builtin·RIL 파생·외부 파서 이벤트는 **별도 레코드**(같은 `ts`·`tag`·`msg`, `ril: null`). 파생 레코드는 그 줄 바로 뒤에 온다. 매처(Phase 3)의 `must_match`는 줄 레코드에만 적용한다.
- **`ril` 필드**: `{serial, dir: req|resp|unsol, request, error, paired_ts, latency_ms}`. 응답에 에러 표기가 없으면 `error: "NONE"`.
- **RIL 파생 이벤트**(`source: rules`, 엔진 예약 이름 — extractor가 쓸 수 없다): `ril_error {request, serial, error}`, `ril_timeout {request, serial, latency_ms, timeout_ms}`(응답 시각), `ril_no_response {request, serial, timeout_ms}`(요청 시각, 파일이 요청+timeout 이후까지 있을 때만). `ril.yaml`의 `requests`에 있는 요청만 만든다. `fields` 값은 모두 문자열이다.
- **태그 필터**: `tags.yaml`에 없는 태그의 줄 레코드는 버린다. `category_hint`는 태그 카테고리, RIL 줄은 `ril.yaml`의 요청/unsol 카테고리가 우선한다. builtin·외부 파서 레코드는 필터하지 않는다.
- **외부 파서**: 로그 파일마다 한 번 실행(`{log}` 치환). `event`가 `ext.<category>.`로 시작하지 않거나 시각을 모르면 버리고 경고. `merge`는 이름 없는 레코드를 버리고, `replace`는 백엔드의 그 카테고리 레코드를 빼고 외부 레코드(이름 없는 줄 포함)를 쓴다. 실행 실패는 경고(`external-parser-failed`) 후 계속. 이슈 DB 고정 버전 비교는 site-defaults의 `version`(없으면 어댑터 `VERSION`).
- **경고 코드**: `tz_assumed_utc`, `year_assumed`, `unparsed-lines`, `no-lines-parsed`, `parser-backend-mismatch`, `external-parser-mismatch`, `external-parser-failed`.
- **`extract-bugreport` 출력**: `{files: [{buffer, path, lines}], build_json, build: {build, fingerprint}, warnings}`. 섹션을 하나도 못 찾으면 종료 코드 2(S21 안내). bugreport를 `parse`에 바로 넣으면 종료 코드 2로 `extract-bugreport`를 안내한다.
- **규칙 스키마 위치**: `--rules <db>/parser-rules`의 상위 `<db>/schema/parser-rules.schema.json`. 고정값은 `<db>/issue-db.config.yaml`.
- **extractor**: 태그가 맞으면 패턴을 순서대로 `search`하고 첫 매치만 쓴다. `fields`에 적힌 그룹 중 값이 있는 것만 넣는다. `fields`가 패턴의 이름 있는 그룹에 없으면 규칙 오류. 패턴 실행 시간 상한(`matcher.pattern_timeout_ms`)은 Phase 3의 컴파일 함수와 함께 넣는다.

### Phase 3에서 만든 것

| 산출물 | 경로 |
|---|---|
| 매처 | `plugin/scripts/match_signatures.py` (분석 모드 2단계 / `--regress`, 점수·신뢰도·bonus·피드백 가중치, 수정 상태 판단, related, `pending_causes`) |
| 시그니처 컴파일·평가 | `plugin/scripts/common/signatures.py` (`compile_signature`, `Evaluator`: 윈도우·`same_phone`·`sequence`·`must_not_match`) |
| 이슈 DB 읽기 | `plugin/scripts/common/issuedb.py` (설정·유형 frontmatter·원인·Jira 건수·피드백, 수락률 `acceptance`) |
| 정규식 시간 상한 | `plugin/scripts/common/patterns.py` (`PatternRunner`: 작업 프로세스에서 패턴 실행, 상한을 넘기면 프로세스를 끝내고 `PatternTimeout`) |
| 빌드 비교 | `plugin/scripts/common/builds.py` (`build_compare`, 같은 브랜치 접두어끼리만 비교) |
| `--db` 기본값 | `plugin/scripts/common/dbpath.py` (① `--db` ② cwd git toplevel ③ 사용자 config는 Phase 6에서 연결) |
| Phase 3 테스트 | `tests/test_match_signatures.py` (17개) |

### Phase 3 완료 기준 확인 결과

`python3 tests/test_match_signatures.py` — **17개 전부 통과**. `python3 -m pytest tests` 전체 **79개 통과**.
테스트 입력 이벤트는 `parse` 출력에 `masked: true`를 붙인 테스트 데이터다(완료 기준 문구대로).

| 완료 기준 | 확인 | 어디서 |
|---|---|---|
| "없음 + DATA_DISABLED" → `DATA-001 > DATA-001-01` 1위, medium 이상 | ✅ (high, 1.0) | `test_data_disabled_is_top_candidate` |
| 원인 로그를 지운 fixture → "DATA-001, 원인 미확인" | ✅ | `test_cause_log_removed_gives_unresolved_type` |
| 음성 fixture → S=1 유형 없음 | ✅ (샘플 음성 fixture 전부, 두 모드) | `test_negative_fixtures_have_no_symptom` |
| 증상 없이 원인 시그니처만 → 분석 모드 후보 없음, `--regress` C=1(0.6 참고), `cause_weight` 0.5여도 S/C 같음 | ✅ | `test_cause_without_symptom_only_in_regress` |
| CALL-001에 fixed_in 이전/같은/이후 SW → 이미 수정됨/회귀 의심/회귀 의심 | ✅ (+ 다른 브랜치·빌드 없음 → 판단 불가, open → 미수정 N건, fix-submitted 두 경우) | `test_fix_judgement_against_fixed_in`, `test_fix_submitted_judgement` |
| `deprecated` 원인은 후보에 없음, `signatures_pending` 원인은 `pending_causes`로만 | ✅ | `test_status_filter_and_pending_causes` |
| `--regress`면 bonus 0, 피드백 가중치 끔, 범위 = 파일 전체 | ✅ (+ 수락률 가중치·`--no-feedback-weight`, `manual` 제외) | `test_regress_mode_disables_bonus_and_feedback`, `test_manual_feedback_is_not_counted` |
| 교차 슬롯 fixture → DATA-001-01 C=0, `same_phone: false` 사본에서 C=1 | ✅ (아래 해석 참고) | `test_cross_slot_same_phone`, `test_symptom_must_not_match_is_per_slot` |
| `sequence` 시그니처는 순서를 뒤집은 로그에서 C=0 | ✅ | `test_sequence_order_matters`, `test_window_sec_limits_span` |
| 느린 정규식은 타임아웃으로 `error`, 다른 후보는 그대로 | ✅ (매처·extractor 둘 다) | `test_slow_regex_times_out_and_others_continue`, `test_parse_logcat.py::test_slow_extractor_times_out_and_others_continue` |
| 마스킹 안 된 입력 거부 | ✅ 종료 코드 2 | `test_unmasked_input_is_rejected` |

**완료 기준 해석 (교차 슬롯)**: 기준 문구는 "분석 모드에서 DATA-001-01 C=0, `same_phone: false` 사본에서는 C=1"이다. 교차 슬롯 로그는 음성이라 DATA-001의 S=0이고, 분석 모드는 S=1 유형의 원인만 평가하므로 사본에서도 분석 모드로는 C가 나오지 않는다. 그래서 분석 모드에서는 "DATA-001-01이 후보에 없음"을, C 값 비교(원본 C=0 / `same_phone: false` 사본 C=1)는 원인을 독립 평가하는 `--regress`로 확인했다. 원인 시그니처의 `same_phone`이 실제로 슬롯을 가르는지는 이것으로 드러난다.

### Phase 3에서 바꾼 이전 산출물

| 대상 | 무엇을 | 왜 |
|---|---|---|
| `tests/fixtures/issue-db-sample/schema/type.schema.json` | `must_match` 항목에 `{id, pattern}` 객체도 허용 | `04-parser-matching.md §5.11 (1)`: "`must_match`·`must_event` 항목에 선택 `id`를 붙이고 `sequence`로 참조". Phase 1 스키마는 문자열만 받아 설계와 달랐다 |
| `tests/mocks/scenarios/data-001-none-cross-slot.yaml` | 순서를 "슬롯 1 설정 OFF → 슬롯 0 거부 → 슬롯 0 정상 연결"로 | Phase 1 배치(슬롯 0 거부가 먼저)에서는 `same_phone: false` 사본도 `sequence: [setting-off, rejected]` 때문에 C=0이라 Phase 3 완료 기준을 시험할 수 없었다. 음성 성질(S=0, `expect_top: none`)은 그대로다 |
| `DATA-001.none.2.log`, `tests/fixtures/logs/dual-sim-cross-slot.{log,events.json}`, `tests/mocks/golden/data-001-none-cross-slot.golden.json` | 위 시나리오로 다시 생성 | 위와 같음 (모의 골든) |
| `plugin/scripts/parse_logcat.py` | extractor를 `PatternRunner`로 실행(시간 상한), 출력에 `errors` 추가, 경고 `pattern-timeout` | `04-parser-matching.md §5.8 (4)`: 매처와 extractor 모두 패턴당 상한 |
| `tests/test_parse_logcat.py` | `test_slow_extractor_times_out_and_others_continue` 추가 (24개) | 위와 같음 |

### Phase 3 구현에서 정한 세부 (계약 보완 후보)

- **`--jira-meta` 형식**(계약에 정의 없음): JSON 객체 `{key, occurred_at, sw, summary, description}`, 모두 선택. `occurred_at`은 타임존 있는 ISO(없으면 종료 코드 2). 텍스트는 마스킹된 것. `--regress`는 이 값을 쓰지 않는다(수정 판단 없음, bonus 0).
- **출력**: `{schema, mode: analysis|regress, db, range, bonus, feedback_weight, jira, candidates[], pending_causes[], types[{type,S,signature,evidence}], causes[{type,cause,S,C,signature}], errors[{signature,error}], warnings[]}`. 후보는 `{type, cause, title, category, secondary_categories, score, confidence, S, C, signature, evidence[], bonus{proximity,keyword}, feedback{accepted,total,rate,applied}, fix_judgement, related[{cause,type,title,status}]}`. `--top 0`이면 전부. 증거 항목은 `{signature, condition, ts, tag, msg, event, fields, phone_id}`.
- **후보 구성**: S=1 유형마다 C=1 원인은 각각 후보, C=1 원인이 없으면 `cause: null`("원인 미확인") 후보 하나. `--regress`에서는 S=0이어도 C=1 원인이 후보가 된다(점수 0.6 참고). `pending_causes`는 S=1 유형의 pending 원인.
- **윈도우 의미**: 분석 범위 `[lo, hi]`는 분석 모드면 입력의 `input.window`(없으면 파일 범위), `--regress`면 `coverage.first_ts~last_ts`. 구간 `[a, a+W]`는 `lo ≤ a ≤ max(lo, hi−W)`로 범위 안에 둔다(범위 밖으로 밀어서 `must_not_match`를 피하지 못하게).
- **`same_phone`과 `must_not_match`**: 부정 조건도 같은 슬롯(+ `phone_id: null`) 레코드만 본다. 다른 슬롯의 `SETUP_DATA_CALL`은 이 슬롯의 증상을 깨지 않는다(`test_symptom_must_not_match_is_per_slot`).
- **`sequence`**: 구간 안 각 조건의 첫 충족 레코드가 `(시각, 입력 순서)` 기준으로 엄격히 증가해야 한다.
- **증거 구간 선택**: 충족 구간이 여럿이면 분석 모드는 발생 시각에 가장 가까운 증거가 있는 구간, 아니면 가장 이른 구간.
- **bonus**: 근접 = `proximity_bonus_max × max(0, 1 − |증거 시각 − 발생 시각| / (분석 범위 절반))`, 증거 중 가장 가까운 것. 키워드 = `keyword_bonus_max × |원인 title(원인 미확인이면 유형 title) + 유형 tags의 토큰 ∩ Jira summary·description 토큰| / |앞의 토큰|`. 토큰은 영숫자·한글 2자 이상, 소문자.
- **피드백 가중치**: 후보가 충족한 시그니처(원인 미확인이면 증상 시그니처)의 전역 키로 수락률을 찾는다. 표본 ≥ `quality.min_samples`일 때만 적용.
- **수정 판단 코드**: `already-fixed`, `regression-suspected`, `undetermined`, `fix-pending-build`, `fix-insufficient`, `unfixed`, 그리고 `wont-fix`/`not-a-bug`은 `judgement: null`. 빌드 비교는 같은 `build_compare` 규칙에 맞고 `branch_regex`가 맞은 부분(브랜치 접두어)이 같을 때만 한다.
- **시간 상한 구현**: `re`는 실행 중 끊을 수 없어서 작업 프로세스(spawn) 하나에 줄 목록을 한 번 넘기고 패턴마다 결과를 기다린다. 넘기면 프로세스를 끝내고 다음 패턴에서 다시 띄운다. 호출마다 프로세스 기동 비용(이 PC에서 약 0.15초)이 든다. 매처는 상한을 넘긴 시그니처를 `errors`에 남기고 불충족으로 본다. `--regress`의 실패 처리(종료 코드)는 `db_regress`·`db_verify`(Phase 5·10)가 `errors`를 보고 한다.
- **시그니처 오류**(없는 sequence id, 정규식 오류 등)는 이슈 DB 오류라 종료 코드 2.

## 개발 환경과 설계의 차이 (중요)

설계는 실행 환경을 **Ubuntu(Linux)** 로 못박는다 (`01-architecture.md §3`,
`14-site.md` S15). 이 초안은 **Windows PC에서 Git Bash로** 만들고 시험했다
(WSL 미설치). 사용자 결정: **산출물은 Ubuntu 타깃을 그대로 유지하고,
Windows 전용 보정은 커밋하지 않는다.**

| 지점 | 설계(Ubuntu) | 이 PC에서 한 처리 | 사내 영향 |
|---|---|---|---|
| `tests/mocks/bin/gh` | 확장자 없는 `#!/bin/sh` 스텁을 `PATH`로 부른다 | 로직은 `gh_stub.py`(파이썬)에 두고 `gh`는 `exec python3 …` 한 줄. Windows에서는 `mock_env.py`가 **런타임에** `gh.cmd` 래퍼를 임시 디렉토리에 만든다 (커밋 안 함) | 없음. Ubuntu에서는 POSIX 스텁이 그대로 쓰인다 |
| 실행 비트 | 파일 모드가 그대로 커밋된다 | `make_repo.py`가 `git update-index --chmod=+x`로 index 모드를 100755로 명시 (Windows는 `core.filemode=false`) | 없음. Ubuntu에서는 무동작이고 커밋 결과(트리 100755)가 같다 |
| 이 레포 자체의 실행 비트 | 〃 | 이 레포도 `core.filemode=false`다. **`git add` 뒤 `git commit` 전에 `python3 tools/fix_exec_bits.py`를 돌려야** POSIX 스크립트가 100755로 커밋된다 (`--check`로 확인) | 없음. Ubuntu에서는 무동작 |
| 실행 파일 탐색 | `subprocess`가 자식 `PATH`로 찾는다 | Windows `CreateProcess`는 **부모 `PATH`** 로 찾는다. 테스트는 `mock_env.resolve()`로 절대 경로를 넘긴다. **런타임 코드는 그대로 PATH의 `gh`를 쓴다** | 없음 |
| 줄바꿈 | LF | `core.autocrlf`가 켜져 있으면 작업 트리가 CRLF가 되어 **`#!/bin/sh` 스텁이 Ubuntu에서 `bad interpreter: /bin/sh^M`으로 죽고**, 같은 시나리오가 OS마다 다른 fixture를 낸다. 레포 루트 `.gitattributes`(`* text=auto eol=lf`)로 막고, 생성기·도구의 모든 텍스트 쓰기에 `newline="\n"`을 명시했다 | 없음. `test_generated_files_use_lf`·`test_repo_text_files_use_lf`가 지킨다 |
| 출력 인코딩 | UTF-8 기본 | Windows 콘솔이 cp949라 검증 때 `PYTHONIOENCODING=utf-8`을 붙였다. `mock_env.env_with_mocks()`가 기본으로 넣는다 | 없음 |

> 사내에서 처음 `pytest`를 돌릴 때 위 보정 경로가 모두 "무동작"이 되는지
> 확인한다(S-2).

## 사외 Claude Code 실험 결과 (S1 예비)

`tests/mocks/plugin-probe/`로 확인한다. 절차는 그 디렉토리의 `README.md`.
**사내 버전은 다를 수 있으므로 S-2에서 다시 확인한다.**

| # | 항목 | 사외 결과 | 비고 |
|---|---|---|---|
| 1 | 플러그인 로컬 로드 | ⏳ 미확인 | 새 세션에서 `/plugin`으로 `tests/mocks/plugin-probe` 등록 후 `/probe:ping` |
| 2 | 커맨드 ↔ 스킬 관계 | ⏳ 미확인 | 같은 실험 |
| 3 | `${CLAUDE_PLUGIN_ROOT}` 치환 | ⏳ 미확인 | 치환 안 되면 config `plugin.scripts_path`를 읽는 방식으로 바꿔야 한다 (`01-architecture.md §3`) |
| 4 | hooks (SessionStart / PreToolUse) | ⏳ 미확인 | `probe-hook.log`에 남는지 |
| 5 | MCP 도구 이름 형식 | ⏳ 미확인 (예상 `mcp__<server>__<tool>`) | `probe_hook.py`가 `tool_name`을 그대로 기록한다. `guard.py`(Phase 8)가 이 형식에 의존한다 |
| 6 | hook matcher `mcp__.*` | ⏳ 미확인 | 같은 실험 |
| 7 | 권한 결정 필드(`allow`/`deny`/`ask`) | ⏳ 미확인 | `probe_hook.py --decide` |
| 8 | `@SITE_PROFILE.md` import (파일 없음) | ⏳ 미확인 | `CLAUDE.md` 첫 줄. **사외에서는 경고가 나도 동작에 문제가 없다** — 모드 판별은 `.local-draft`가 한다 (`CLAUDE.md` 머리말 규칙 3) |
| — | `--mcp-config tests/mocks/mcp.json` 로 모의 MCP 붙이는 법 | ⏳ 미확인 | 사외 Claude Code 버전에서 확인해서 여기 적는다 |

> **왜 아직 미확인인가**: 플러그인 로드·hook·`@import`는 **세션이 시작될 때**
> 결정되므로, D0를 진행한 이 세션에서는 관찰할 수 없다. 새 세션을 열어
> 위 절차를 돌리고 이 표를 채운다. 스크립트 자체(`probe.py`,
> `probe_hook.py`)는 직접 실행해서 동작을 확인했다.

## 가정 (사내에서 확인해야 하는 판단)

1. **데이터 스택 태그 형식은 확정**으로 두고 썼다 (`DNC-<n>`, `DN-…`,
   `DPM-<n>`, `DRM-<n>`, `DSM-<n>`, `DCM-<n>`, `DSRM-<n>`). 레거시
   데이터 스택(DcTracker/DCT)은 어디에도 쓰지 않았다.
2. **그 밖의 모든 로그 문구는 placeholder**다. 시그니처·extractor·모의
   백엔드의 판별 정규식은 사내 실제 로그로 전부 다시 써야 한다(S9).
3. 슬롯 표기는 태그 접미사(`DNC-1`)가 1순위, 메시지 접두어(`[PHONE1]`)가
   2순위라고 가정했다(S20). RIL 페어링 키는 `(pid, phone_id, serial)`이다.
4. bugreport 섹션 헤더 문자열을 `------ RADIO LOG (…) ------` 형태로
   가정했다(S21). 실제 문자열이 다르면 `extract-bugreport`가 아무것도
   못 뽑는다.
5. 빌드명은 `<모델><브랜치>_<리비전>_<YYYYMMDD>` 가상 체계를 썼다(S12).
   `sanitize_build`가 이 체계에 대해 충분한지는 `tests/mocks/builds.yaml`의
   `sanitize_cases`로만 확인했다.
6. MCP 서버의 `tools/list`·`tools/call` 응답 형식은 표준 MCP 형식을 따랐다.
   사내 Jira MCP 구현이 다르면 `jira.field_map`의 경로 표기로 흡수하고,
   안 되면 `plugin/scripts/adapters/jira_<구현>.py`를 만든다(S3).
7. **모의 MCP 서버는 MCP SDK에 의존하지 않는다.** 외부 의존성을 늘리지 않기
   위해 `initialize`/`tools/list`/`tools/call`만 stdlib로 구현했다. 사내
   Claude Code가 다른 프로토콜 버전을 요구하면 `PROTOCOL_VERSION`을 고친다.
8. 파서 백엔드 인터페이스(`plugin/scripts/parser_backends/base.py`)와
   reference 백엔드는 Phase 2에서 만들었다. 계약의 `parse`·`builtin_events`·
   `version`은 모듈 함수가 아니라 백엔드 패키지의 `BACKEND` 객체(`ParserBackend`)의
   메서드로 제공한다. 모의 site 백엔드는 reference를 상속해 builtin 판별만 더한다.
9. `config.py`는 D0에서 **site-defaults 로드와 종료 코드 2 경로만** 있다.
   `check`/`set`/`sync-scripts-path`는 Phase 6에서 구현한다(지금은 종료
   코드 2로 "Phase 6에서 구현한다"를 낸다).
10. 마스킹 함수(`mask_pii`)는 Phase 4다. 골든 테스트의 마스킹 민감도
    검사는 그때까지 `tests/test_golden.py` 안의 임시 치환을 쓴다.
    Phase 4에서 `mask_pii`로 바꾼다.
11. 의존성은 `pyyaml`, `jsonschema`, `pytest`만 썼다. 사내 반입 규정과
    오픈소스 승인 대상이다(사용자 확인 필요). 타임존 변환은 표준 `zoneinfo`를 쓰므로
    Ubuntu의 시스템 tzdata가 필요하다(보통 설치돼 있다).
12. `--tz`가 없으면 logcat 시각을 **UTC**로, `--year`가 없으면 연도를 **2000**(고정,
    윤년)으로 해석하고 경고한다. 실행 날짜에 따라 결과가 달라지지 않게 하기 위해서다.
    분석 경로에서는 스킬이 항상 `--tz`/`--year`를 준다(`07-workflow.md §Step 3`).
13. 연도 없는 로그에서 월이 6 넘게 줄면(12월 → 1월) 해가 넘어간 것으로 보고 연도를
    올린다. `--year`는 **첫 줄의 연도**다.
14. 시계 이상 기준: 한 파일 안에서 앞 줄보다 1초 넘게 이르면 역행, **3600초 이상**
    늦으면 점프. 조용한 구간과 시계 점프를 로그만으로 구분할 수 없어서 점프 기준을
    크게 잡았다(TODO(SITE:S7), 사내 NITZ 전·재부팅 직후 로그로 확인).
15. 슬롯 태그 접미사는 `이름-숫자` 한 마디만 본다(`DNC-1`은 슬롯 1, `DN-17-C`·
    `DN-default-1`은 슬롯이 아니다). 메시지 접두어 `[PHONE n]`/`[SUB n]`, AOSP RILJ식
    메시지 끝 `[PHONE n]`도 본다(TODO(SITE:S20)).
16. RILJ 형식 placeholder: 요청 `[serial]> NAME`, 응답 `[serial]< NAME ... error=X`,
    unsol `[UNSL]< NAME`. 에러 표기가 없으면 `NONE`. RIL 태그는 `RILJ`만(TODO(SITE:S9·S10)).
17. `--jira-meta`는 스킬(Phase 13)이 Jira에서 뽑아 만드는 JSON이다. 형식은 위 "Phase 3
    구현에서 정한 세부"에 정했다(계약에 없음).
18. 정규식 시간 상한은 작업 프로세스로 구현했다(새 의존성 없음). 사내 반입 규정상
    `regex` 모듈(자체 timeout 지원)을 쓸 수 있으면 더 가볍게 바꿀 수 있다.

## 모의와 실제가 다를 것으로 예상되는 지점

| 지점 | 왜 다를 것 같은가 | 먼저 깨질 것 |
|---|---|---|
| 로그 문구·태그 | 전부 placeholder | 모든 시그니처와 extractor, `db_regress` 전체 |
| RIL 출력 형식 | 벤더·버전마다 다름 | RIL 페어링, `call_fail_cause` extractor |
| 슬롯 표기 | 메시지 접두어 형식이 다를 수 있음 | `phone_id` 추출률 → `same_phone` 시그니처 전부 |
| bugreport 섹션 헤더 | 버전·벤더마다 다름 | `extract-bugreport`가 빈 결과 |
| Jira 커스텀 필드 | 사내 필드 ID가 다름 | `field_map`, 발생 시각 → 분석 윈도우 |
| Jira MCP 도구 이름 | 구현마다 다름 | `jira.tools` 매핑, `guard.py` 허용 목록 |
| 빌드명 체계 | 사내 규칙이 다름 | `build_compare`, verify-fix 판정, fixture 파일명 |
| `${CLAUDE_PLUGIN_ROOT}` 치환 | 버전에 따라 다를 수 있음 | 모든 커맨드의 스크립트 호출 |
| GHE 브랜치 보호 권한 | 조직 정책 | `.githooks/` 채택 재결정 (`06-collaboration.md §6.1`) |

**S-0(선택) 권장**: Phase 3이 끝나면 `parse_logcat.py`(reference 백엔드)와
`match_signatures.py`만 사내로 가져가 실제 로그 3~5개로 돌려 보는 것이
되돌리는 비용을 크게 줄인다 (`15-local-draft.md §15.5` S-0).
위 표의 위쪽 네 줄이 거기서 바로 드러난다.

## 사내 확인 목록 (`TODO(SITE:S<n>)`)

`python3 tools/list_site_todos.py`로 갱신한다(Windows 콘솔에서는 `PYTHONIOENCODING=utf-8`). 2026-09-29(Phase 3 끝) 기준 **50곳**(Phase 3에서 늘지 않음). Phase 2에서 파서 엔진(S7 시계 이상 기준·S9 RILJ 형식·S20 슬롯 표기·S21 bugreport 헤더)과 새 시나리오 4개가 더해졌다:

### S1 (1곳)
- `tests/mocks/skills/data-analyzer/SKILL.md:63` — 스킬 이름과 호출 방식 확인.

### S4 (1곳)
- `plugin/site-defaults.example.yaml:38` — 사내 Jira 시각 타임존

### S5 (3곳)
- `plugin/site-defaults.example.yaml:50` — 사내 GHE 호스트
- `plugin/site-defaults.example.yaml:51` — 사내 org
- `tests/fixtures/issue-db-sample/.github/CODEOWNERS:3` — . 사내에서 확인하고 바꾼다.

### S7 (3곳)
- `plugin/scripts/parser_backends/logcat.py:13` — TODO(SITE:S20).
- `plugin/scripts/parser_backends/logcat.py:33` — 사내 로그(NITZ 전·재부팅 직후)로 기준을 확인한다.
- `plugin/site-defaults.example.yaml:54` — logcat 시각 타임존

### S9 (21곳)
- `plugin/scripts/parser_backends/ril.py:11` — . 벤더 RIL 태그는 TODO(SITE:S10).
- `tests/fixtures/issue-db-sample/data/DATA-001-no-setup-data-call/type.md:119` — .
- `tests/fixtures/issue-db-sample/parser-rules/extractors.yaml:10` — . 사내 실제 logcat으로
- `tests/fixtures/issue-db-sample/parser-rules/ril.yaml:3` — .
- `tests/fixtures/issue-db-sample/parser-rules/tags.yaml:7` — . 사내 실제 logcat으로
- `tests/fixtures/issue-db-sample/parser-rules/tags.yaml:23` — TODO(SITE:S10)
- `tests/fixtures/issue-db-sample/parser-rules/tags.yaml:27`
- `tests/fixtures/issue-db-sample/parser-rules/tags.yaml:30`
- `tests/fixtures/issue-db-sample/parser-rules/tags.yaml:34`
- `tests/mocks/logcat_gen.py:61` — RILJ 요청/응답 출력 형식. 사내 실제 로그로 확인한다.
- `tests/mocks/parser_backends/site/__init__.py:32`
- `tests/mocks/scenarios/call-001-01-positive.yaml:2` — , TODO(SITE:S10)
- `tests/mocks/scenarios/call-drop.yaml:2`
- `tests/mocks/scenarios/data-001-01-positive.yaml:2`
- `tests/mocks/scenarios/data-001-02-roaming.yaml:2`
- `tests/mocks/scenarios/data-setup-error.yaml:2`
- `tests/mocks/scenarios/dual-sim-ril.yaml:7` — TODO(SITE:S20)
- `tests/mocks/scenarios/network-001-01-positive.yaml:2`
- `tests/mocks/scenarios/sim-001-01-positive.yaml:2`
- `tests/mocks/scenarios/sim-absent.yaml:2`
- `tests/mocks/scenarios/sms-001-01-positive.yaml:2`

### S10 (2곳)
- `tests/mocks/scenarios/ims-001-01-positive.yaml:2`
- `tests/mocks/src/README.md:17`

### S11 (7곳)
- `tests/fixtures/issue-db-sample/ims/IMS-001-ims-registration-failed/type.md:77` — .
- `tests/fixtures/issue-db-sample/network/NETWORK-001-no-service/type.md:68` — .
- `tests/fixtures/issue-db-sample/sim/SIM-001-sim-not-detected/type.md:74` — .
- `tests/fixtures/issue-db-sample/sms/SMS-001-sms-send-failed/type.md:67` — .
- `tests/mocks/src/android16/build/make/core/version_defaults.mk:1` — 사내 트리의 실제 버전 식별 파일로 바꾼다)
- `tests/mocks/src/android17/build/make/core/version_defaults.mk:1` — 사내 트리의 실제 버전 식별 파일로 바꾼다)
- `tests/mocks/src/README.md:10`

### S12 (1곳)
- `tests/mocks/builds.yaml:3` — .

### S16 (1곳)
- `tests/fixtures/issue-db-sample/issue-db.config.yaml:12` — 사내 Jira 키 형식

### S17 (1곳)
- `tests/fixtures/issue-db-sample/issue-db.config.yaml:11` — 사내 Jira URL

### S18 (1곳)
- `tests/fixtures/issue-db-sample/issue-db.config.yaml:32` — 사내 Gerrit CL/커밋 형식

### S19 (2곳)
- `tests/fixtures/issue-db-sample/.github/CODEOWNERS:5` — ).
- `tests/fixtures/issue-db-sample/issue-db.config.yaml:68` — gh pr create --reviewer 형식

### S20 (4곳)
- `plugin/scripts/parser_backends/logcat.py:57` — 사내 실제 표기로 확인한다.
- `plugin/site-defaults.example.yaml:47` — 사내 Jira에 슬롯 필드가 있는지
- `tests/mocks/logcat_gen.py:66` — 슬롯 표기. 메시지 접두어는 사내 실제 형식으로 바꾼다.
- `tests/mocks/scenarios/README.md:10` — )

### S21 (2곳)
- `plugin/scripts/parse_logcat.py:438` — 사내 실제 문자열로 확인한다.
- `tests/mocks/logcat_gen.py:35` — 사내 실제 문자열 확인

> 아직 코드가 없는 곳(S3 `jira.tools` 확정, S8 태그 수집 목록, S13 마스킹
> 오탐, S14 보안 규정, S15 Ubuntu/파이썬 버전, S16~S19
> `issue-db.config.yaml` 값, S2 마켓플레이스, S6 Actions)은 Phase 1·2·4·6에서
> 코드가 생길 때 `TODO(SITE:S<n>)`가 늘어난다. 반입 전에 이 목록을 다시
> 뽑는다.

## 반입 체크리스트 상태 (`15-local-draft.md §15.4`)

| 항목 | 상태 |
|---|---|
| 전체 테스트 통과 | 🟡 D0·Phase 1~3 범위 (`pytest tests` 79개). `db_regress`·eval은 Phase 5·13 뒤 |
| 사내 정보 없음 | ✅ 사내 자료를 쓰지 않았다 |
| `plugin/site-defaults.yaml` 없고 example만 있음 | ✅ `test_plugin_root_helper_and_missing_site_defaults`가 검사 |
| `SITE_PATHS`의 다른 경로가 비어 있음 | ✅ `test_site_paths_are_absent_in_draft`가 검사 |
| 레포 루트에 `.mcp.json` 없음 | ✅ `test_no_mcp_json_at_repo_root`가 검사 |
| `.local-draft`를 반입 묶음에 넣지 않음 | ✅ `.gitignore` 등록 + `import_draft.py`가 항상 제외 |
| 이슈 DB 뼈대 (`make_db_skeleton.py`) | ✅ Phase 1. `test_skeleton_has_no_types_and_validates`가 검사 |
| `TODO(SITE)` 목록 갱신 | ✅ 위 절 (Phase가 끝날 때마다 다시 뽑는다) |
| `DRAFT_NOTES.md` 최신 | ✅ 이 파일 |

## 다음 세션에서 할 일

1. 새 세션을 열어 **빈 플러그인 실험**을 돌리고 위 "사외 Claude Code 실험
   결과" 표를 채운다 (`tests/mocks/plugin-probe/README.md`). 아직 미확인이다.
2. (선택, 사내) **S-0 선행 확인**이 이제 가능하다: `parse_logcat.py`(reference 백엔드)와
   `match_signatures.py`만 사내로 가져가 실제 로그 3~5개로 돌려 본다
   (`15-local-draft.md §15.5` S-0). 사외에서는 기다리지 않고 Phase 4로 간다.
3. **Phase 4** (마스킹): `docs/design/11-phases.md` Phase 4 절과 그 "읽을 문서"를 읽고
   `common/masking.py`의 `new_masker()`와 `mask_pii.py`, `parse --mask`, `cut`을 만든다.
   - 마스킹 자리는 Phase 2에서 만들었다: `parse_logcat.postprocess(masker=...)`가
     extractor보다 먼저 줄·builtin·외부 파서 레코드의 `msg`·`fields`에 적용한다.
   - Phase 3 매처는 `masked: true`만 받는다. Phase 4 완료 기준 "`parse --mask` → 매처
     파이프라인이 Phase 3 결과와 같다"는 `tests/test_match_signatures.py`의 입력을
     `--mask` 출력으로 바꿔 같은 결과가 나오는지로 확인한다.
   - 골든 테스트의 임시 치환(`tests/test_golden.py`의 `_provisional_mask`)을 `mask_pii`로
     바꾼다 (가정 10).
