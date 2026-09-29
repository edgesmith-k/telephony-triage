# DRAFT_NOTES — 사외 초안 진행 기록

> 사외 초안 모드의 진행 상태·가정·실험 결과를 적는 파일이다
> (`docs/design/15-local-draft.md §15.1`). 사내 Claude Code가 설계 문서를 다시
> 다 읽지 않고도 초안 상태를 파악하게 하는 것이 목적이다.
> 이 파일은 **반입 때 사내로 같이 간다**. `.local-draft`는 가지 않는다.

## 진행 상태

- 모드: **사외 초안** (`.local-draft` 있음)
- 완료 Phase: **D0, 1** (2026-09-28), **2, 3, 4, 5, 6** (2026-09-29)
- 완료 Phase 추가: **7** (2026-09-29, 사용자 확인 후 커밋)
- 완료 Phase 추가: **8** (2026-09-29, 사용자 확인 후 커밋. guard 예외·pre-push 검사 강화는 계약에 반영 — `CHANGES.md`)
- 완료 Phase 추가: **9** (2026-09-29, 사용자 확인 — Phase 10 진행 지시로 확인)
- 완료 Phase 추가: **10** (2026-09-29, 사용자 확인 후 커밋. recovery 예시는 사용자 결정 (a))
- 완료 Phase 추가: **11** (2026-09-29, 사용자 확인 후 커밋. 병합 unresolved Jira는 결정 (a), `GENERATOR_VERSION`은 1 유지)
- 완료 Phase 추가: **12** 구현·점검 끝 (2026-09-29, **사용자 확인 대기**)
- 다음 Phase: **13** (`11-phases.md` Phase 13 절부터, Phase 12 확인 후)
- Phase 2~6은 사용자가 미리 승인해서 Phase마다 확인을 기다리지 않고 진행했다(각 Phase 끝에 커밋·push). 완료 기준 점검 결과는 Phase별 절에 있다. **Phase 7부터는 다시 Phase마다 사용자 확인을 받는다.**
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

### Phase 4에서 만든 것

| 산출물 | 경로 |
|---|---|
| 마스킹 함수 | `plugin/scripts/common/masking.py` (`Masker`: 규칙 표, 번호 토큰, 기존 토큰 다음 번호, 멱등, `allow_patterns`, `mask_value`, `find`) |
| 마스킹 CLI | `plugin/scripts/mask_pii.py` (치환 `--in-place`/`--out`/stdout, `--check` 파일·`--staged`·`--changed <ref>`, `--events`) |
| `parse --mask` 연결 | `plugin/scripts/parse_logcat.py` (입력 전체의 기존 토큰을 먼저 보고, 줄·builtin·외부 파서 레코드를 extractor 전에 마스킹. 필드 값은 같은 번호 대응) |
| `cut` | `plugin/scripts/parse_logcat.py cut` (`--around`/`--evidence`, `--context`, `--max-lines`, 마스킹된 줄만 쓴다) |
| 마스킹된 fixture 생성 | `tests/helpers/make_sample_fixtures.py`, `make_log_fixtures.py`가 생성한 로그를 마스킹해서 쓴다 |
| Phase 4 테스트 | `tests/test_masking.py` (16개) |

### Phase 4 완료 기준 확인 결과

`python3 tests/test_masking.py` — **16개 전부 통과**. `python3 -m pytest tests` 전체 **94개 통과**.

| 완료 기준 | 확인 | 어디서 |
|---|---|---|
| `08-safety.md §8` 항목별 누락/과잉 (자격증명 `<CRED#n>`: SIP Digest `response=`·`nonce=`, AKA `RES`, `password=`) | ✅ 누락 30줄·과잉 12줄 | `test_each_kind_is_masked`, `test_no_over_masking` |
| Jira 응답 JSON 텍스트를 `mask_pii --events`로 → 전화번호·IMEI 토큰 | ✅ (날짜·빌드 필드는 그대로) | `test_mask_pii_jira_json_via_events` |
| 같은 셀 ID = 같은 `<CELL#n>`, 다른 셀 = 다른 번호 | ✅ | `test_numbered_tokens_and_existing_tokens`, `test_extractor_reads_masked_values` |
| 이미 `<CELL#1>`이 있는 입력의 새 셀 → `<CELL#2>` | ✅ (함수·`parse --mask` 둘 다) | `test_numbered_tokens_and_existing_tokens`, `test_existing_tokens_continue_numbering_in_parse` |
| 빌드 번호·타임스탬프 오탐 없음 | ✅ | `test_no_over_masking` |
| 같은 입력 = 같은 출력, 마스킹된 입력에 다시 적용해도 같음 | ✅ | `test_deterministic_and_idempotent`, `test_parse_mask_pipeline_matches_phase3` |
| `parse --mask` → 매처 결과가 Phase 3와 같음 | ✅ 샘플 fixture 전부(`--regress` S/C·후보·점수) | `test_parse_mask_pipeline_matches_phase3` |
| 원본 식별자가 든 줄에서 extractor가 마스킹된 값을 추출 | ✅ | `test_extractor_reads_masked_values` |
| 모의 site 백엔드의 원본 값 `builtin.*` 필드도 마스킹 | ✅ (`builtin.data.ip_assigned`) | `test_site_backend_builtin_fields_are_masked` |
| `cut` 결과 파일에 원본 식별자 없음 | ✅ (`--around`·`--evidence`, 잘라낸 fixture로 같은 원인) | `test_cut_writes_only_masked_lines` |
| (`mask_pii --check`의 `--staged`·`--changed`, 종료 코드 1) | ✅ | `test_mask_pii_check_staged_and_changed`, `test_mask_pii_replace_and_check_files` |
| (커밋된 fixture가 모두 마스킹돼 있음) | ✅ | `test_sample_db_fixtures_are_masked` |

### Phase 4에서 바꾼 이전 산출물

| 대상 | 무엇을 | 왜 |
|---|---|---|
| `tests/helpers/make_sample_fixtures.py`, `make_log_fixtures.py` | 생성한 로그를 마스킹해서 쓴다 | "모든 테스트 로그는 마스킹된 fixture만 쓴다"(`CLAUDE.md` §11.0). 시나리오 원문의 RIL 응답 `cid=1`이 셀 문맥(`cid=`)에 걸린다 |
| 샘플 fixture `DATA-001.none.log`·`DATA-001.none.2.log`, 파서 fixture 3개와 스냅샷 | `cid=1` → `cid=<CELL#1>` | 위와 같음 |
| `tests/test_golden.py` | 임시 치환(`_provisional_mask`)을 `common/masking.py`로 | 가정 10 (Phase 4에서 바꾼다) |
| `tests/mocks/parser_backends/site/__init__.py` | `builtin.data.ip_assigned`(원본 IP를 필드로) 추가, 버전 `0.0.3-mock`, 모의 골든 갱신 | Phase 4 완료 기준 "원본 값을 담은 builtin 필드도 마스킹" |
| `plugin/scripts/parse_logcat.py` | `--mask` 연결, `cut` 구현, 필드는 `mask_value`로 | Phase 2의 인터페이스 자리를 채움 |
| `tests/test_parse_logcat.py` | `test_mask_and_cut_are_phase4` 삭제 (23개) | 기능이 생겼다. `tests/test_masking.py`가 대신한다 |

### Phase 4 구현에서 정한 세부

- **번호 순서**: 규칙마다 위치를 먼저 모은 뒤 **텍스트에 나온 순서**로 번호를 준다(규칙 순서가 아니다). 한 마스커 안에서는 줄이 달라도 같은 값 = 같은 번호.
- **규칙 우선순위**: 자격증명 → SIP·tel URI·이메일·SUPI/SUCI → 문맥 있는 IMSI/IMEI/ICCID/TMSI/GUTI/셀/번호 → 번호·MAC·IP 형식 → 문맥 없는 15자리(Luhn이면 IMEI, MCC 200~799면 IMSI)·`89`로 시작하는 19~20자리(ICCID). 앞 규칙이 차지한 구간과 기존 토큰은 뒤 규칙이 다시 보지 않는다.
- **자격증명 문맥**: `response=`·`nonce=`·`cnonce=`·`opaque=`는 줄에 `Authorization`·`WWW-Authenticate`·`Proxy-*`·`Digest`가 있을 때만. `key=`는 값이 16자 이상이고 숫자가 있을 때만(설정 키 이름 오탐 방지). `password`·`passwd`·`pwd`·`secret`·`token`은 항상.
- **셀 문맥 키**: `mCi mPci mTac mLac mCid mNci mCellId cid ci pci tac lac nci eci cellId cellIdentity`. `mEarfcn`(채널 번호)은 식별자가 아니라 두지 않는다. RIL 데이터 콜 응답의 `cid`(context id)도 셀로 본다 — 과잉이지만 안전 쪽이다(TODO(SITE:S13)).
- **숫자 경계**: 숫자 값은 앞뒤가 단어 문자·`.`·`*`가 아닐 때만 본다(`_20260915` 같은 빌드명 안, `310260xxxx` 같은 Android 부분 마스킹, `1.2.3` 버전 안의 숫자를 건드리지 않는다).
- **`mask_value`(필드 값)**: 같은 마스커가 이미 본 원래 값과 정확히 같으면 그 토큰(문맥 없는 필드 값 `"4321"`도 `<CELL#1>`), 아니면 텍스트로 마스킹.
- **`parse --mask`**: 마스커는 파싱 한 번에 하나. 입력 파일 전체 텍스트의 기존 토큰을 먼저 본다. 마스킹 순서는 후처리 순서(시각 정렬된 레코드 순, 줄 → 그 줄의 builtin), 그다음 외부 파서 레코드.
- **`mask_pii` 치환 모드**: 파일마다 마스커 하나. `--in-place`/`--out`이 없으면 파일 하나를 stdout으로(여러 파일은 `--in-place` 필요). 요약 JSON은 `{files: [{path, replacements: {종류: 건수}}]}`.
- **`mask_pii --check`**: 결과 `{checked, detections: [{path, line, col, kind}]}` — 값은 내지 않는다. 있으면 종료 코드 1. `--staged`는 `git diff --cached`(ACMR) 파일의 index 내용, `--changed <ref>`는 `merge-base <ref> HEAD` 이후 바뀐 파일과 추적 안 된 파일의 워킹 트리 내용. NUL 바이트가 있는 파일은 건너뛴다. `allow_patterns`는 `--db`(없으면 cwd의 이슈 DB) 설정에서 읽는다.
- **`mask_pii --events`**: `events` 목록이 있으면 각 `msg`·`fields`, 없으면(예: Jira 응답) 모든 문자열 값을 마스킹하고 최상위에 `masked: true`.
- **`cut`**: 앵커는 `--around`면 ±`--seconds`의 줄, `--evidence`면 매처 출력 1위 후보 근거의 `(ts, tag)`와 같은 줄. 앵커마다 같은 파일에서 앞뒤 `--context` 줄을 합치고, `--max-lines`를 넘으면 context를 줄인다(앵커만으로 넘으면 종료 코드 2). 여러 파일은 시각 순으로 합친다. `--rules`를 주면 그 이슈 DB의 `allow_patterns`를 쓴다. 출력 `{out, lines, anchors, context, masked: true, replacements}`.

### Phase 5에서 만든 것

| 산출물 | 경로 |
|---|---|
| 생성기 | `plugin/scripts/db_build.py` (README·카테고리 README·STATS·parser-rules CHANGELOG·캐시, `--write`/`--verify [--staged]`/`--preview`/`--cache-only`, `generator_version` 검사) |
| 린터 | `plugin/scripts/db_lint.py` (`--all`/`--ref`/`--changed`/`--staged`, `--residual`, 검사 코드 목록은 스크립트 머리말) |
| 회귀 | `plugin/scripts/db_regress.py` (`--all`/`--changed`/`--staged`, 항상 회귀·검증 모드, 실패 원인·`allow-cause` 초안, `--events-diff`는 Phase 10 자리) |
| fixture 이름·기대값 | `plugin/scripts/common/fixtures.py` |
| 컴파일 캐시 | `plugin/scripts/common/compiled.py` (소스·백엔드·외부 파서 해시, 매처가 hit/miss 판단) |
| git 범위 | `plugin/scripts/common/gitscope.py` (`--changed`·`--staged`·`--ref`, index·ref 트리 꺼내기) |
| 버전 상수 | `plugin/scripts/common/versions.py` (`GENERATOR_VERSION = 1`, `SCHEMA_VERSION = 1`) |
| 변형 이슈 DB | `tests/fixtures/issue-db-lint-errors/`, `issue-db-empty-category/`, `issue-db-pending/` — `tests/helpers/make_variant_dbs.py [--check]`가 샘플에서 만든다 |
| 새 시나리오 | `tests/mocks/scenarios/data-001-03-pending.yaml` (pending 원인 양성 fixture) |
| 테스트 공용 헬퍼 | `tests/helpers/runner.py` (플러그인 루트·스크립트 실행·DB 복사·임시 git 레포) |
| Phase 5 테스트 | `tests/test_db_build.py`(10), `tests/test_db_lint.py`(9), `tests/test_db_regress.py`(8) |

### Phase 5 완료 기준 확인 결과

`python3 -m pytest tests` 전체 **121개 통과**.

| 완료 기준 | 확인 | 어디서 |
|---|---|---|
| 샘플 README가 §5.6 구조, 6개 카테고리 모두 | ✅ | `test_readme_structure_matches_design` |
| 0건 카테고리: `issue-db-empty-category/`와 `make_db_skeleton.py` 결과(6개 모두 "아직 등록된 이슈가 없습니다") | ✅ | `test_empty_categories_are_listed`, `test_skeleton_shows_all_categories_empty` |
| 두 번 실행하면 바이트 단위로 같음 | ✅ (LF·끝 개행 1개 포함) | `test_write_is_deterministic_and_verify` |
| `--preview`·`--cache-only`는 워킹 트리를 바꾸지 않음 | ✅ | `test_preview_and_cache_only_leave_worktree_alone` |
| 캐시 해시가 다르면 매처가 재컴파일 | ✅ (hit이면 캐시 시그니처를 쓴다는 것도 확인) | `test_matcher_uses_cache_and_recompiles_when_hash_differs` |
| 린터가 `issue-db-lint-*`의 일부러 넣은 오류를 모두 잡음 | ✅ 24개 (코드·파일 쌍) | `test_injected_errors_are_all_caught` (`EXPECTED`), 옛 ID 잔존은 `test_residual_ids`, synthetic은 `test_synthetic_fixtures_warn_when_not_allowed` |
| `.resolved.1.log`·`.extra.1.log`·다른 유형 원인의 `also_allowed`는 통과 | ✅ 샘플 오류·경고 0 | `test_sample_db_is_clean`, `test_skeleton_is_clean` |
| `decision: manual` 피드백이 수락률에 들어가지 않음 | ✅ | `test_stats_excludes_manual_feedback`, `test_manual_feedback_is_not_counted`(Phase 3) |
| `date`는 최근이지만 `occurred_on`이 오래된 Jira가 최근 30일·급증에 들어가지 않음 | ✅ (반대 경우도 확인) | `test_stats_use_occurred_on_for_recent_counts` |
| 회귀가 샘플 fixture 전부 통과 | ✅ 20개 | `test_all_sample_fixtures_pass` |
| 음성 fixture를 깨면 어느 유형의 어떤 시그니처가 잡았는지 출력 | ✅ | `test_broken_negative_fixture_reports_type_and_signature` |
| `signatures_pending` 원인의 양성 fixture가 `"<유형 ID>:unresolved"`로 포함 | ✅ (`issue-db-pending/`) | `test_pending_cause_fixture_expects_unresolved` |
| (그 밖) `--verify --staged`, `generator_version` 불일치 종료 코드 2, 새 원인 fixed 금지(base 범위), `--changed`·`--staged` 범위와 parser-rules 변경 시 전체 확장, 백엔드 불일치·`--no-external` 종료 코드 2, 시간 상한 초과는 실패, `allow-cause` 초안 | ✅ | 각 테스트 파일 |

### Phase 5에서 바꾼 이전 산출물

| 대상 | 무엇을 | 왜 |
|---|---|---|
| `plugin/scripts/common/masking.py` | 번호·IP·문맥 숫자 규칙의 뒤쪽 경계를 `(?![\w.])` → `(?!\w\|\.\w)`로 | **마스킹 누락 수정**: 문장 끝 마침표 뒤의 값(`연락처 +82-10-1111-2222.`)이 마스킹되지 않았다. 린터 오류 주입 시험에서 드러났다. 버전 번호(`1.2.3.4.5`)·빌드명은 여전히 그대로다. 기존 fixture는 바뀌지 않았다 |
| `plugin/scripts/match_signatures.py` | 매칭 본체를 `match()`로 분리(`db_regress`·`db_verify`가 직접 부른다), 캐시(`cache: hit\|miss\|none`)를 쓴다 | 06 §6.8, 04 §5.11 (3) |
| `plugin/scripts/common/issuedb.py` | Jira 기록 자체도 보관(`IssueDb.jira`) | 생성기·통계 |
| `tools/list_site_todos.py` | 변형 이슈 DB 3개를 건너뜀 | 샘플 표시의 사본이라 같은 항목이 네 번 세어졌다 |

### Phase 5 구현에서 정한 세부 (계약 보완 후보)

- **README**(§5.6 예시에 없는 표기): 원인 셀에 `CP 근거`(cp_evidence 있음), `시그니처 없음`(pending) 표시. "최근 추가 (N건)"의 N은 실제 표시 건수(최대 10). 보관 절은 `| ID | 제목 | 상태 | 새 ID |` 표, 없으면 "없음". Jira가 없으면 "아직 기록된 Jira가 없습니다.", 기준일은 `-`. 카테고리 README는 증상 시그니처 요약(이벤트·패턴·window·sequence·슬롯 무관), `Android`(빈 목록 = 전 버전)·`코드`(`ref` + `symbol` + 버전) 열을 더한다.
- **STATS 급증**: 최근 30일 ≥ 2건이고 최근 30일 ≥ (그 앞 90일 건수 / 3) × `surge_ratio`. 발생일은 `occurred_on`(없으면 `date`), 기준일은 가장 최근 Jira `date`. "최근 N일"은 기준일 포함 N일(경과 일수 0~N-1).
- **STATS 그 밖**: 기여 현황의 월은 피드백 `date`의 월, "분석"은 `decision`이 manual이 아닌 것. 기여자 = Jira `analyzed_by` ∪ 피드백 `by`. 품질 점검에 "fixed 전환 불가(흔적 시그니처 없음)"도 넣었다(§6.6 리뷰 항목과 같은 기준).
- **캐시**: `.cache/compiled.json` = `{format, generator_version, hash, environment{backend, external}, signatures{소유자 ID: 원문}, causes{fix, related, status, pending}, extractors, acceptance}`. 해시 입력은 설정·`type.md`·`jira/`·`feedback/`·`parser-rules/*.yaml`(CRLF→LF)과 백엔드 이름·버전, site-defaults의 외부 파서 `{adapter, version}`.
- **린터 수준**: 오류 = 스키마·ID·Jira·related·code_refs·fix.ref·fixture 이름·원본 식별자·정규식 안전·sequence·빈 시그니처·builtin/ext 참조·근거·새 원인 fixed·also_allowed·병합 대상·parser-rules·옛 ID. 경고 = 금지 동의어, 제목 길이(유형 30자·원인 20자), 양성 fixture 없음, pending, 특정 마스킹 번호 고정, synthetic.
- **린터 휴리스틱(보수적·정적)**: 원본 식별자 패턴 = `\d{N}`/`[0-9]{N}`(N≥10), 10자리 이상 숫자, `01[016789]…`·`+82` 전화번호, 이스케이프를 푼 리터럴에 마스킹 규칙이 걸리는 값. 정규식 안전 = 반복 안의 반복(max>1), 반복 안에서 첫 요소가 같은 선택지, 역참조. **한계**: `(\d|\w)+`처럼 서로 다른 문자 집합이 겹치는 선택지는 못 잡는다 — 실행 시간 상한이 대신 막는다.
- **린터 범위**: 전역 검사(중복 등)는 전체 트리를 보고 바뀐 파일이 관련된 결과만 낸다. `--staged`는 index를, `--ref`는 그 커밋을 임시 디렉토리로 꺼내 검사한다. "새 원인 fixed 금지"의 base는 `--changed`면 merge-base, `--staged`면 HEAD(없으면 검사 안 함).
- **회귀**: fixture는 `parse --full --mask --tz UTC`(연도 기본값)로 파싱한다(분석 범위가 파일 전체라 시각 기준은 결과에 영향이 없다). 범위: 바뀐 유형 + 그 원인의 `related` 원인의 유형 + 같은 카테고리 유형, `parser-rules/`·`schema/`·`issue-db.config.yaml`이 바뀌면 전체. 결과 `{summary{scope, expanded, total, passed, failed}, results[{fixture, kind, expect, status, S, C, reasons[], allow_cause_drafts[]}]}`. `allow-cause` 초안은 `{op, fixture: fixtures/<이름>, cause, type_dir}`이고 양성·recurrence·extra에만 만든다. 파서·매처의 `errors`(시간 상한)는 실패.
- **파서 백엔드 비교**: 회귀는 site-defaults의 백엔드(`parser.backend`)와 버전을 이슈 DB `parser_backend`와 비교한다. 외부 파서는 site-defaults에 설정된 것을 "사용 가능"으로 본다(어댑터 로드 실패는 분석 때 경고로 드러난다).

### Phase 6에서 만든 것

| 산출물 | 경로 |
|---|---|
| 설정 | `plugin/scripts/config.py` (`show`, `site-defaults`, `init`, `set`, `sync-scripts-path`, `jira-candidates`, `set-jira`, `install-hooks`, `check`, `gh-status`) |
| 사용자 config·우선순위 | `plugin/scripts/common/userconfig.py` (사용자 config > site-defaults > 내장, `TELEPHONY_TRIAGE_HOME`, 권한 700) |
| MCP 도구 후보 | `plugin/scripts/common/mcptools.py` (stdio 서버 `tools/list`, `exclude_servers`, 읽기·쓰기 분류, 전체 이름) |
| gh 호출 | `plugin/scripts/common/ghcli.py` (`shutil.which("gh")`, `GH_HOST`) |
| 코드 경로 | `plugin/scripts/code_roots.py` (`suggest`, `validate`, `resolve`, `find-symbol`, `remember`) |
| 세션 lock·스냅샷 | `plugin/scripts/db_pr.py` (`lock status/acquire/release`, `snapshot --job`. 나머지 서브커맨드는 Phase 7 자리) |
| setup 커맨드 | `plugin/commands/setup.md` (setup 1~10) |
| `--db` ③ 연결 | `common/dbpath.resolve(user_config_path=...)` ← `userconfig.issue_db_path` |
| Phase 6 테스트 | `tests/test_config_setup.py` (11개) |

### Phase 6 완료 기준 확인 결과

`python3 tests/test_config_setup.py` — **11개 전부 통과**. `python3 -m pytest tests` 전체 **132개 통과**.

| 완료 기준 | 확인 | 어디서 |
|---|---|---|
| config 대화형 생성, 잘못된 경로 거부 | ✅ (stdin 대화형·`--answers` 둘 다, 타임존·year_source도 거부) | `test_init_interactive_rejects_bad_paths`, `test_set_and_sync_scripts_path` |
| 비표준 이름의 `mock-jira`에서 `jira.tools` 후보를 골라 확인받고 `read_tools`에 포함 (헬퍼 루트, `exclude_servers: []`) | ✅ (쓰기 도구는 후보 아님, 짧은 이름 거부) | `test_jira_tools_from_nonstandard_mock_server` |
| `exclude_servers: ['mock-*']` 복사본에서 `mock-jira`가 후보에서 빠짐 | ✅ | `test_excluded_mock_servers` |
| `site-defaults.yaml` 없는 루트에서 setup·`config.py check`가 종료 코드 2, example 읽지 않음 | ✅ (config·db_pr·code_roots 모두) | `test_missing_site_defaults_stops_everything` |
| read_tools 확인 절차(전체 도구 이름 저장) | ✅ | `test_jira_tools_from_nonstandard_mock_server` |
| gh 인증 실패 시 읽기 설정(1~8)은 끝난 상태로 "쓰기 불가" 안내 후 종료 | ✅ | `test_setup_with_gh_unauth_finishes_read_setup` |
| 스키마·생성기 버전 확인은 스냅샷(origin/<base>) 기준, 버전 불일치면 읽기 전용 | ✅ (옛 사용자 clone은 쓰기 가능, 스냅샷은 `schema-too-new`) | `test_version_check_uses_snapshot_of_origin` |
| `migrate/schema-v<N>` 브랜치면 버전 불일치에서도 gh 인증만 | ✅ | `test_migrate_branch_skips_version_checks` |
| `--for dry-run`은 gh 인증 없이 `push_allowed: false`로 통과 | ✅ | `test_setup_with_gh_unauth_finishes_read_setup` |
| `core.hooksPath`가 정확히 `.githooks` | ✅ | 같은 테스트 |
| setup 후 사용자 clone의 브랜치·워킹 트리 그대로(캐시는 스냅샷에만) | ✅ (HEAD도 같음) | 같은 테스트 |
| lock: 다른 작업 키 → `acquire`·`snapshot` 종료 코드 2와 보유자, 같은 키 10분 이내 → `--take-over` 필요, 4시간 넘으면 가져옴, `release --force` | ✅ | `test_session_lock_rules` |
| 코드 경로 선택기: 버전 일치 프로필 먼저 추천, 잘못된 루트 거부, 버전 불일치 경고 | ✅ (16/17 경로가 다른 파일 `find-symbol`, `resolve`) | `test_code_root_selector` |
| (파서 백엔드·외부 파서 고정값 불일치 → 쓰기 불가 사유) | ✅ `parser-backend-mismatch`, `external-parser-mismatch` | `test_backend_and_external_pins_block_writes` |

### Phase 6에서 바꾼 이전 산출물

| 대상 | 무엇을 | 왜 |
|---|---|---|
| `plugin/scripts/config.py` | D0의 site-defaults 로드만 있던 것을 전체 구현으로 | Phase 6 할 일 (D0 가정 9) |
| `plugin/scripts/common/dbpath.py`, `common/buildname.py` | git 출력 디코딩을 UTF-8로 지정 | 경로에 한글이 있으면(이 PC) cp949 디코딩이 실패해 `git_toplevel`이 예외를 냈다. Ubuntu에서는 영향 없음 |
| `tests/helpers/runner.py` | `run()`에 `env`·`unauth`·`stdin` | Phase 6 테스트 |
| `plugin/.claude-plugin/plugin.json` | 설명의 "Phase D0" 표기를 "사외 초안"으로 | 상태 표기 |

### Phase 6 구현에서 정한 세부 (계약 보완 후보)

- **`config.py` 서브커맨드 추가**: 계약(`contracts.md §3.2`)은 `show`/`check`/`sync-scripts-path`/`set`만 적는다. setup 1·4·5·9를 스크립트로 하려고 `init [--answers]`, `jira-candidates`, `set-jira`, `install-hooks`, `gh-status`를 더했다. 사용자 확인(Jira 도구 선택 등)은 커맨드(Claude)가 하고, 스크립트는 후보 계산과 저장만 한다.
- **`config.py check` 출력·종료 코드**: `{db, for, branch, migrate_branch, writable, push_allowed, read_only, versions{schema, generator, backend}, gh{checked, ok, host}, reasons[{code, message}]}`. 사유 코드 `schema-too-new`, `schema-too-old`, `generator-mismatch`(`ci_mode: actions-build`면 보지 않음), `parser-backend-mismatch`, `external-parser-mismatch`, `gh-auth`. 종료 코드: `--for write`는 `push_allowed`면 0 아니면 2, `--for dry-run`은 `writable`이면 0 아니면 2. `SUPPORTED_SCHEMA = (1, 1)`.
- **사용자 config 위치**: 환경변수 `TELEPHONY_TRIAGE_HOME`(기본 `~/.telephony-triage`). 사용자 config에 없는 값은 site-defaults(`jira.*`, `logcat.*`, `ghe.host` → `issue_db.ghe_host`)와 내장 기본값(`issue_db.base_branch: main`, `logcat.year_source: jira`, `work_dir: <home>/work`)으로 채운다.
- **`init` 검증**: `issue_db.path`는 있는 디렉토리이거나 상위가 있어야 한다(없으면 clone 명령을 제안). `log_dir`는 있어야 한다(빈 값이면 건너뜀). `work_dir`는 상위가 있어야 하고 700으로 만든다. 타임존은 IANA, `year_source`는 `jira|file-mtime|ask`. 대화형은 항목당 3번까지 다시 묻는다.
- **Jira 도구 후보**: 기본 서버 목록은 `~/.claude.json`의 `mcpServers`(사용자 범위), `--mcp-config`로 바꾼다. 원격 서버는 도구 목록을 못 읽으므로 스킬이 세션에서 보이는 이름을 `--tools-json`으로 준다. 이름 분류: 쓰기 단어(create/add/update/delete/post/move/…)가 있으면 제외, `comment` → `get_comments`, `search|query|jql`(또는 issue·ticket + list) → `search_issues`, issue·ticket + get/fetch/read/view/show → `get_issue`. site-defaults의 팀 기본값을 먼저 제안한다. `set-jira`는 `read_tools`에 `jira.tools` 값을 자동으로 더한다.
- **gh 호출**: 런타임 코드도 `shutil.which("gh")`로 PATH의 `gh`를 찾는다(개발 환경 차이 표 참고).
- **lock 파일**: `<work_dir>/session.lock` JSON. 이어받기(`--take-over` 또는 10분 초과)는 `started_at`을 유지한다. 출력 `{acquired, lock{job, command, started_at, updated_at, expired, age_sec}, taken_over, previous}`. 시각은 `TT_NOW`로 바꿀 수 있다(테스트).
- **스냅샷**: 매번 `git worktree prune` 후 `<work_dir>/_snapshot`이 worktree면 `checkout --detach -f origin/<base>`, 아니면 `worktree add --detach`(worktree가 아닌데 비어 있지 않으면 종료 코드 2). pull은 현재 브랜치가 base이고 깨끗할 때만 `--ff-only`, 실패는 자동 해결하지 않고 사유로 낸다.
- **코드 경로**: `suggest` 순서는 버전 일치 프로필 → 버전 일치 최근 → 나머지 최근(최신 순) → 나머지 프로필. 트리 버전 추정은 `build/release/release_config_map.textproto` → `build/make/core/version_defaults.mk` → `build/core/version_defaults.mk` 순서(TODO(SITE:S11)). `validate`는 잘못된 루트면 종료 코드 2. `find-symbol`은 `Class#method`면 `Class.*` 파일(또는 `class Class` 선언이 있는 파일)에서 `method(`를 찾는다. `remember`로 최근 5개를 기록한다(`code_roots.py`의 계약 밖 서브커맨드).
- **setup 커맨드 형식**: `plugin/commands/setup.md`는 frontmatter `description`만 쓴다. 커맨드 파일 형식·`${CLAUDE_PLUGIN_ROOT}` 치환은 빈 플러그인 실험(S1)이 아직 미확인이다.

### Phase 7에서 만든 것

| 산출물 | 경로 |
|---|---|
| 계획 적용·drift·ID 도구 | `plugin/scripts/db_add.py` (`apply`, `drift`, `renumber`, `check-ids`, `similar`) |
| 쓰기 오케스트레이션 | `plugin/scripts/db_pr.py` (`cleanup`, `preflight`, `stage`, `summary`, `publish`, `discard`, `find-plan`, snapshot 뒤 사후 lint) |
| 검증 뼈대 | `plugin/scripts/db_verify.py` (`rules`: R4만 실행, R1~R3·R5 `not-implemented`, R6 `skipped`, `--plan`/`--draft`/`--changed`/`--staged`, `TT_FORCE_VERIFY_EXIT=3`. `resolution`·`fix`는 Phase 10) |
| type.md 엔티티 단위 쓰기 | `plugin/scripts/common/typedoc.py` (바뀐 최상위 키·원인·원인 안 필드만 다시 렌더링, 본문 `### <원인 ID>` 섹션을 ID 순서로 삽입) |
| YAML 엔티티 단위 쓰기 | `plugin/scripts/common/yamldoc.py` (키 블록·목록 항목 분할, 결정적 덤프. parser-rules 항목 추가·교체도 이것으로) |
| 손으로 쓴 계획 8개 | `tests/fixtures/plans/p7-*.plan.json` (analyze append/new-cause/new-type/unresolved, review reclassify, record pending/verified, import) |
| 사후 lint 변형 | `tests/fixtures/issue-db-dup-id/` (`make_variant_dbs.py`의 `dup_id`: 같은 type.md에 DATA-001-03 두 번, MOCK-1101이 두 유형에) |
| 쓰기 경로 테스트 환경 | `tests/helpers/workspace.py` (임시 홈·config·모의 원격·clone·gh 상태, 생성 파일을 main에 미리 커밋, `ship()`·`merge()`·`push_main()`·`push_branch()`) |
| Phase 7 테스트 | `tests/test_db_pr.py` (21개) |

### Phase 7 완료 기준 확인 결과

`python3 tests/test_db_pr.py` — **21개 전부 통과** (약 5분. 20개 + 아래 "Phase 7 대조 후 보완"의 1개). 전체 결과는 아래 "반입 체크리스트 상태".

| 완료 기준 | 확인 | 어디서 |
|---|---|---|
| `append`·`new-cause`·`new-type`·`unresolved`·`reclassify`가 모두 PR까지 | ✅ (PR 5개, 제목에 할당된 실제 ID) | `test_each_op_reaches_pr` |
| main에 없는 Jira의 `reclassify` 거부, main에 있는 Jira의 `append` 중단(기존 분류 표시) | ✅ `reclassify-missing`, `jira-exists`(+`existing.cause`), preflight `jira_in_main` | `test_reclassify_needs_jira_in_main_and_append_stops_on_existing` |
| `source: record` → PR, summary·PR 본문에 "수동 기록"과 실행/건너뛴 검증, `jira.origin: file` 라벨 | ✅ | `test_record_labels_pending_rules_and_sync_keeps_pending` |
| `signatures_pending`은 record에서만, pending 피드백은 analyze에서만 | ✅ (analyze·import의 pending 원인 거부, record stage는 pending 미포함, analyze stage는 포함) | `test_pending_only_in_record_and_pending_feedback_only_in_analyze`, 위 테스트 |
| pending 원인이 든 record PR이 뒤처졌을 때 sync-pr가 pending 그대로 올림 | ✅ (다른 PR 머지 뒤 재적용, 최신 main 위, `signatures_pending: true` 유지) | `test_record_labels_pending_rules_and_sync_keeps_pending` |
| record `verify-resolution`의 자기 Jira evidence 거부, `new-cause` 뒤 `verify-resolution`(resolved fixture) → verified, 순서 반대 거부 | ✅ (`self-evidence`, `order` — 뒤에 오는 `set-resolution`도 `order`) | `test_verify_resolution_and_update_fix_rules` |
| 같은 계획 두 번 stage → `<wt>` diff 바이트 단위 같음 | ✅ (사이에 넣은 잔여 파일도 사라짐) | `test_restage_is_byte_identical_and_feedback_stable` |
| 사용자 clone 불변(앞선 커밋이 있는 로컬 `issue/<KEY>` checkout 상태 포함), discard 후 worktree·`tt/*`·`state.json`·lock 없음 | ✅ (HEAD·브랜치·워킹 트리 상태·로컬 브랜치 SHA 같음) | `test_user_clone_is_untouched_and_discard_cleans_up` |
| `tt/<br>`가 다른 worktree에 checkout → stage 종료 코드 2 | ✅ | `test_tool_branch_in_other_worktree_stops_stage` |
| Step 8-2: 도구 브랜치 잔여물, 원격에 있는 브랜치("plan으로 브랜치 갱신"은 lease push) | ✅ (잔여물 cleanup, 같은 SHA → lease push + `gh pr edit`, 다른 사람 push → 옛 lease·`new` 모두 거부) | `test_step8_2_branch_states` |
| source 9개 값 밖(`migrate`) 거부, `stage --dry-run` gh 인증 없이 summary까지, `TT_FORCE_VERIFY_EXIT=3` → stage 3 | ✅ | `test_source_outside_values_dry_run_and_forced_exit_3` |
| drift: `set-resolution` 대상 해결책 변경 → 1, 결정 반영 후 통과. `update-parser-rule` 기능 필드 변경은 drift, 이력 필드만은 아님. `allow-cause` 대상 `also_allowed` 변경은 drift | ✅ | `test_drift_resolution_parser_rule_and_allow_cause` |
| `allow-cause`: `.expect.yaml` 없으면 기본 기대값 + `also_allowed`로 생성, 있으면 추가, 자기·같은 유형 원인 거부, 리뷰어에 fixture 카테고리 오너 | ✅ | `test_allow_cause_creates_or_extends_expect_and_adds_reviewer` |
| 같은 계획 두 번 stage해도 피드백 파일 이름·`date` 같음 | ✅ | `test_restage_is_byte_identical_and_feedback_stable` |
| `verify-resolution` evidence가 없는 Jira·fixture면 거부, `update-fix` `fixed`→`fix-submitted` 거부, `not-a-bug`→`fix-submitted` 통과 | ✅ | `test_verify_resolution_and_update_fix_rules` |
| 두 브랜치가 같은 번호(DATA-001-03)의 새 원인·fixture → 차례로 머지할 때 둘째가 sync-pr로 DATA-001-04, 섞이지 않고, PR 제목·본문 갱신 | ✅ (둘째 머지도 텍스트 충돌 없음) | `test_same_number_race_resolved_by_sync_pr` |
| sync-pr 재적용 때 `included_pending` 다시 포함 | ✅ | `test_pending_only_in_record_and_pending_feedback_only_in_analyze` |
| 원격이 `pr.head_sha` 이후 바뀌면 바뀐 내용 표시, 계획 없는 브랜치는 수동 절차만 안내하고 아무것도 안 바꿈 | ✅ (`find-plan`의 `remote_changed`·`remote_diff_stat` / `manual_steps`) | `test_step8_2_branch_states`, `test_sync_pr_without_plan_only_guides` |
| sync-pr 도중 원격 변경 → push 거부, 승인 후 파일 변경·커밋 둘·메시지·브랜치 불일치 → publish 거부 | ✅ | `test_step8_2_branch_states`, `test_publish_rejects_changes_after_approval` |
| `cleanup --dry-run`은 현재 lock 작업의 worktree 제외, `--yes` 없이는 안 지움, `lock release` 뒤 다음 작업이 바로 lock | ✅ | `test_cleanup_skips_lock_holder_and_needs_yes` |
| `issue-db-dup-id/`에서 사후 lint가 ID 중복·Jira 중복 보고(아무것도 안 바꿈) | ✅ | `test_post_lint_reports_duplicates_without_changes` |
| 기존 fixture 결과를 바꾸는 규칙은 R4에서 차단 | ✅ (R1~R3·R5 `not-implemented`) | `test_rule_that_changes_existing_fixture_is_blocked_by_r4` |
| (그 밖) import 규칙(피드백 없음), 새 유형 증상 시그니처 필수, `check-ids`·`renumber`(내 ID만, 옛 ID 잔존 없음)·`similar` | ✅ | `test_import_rules_and_new_type_needs_symptom`, `test_check_ids_renumber_and_similar` |

### Phase 7에서 바꾼 이전 산출물

| 대상 | 무엇을 | 왜 |
|---|---|---|
| `plugin/scripts/db_lint.py` `_check_ids` | 같은 type.md 안의 중복 ID도 `duplicate-id`로 잡는다 | **린터 누락 수정**: 두 PR이 같은 원인 번호를 추가한 채 `sync-pr` 없이 머지되면 중복이 **한 type.md 안**에 생기는데, 기존 검사는 다른 파일 사이 중복만 봤다. `issue-db-dup-id` 사후 lint 시험에서 드러났다 |
| `plugin/scripts/db_pr.py` | Phase 6 자리(`PHASE7` 종료 코드 2)를 구현으로. `snapshot` 결과에 `post_lint` | Phase 7 할 일 |
| `tests/helpers/make_variant_dbs.py` | `issue-db-dup-id` 변형 추가 | Phase 7 완료 기준 |

### Phase 7 구현에서 정한 세부 (계약 보완 후보)

- **`db_add apply` 종료 코드**: 계획 형식(스키마)·`source` 값·`schema_version` 불일치·`--pending`을 analyze 밖에서 줌 → 2. op 규칙 위반(Jira 중복, reclassify 대상 없음, `fixed`→`fix-submitted`, evidence 없음, pending 불가, 순서 등) → 1과 `rejected: [{code, op_index, message, ...}]`. 거부가 있으면 **아무 파일도 쓰지 않는다**(메모리에서 적용 후 한 번에 쓴다).
- **`db_add apply` 옵션**: `--pending <file>`(여러 번, `db_pr stage`가 analyze일 때만 넘김), `--user <GHE 아이디>`(없으면 config `user.ghe_id`). 출력 `{applied, changed[{path, change}], ids[{temp_id, id}], fixtures[{op_index, for, kind, name, path}], commit_message(치환됨), feedback, pending_included, operations(치환됨), warnings}`.
- **ID 할당**: 적용 대상 트리의 최댓값 + 1(유형은 카테고리별, 원인은 유형별). 빈 번호를 채우지 않는다(폐기·병합 원인도 남아 있으므로 번호 재사용이 없다). 임시 ID는 `NEW-(CAUSE|TYPE)-<n>` 토큰을 계획 전체 문자열에서 치환한다.
- **fixture 참조**: `verify-resolution` evidence, `verify-fix`·`update-fix` history의 `fixture`, `allow-cause`의 `fixture`에 같은 계획 `add-fixture`의 `path`를 쓰면 할당된 `fixtures/<이름>`으로 바꾼다(계획은 번호를 모르므로). `add-fixture`의 상대 `path`는 계획 파일 디렉토리 기준.
- **`update-fix`**: `fixed_in`은 브랜치 기준으로 병합(같은 브랜치면 build 갱신, 없으면 추가 — fix-submitted "빌드 추가" 흐름). `open`으로 되돌리는 이력 항목의 `date`·`by`는 계획의 `jira.date`(없으면 `started_at`의 날짜)와 적용 사용자.
- **새 원인 필드 순서**: `templates/cause.yaml`의 키 순서. `signatures_pending`은 `signatures` 뒤, `cp_evidence`는 값이 있을 때만 `related` 뒤(마스킹). `resolution_verification`은 항상 `{status: unverified(, method)}`로 시작.
- **새 유형 본문**: 계획 `body`(`## `로 시작하지 않으면 `## 증상`을 앞에 붙임) + `## 원인별 상세` + `### <첫 원인 ID> <title>` + 첫 원인 `body`.
- **Jira 기록**: `key, cause, date, occurred_on?, model, sw, android_version, carrier?, analyzed_by, note?` 순서. `note`·`cp_evidence`·fixture 내용은 마스킹 함수를 거친다(멱등).
- **reclassify**: 현재 `cause`가 계획 `from`과 다르면 거부(`reclassify-from`). `note`에 `; reclassified from <from>`을 덧붙인다.
- **drift 비교 대상**: `db_pr stage`가 사용자 clone에서 `db_add drift --onto <기준 SHA>`를 돈다(`base_sha`·기준 SHA 트리를 `git archive`로 꺼내 비교). 계획이 만드는 임시 ID 대상은 비교하지 않는다.
- **작업 디렉토리 구현 파일**: 계약의 `plan.json`·`state.json`·`included_pending/`·`wt/` 외에 `stage.json`(stage 결과, summary 입력), `regress.json`(stage의 회귀 결과를 `db_verify rules --regress-json`에 넘겨 회귀를 두 번 돌리지 않는다), `pr.json`(summary가 만든 PR 제목·본문·리뷰어, publish 입력). `state.json`의 `approved_hash`·`commit_message`는 stage가 `null`로 초기화하고 summary가 채운다. discard가 모두 지운다.
- **`approved_hash`**: 계약은 `GIT_INDEX_FILE=<임시> git add -A && git write-tree`. 구현은 그 앞에 `read-tree HEAD`를 둔다 — 빈 임시 index에서 시작하면 `core.filemode=false` 환경(Windows)에서 기존 100755 파일이 100644로 올라가 실제 커밋 트리와 달라진다. Ubuntu에서는 결과가 같다.
- **리뷰어**: 생성 파일(README·카테고리 README·STATS·CHANGELOG)은 원본 변경을 따라가므로 리뷰어 계산에서 뺀다. CODEOWNERS는 마지막으로 맞는 규칙이 이긴다. 바뀐 type.md의 `secondary_categories` 오너, `allow-cause` 대상 fixture 카테고리 오너를 더한다.
- **`publish`**: 검사 실패·push 거부(lease) → 1. push는 됐는데 `gh pr create/edit` 실패 → 2(`gh_error`, 계획의 `head_sha`는 기록). 기존 열린 PR은 `gh pr list --head <br>`로 찾고 `gh pr edit --title --body-file`로 고친다(바뀐 ID 반영). 포함된 pending 원본은 `included_pending/`으로 옮기고 계획 `included_pending`에 `{file, pr}`.
- **`find-plan --branch <br>`**(계약 밖, sync-pr 1~4번 보조): `<work_dir>/*/plan.json` 중 `pr.branch`가 같은 것. 있으면 `{job, plan, pr, remote_sha, remote_changed, remote_diff_stat}`, 없으면 `{found: false, manual_steps}`(06 §6.3 "계획이 없는 브랜치" 4단계). 아무것도 바꾸지 않는다(fetch만).
- **`cleanup`**: 대상은 lock 작업 밖의 `<job>/wt`·`<job>/draft`, 구현 파일(`state.json` 등), worktree가 없거나 이번에 지울 worktree에만 있는 `tt/*` 브랜치. `--older-than`은 값 없이 주면 90일.
- **`summary` 출력**: `{source, source_label, jira{key, origin, label}, branch{name, remote: 신규|갱신, remote_sha, base}, reviewers, open_prs, files[{kind, path, change}], ids, fixtures, drift_decisions, readme_preview, diff(50줄), diff_total_lines, diff_truncated, checks{lint, ids, mask, regress, build}, verification[{id, status, label, reason, review_required}], approval_needed, notes, commit_message, pr_title, push_allowed, push_note, pending_included, pr_body, approved_hash}`. `notes`에 record 표시("로그·코드 분석: 하지 않음", "시그니처 없음 — 매칭 불가, 리뷰 대상", "사용자 진술 — 카테고리 오너 리뷰 필요", "검증 못 함 — 리뷰 대상").
- **`db_verify rules` 뼈대의 R6**: `skipped`(사유 `해당 없음`). `--draft`는 lock 확인 뒤 `origin/<base>` 분리 worktree에 `db_add apply`, 끝나면 지운다.

### Phase 7 대조 후 보완 (2026-09-29, `contracts.md §3.2` `db_pr.py` 세부와 코드 대조)

사용자 확인 뒤 다음을 고쳤다. 계약을 고친 것은 `CHANGES.md`에도 적었다.

| # | 발견 | 결정 | 어디 |
|---|---|---|---|
| 1 | `db_pr.py`가 `--db`를 받지 않는다 (계약 공통 규칙은 "guard.py 제외 전부") | **계약에 예외 명시**. 사용자 clone·스냅샷·작업 worktree를 동시에 다루는 오케스트레이터라 `--db` 하나로는 어느 트리인지 모호하고, cwd 기반 기본값은 오히려 위험하다. 문서에 `db_pr`에 `--db`를 주는 호출도 없다 | `contracts.md §3.2` 공통 규칙 |
| 2 | `Lock.touch`가 **자기 작업의 만료된 lock**도 거부했다 → 확인 화면에서 4시간 넘게 기다리면 `publish`·`discard`가 2로 멈추고 lock을 못 푼다 | **코드를 계약에 맞춤**. 만료는 다른 작업이 `acquire`로 가져갈 수 있다는 뜻일 뿐이고, 같은 작업 키가 남아 있으면 아무도 안 가져간 것이다. 계약에도 한 문장 명시 | `db_pr.py` `Lock.touch`, `contracts.md` 세션 lock, `test_expired_own_lock_does_not_block_publish_or_discard` |
| 3 | `publish`의 "커밋 1개" 검사가 `HEAD^`만 봐서 첫 부모가 기준 SHA인 머지 커밋이 통과했다 | **코드 수정**: `HEAD^2`가 있으면 거부 | `db_pr.py` `publish`, `contracts.md` publish, `test_publish_rejects_changes_after_approval` 확장 |
| 4 | `stage` 7번에 `db_add check-ids`가 있는데 계약 목록에는 없다 (`07-workflow.md §Step 8`에는 있다) | **계약에 추가** (코드 유지). 기준 SHA에 다른 PR의 ID가 먼저 들어왔을 때 stage에서 잡아야 한다 | `contracts.md §3.2` stage 7번 |
| 5 | `preflight`의 `ahead_of_remote`가 bool이 아니라 커밋 수(원격 브랜치가 없으면 `origin/<base>` 기준) | 유지. 0이면 false로 읽으면 되고 확인 화면에 수를 보여줄 수 있다 | (기록만) |

### Phase 8에서 만든 것

| 산출물 | 경로 |
|---|---|
| git pre-commit | 이슈 DB `.githooks/pre-commit` (`#!/bin/sh`: config의 `plugin.scripts_path`에서 `db_precommit.py`를 찾아 `--db "$(git rev-parse --show-toplevel)"`로 실행. config·경로가 없거나 무효하면 차단하고 setup·CONTRIBUTING 안내) |
| git pre-push | 이슈 DB `.githooks/pre-push` (`#!/bin/sh` + python3: base 브랜치 대상 거부, `TT_PUBLISH_TOKEN` 없음 거부, `manual` 통과, 그 밖은 `<work_dir>/*/state.json`의 `approved_hash`와 대조) |
| pre-commit 오케스트레이터 | `plugin/scripts/db_precommit.py` (`config.py check --for dry-run` → `.cache/` → `db_lint`·`mask_pii --check`·`db_regress` `--staged` → 규칙 변경이면 `db_verify rules --staged` → `db_build --verify --staged`(`actions-build`면 생성 파일 staged 거부)) |
| Claude hook 판정 | `plugin/scripts/guard.py` (규칙 2~8, 레포 판별, 최선 노력 명령 파싱, Write/Edit 경로 판정) |
| hook 등록 | `plugin/hooks/hooks.json` (SessionStart `config.py sync-scripts-path`, PreToolUse `mcp__.*`·`Bash`·`Write\|Edit\|MultiEdit\|NotebookEdit` → `guard.py`) |
| Phase 8 테스트 | `tests/test_hooks.py` (12개) |

### Phase 8 완료 기준 확인 결과

`python3 tests/test_hooks.py` — **12개 전부 통과**. 전체 결과는 아래 "반입 체크리스트 상태".
Claude hook은 `guard.py`에 hook 입력 JSON을 직접 넣어 시험했다. **실제 Claude Code 세션에서 hooks.json이 로드되고
결정 필드가 먹는지는 빈 플러그인 실험(S1) 미확인**이다.

| 완료 기준 | 확인 | 어디서 |
|---|---|---|
| 수동 편집한 README 커밋 차단 (pre-commit) | ✅ ("db_build.py --write" 안내) | `test_precommit_blocks_manual_readme_pii_and_bad_scripts_path` |
| PII가 든 커밋 차단 (pre-commit, guard 규칙 3) | ✅ (마스킹된 토큰은 통과) | 같은 테스트, `test_guard_commit_checks_pii_and_generated_files` |
| `plugin.scripts_path` 무효 → 차단과 안내 (무효 경로·키 없음·config 없음) | ✅ | 같은 테스트 |
| `--no-verify`/`-n`/`-anm`/`--no-veri`(약어)/`-c core.hooksPath=` 우회 차단 | ✅ | `test_guard_blocks_hook_bypass_and_hookspath_changes` |
| `core.hooksPath` 변경·해제 차단(`--unset`, `unset`, 다른 값, 빈 값, `--remove-section core`), 정확히 `.githooks` 설정은 허용 → setup 재실행(`install-hooks`) 통과 | ✅ | 같은 테스트 |
| `core.hooksPath`가 unset·다른 값(`hooks`, `.githooks/`)이면 이슈 DB 커밋 차단 | ✅ | `test_guard_commit_requires_exact_hookspath` |
| worktree에서 커밋하면 그 worktree가 검사됨 | ✅ (clone에 staged로 남은 망가진 README를 보지 않고, worktree의 README 수정은 차단) | `test_precommit_in_worktree_checks_that_worktree` |
| read_tools에 없는 Jira 서버 도구 거부, 다른 MCP 서버 무영향 | ✅ (`mock-jira-2`처럼 접두어가 비슷한 서버도 무영향, read_tools 비면 전부 거부, mcp_server 없으면 경고만) | `test_guard_jira_read_only_by_server` |
| `cd <이슈 DB> && git commit --no-verify` 차단 | ✅ (`git -C`, `bash -c "cd … && …"`도) | `test_guard_blocks_hook_bypass_and_hookspath_changes` |
| `git push origin HEAD:refs/heads/main` 차단 | ✅ (`main`, `+HEAD:main`, `--all`, `:`, `--delete … main`, main에서 인자 없는 `git push`) | `test_guard_push_rules` |
| `python -c`로 한 main push는 guard를 지나치지만 pre-push가 거부 | ✅ | `test_prepush_token_and_base_branch` |
| `TT_PUBLISH_TOKEN` 없이 push → pre-push 거부, `db_pr publish` push와 `manual` 통과 | ✅ (틀린 토큰, 승인 토큰으로 다른 브랜치·다른 트리 push도 거부) | 같은 테스트 (+ Phase 7 테스트 전체가 실제 hook으로 publish 경로 통과) |
| Write로 사용자 clone 안 `type.md` 쓰기 거부, `<work_dir>/<키>/wt/` 허용 | ✅ (Edit·MultiEdit·NotebookEdit, 상대 경로, draft·스냅샷도 허용) | `test_guard_blocks_file_tools_in_user_clone_only` |
| config가 없으면 git 규칙 미적용 | ✅ | `test_guard_ignores_other_repos_and_missing_config` |
| 다른 레포에서는 어떤 git hook 규칙도 동작 안 함 | ✅ (commit·push·config·`-c core.hooksPath`·파일 쓰기) | 같은 테스트 |
| `TT_FORCE_VERIFY_EXIT=3` → pre-commit 경고 후 통과 | ✅ ("승인 필요 … needs-approval" 경고, 커밋 성공) | `test_precommit_needs_approval_warns_and_passes` |
| (그 밖) 이슈 DB push·`db_pr.py publish`는 `ask` | ✅ | `test_guard_push_rules` |

### Phase 8에서 바꾼 이전 산출물

| 대상 | 무엇을 | 왜 |
|---|---|---|
| `tests/fixtures/issue-db-sample/.githooks/pre-commit`·`pre-push` | Phase 1 스텁을 실제 hook으로 | Phase 8 할 일. 뼈대(`make_db_skeleton.py`)도 이것을 복사한다 |
| `plugin/scripts/db_verify.py` `rules --staged` | index를 임시 디렉토리로 꺼내 검사 | 뼈대는 `--staged`에서도 워킹 트리로 회귀를 돌렸다 → pre-commit이 unstaged 변경을 보게 된다(계약 "`--staged`는 index 기준" 위반) |
| `tests/helpers/workspace.py` | 생성 파일 커밋·main push를 hook 설치 **전**으로, `sync-scripts-path`(setup 2) 추가, 커밋은 `hook_env()`로 | 실제 pre-push가 main push를, pre-commit이 config 없는 커밋을 막는다 |
| `tests/test_db_pr.py` | 테스트가 직접 하는 커밋(`clone`·`wt`)에 `env=ws.hook_env()` | pre-commit이 테스트용 config를 읽게 |
| `tests/fixtures/README.md`, `tools/make_db_skeleton.py`, `tests/test_mocks.py` | "스텁" 표기 갱신 | 상태 표기 |
| `tests/fixtures/issue-db-{dup-id,empty-category,lint-errors,pending}/.githooks/` | `make_variant_dbs.py`로 다시 생성 | 샘플에서 만드는 변형 트리다 (`test_variant_trees_match_builder`) |

### Phase 8 구현에서 정한 세부 (계약 보완 후보)

- **guard는 `site-defaults.yaml`이 없어도 멈추지 않는다**: 계약은 "없으면 모든 스크립트가 종료 코드 2"다. 그런데 guard는
  모든 Bash·파일·MCP 도구 호출에 걸리는 PreToolUse hook이라 2로 끝나면(= 차단) 이슈 DB와 무관한 작업까지 막힌다.
  그래서 경고만 내고 사용자 config만으로 판정한다. 이때 커밋 검사(규칙 3·4)가 부르는 스크립트가 2를 내므로 이슈 DB
  커밋은 결국 거부된다. → **계약에 반영함** (`contracts.md §3.2` 설정 읽기, `08-safety.md §9`).
- **pre-push 토큰 검사를 계약보다 조금 강하게**: 계약은 "토큰이 `state.json`의 `approved_hash`와 같은지". 구현은 그 밖에
  (1) push하는 커밋의 트리 = 토큰, (2) 대상 브랜치 = 그 `state.json`의 `branch`, (3) 토큰으로 원격 ref 삭제 불가를 본다.
  pre-push는 작업 키를 모르므로 `<work_dir>/*/state.json` 전체에서 `approved_hash`가 같은 것을 찾는다.
  `base_branch`·`work_dir`는 사용자 config(없으면 `main`, `<home>/work`)에서 읽는다. config가 없어도 검사한다(토큰 없으면 거부).
  → **계약에 반영함** (`08-safety.md §9`, `contracts.md §3.2` publish).
- **pre-push는 플러그인 스크립트에 기대지 않는다**: 이슈 DB 안의 자기완결 스크립트(sh + python3 + pyyaml)다. 계약 표에
  pre-push용 스크립트가 없고, `plugin.scripts_path`가 무효해도 main push 차단은 동작해야 하기 때문이다.
- **pre-commit 출력**: `db_precommit.py`는 사람이 읽는 요약을 stderr에, 결과 JSON을 stdout에 낸다. hook 스크립트는 stdout을
  버린다. hook은 `--plugin-root "$(dirname "$scripts_path")"`를 넘긴다(git이 부른 프로세스에 `CLAUDE_PLUGIN_ROOT`가
  남아 있어도 config가 가리키는 플러그인을 쓰게).
- **`db_precommit`의 검사 순서·종료 코드**: 위 "만든 것" 순서. 하위에 1이 있으면 1, 2(실행 불가)가 있으면 2, 3만 있으면
  경고 후 0. 스키마·생성기 버전 불일치는 `config.py check --for dry-run`으로 막는다(06 §6.4 "직접 편집 브랜치의
  pre-commit"). `migrate/schema-v<N>` 브랜치에서 생성기 버전 불일치로 `db_build --verify`가 2를 내면 경고로 바꾼다.
  "규칙 변경"은 staged에 `parser-rules/*.yaml`, `<cat>/<유형>/type.md`, `fixtures/*.expect.yaml`이 있을 때다.
- **hooks.json**: PreToolUse는 matcher 3개(`mcp__.*`, `Bash`, 파일 도구)가 모두 같은 `guard.py`를 부른다. 규칙 3~7(Bash
  5종)은 한 번의 guard 호출에서 모두 판정한다(명령을 한 번만 파싱, 결정은 deny > ask). "8종"은 규칙 수다.
  SessionStart는 `config.py sync-scripts-path >/dev/null`(stdout이 세션 컨텍스트에 들어가지 않게). timeout은 Bash 180초
  (커밋 검사가 mask·build를 돈다), 나머지 30초.
- **guard 결정**: 허용일 때는 아무것도 내지 않는다(`allow`를 내면 사용자 권한 설정을 건너뛴다). push·`db_pr.py publish`는
  `ask`, 규칙 위반은 `deny`. guard 내부 예외는 MCP 도구면 `deny`(Jira 쓰기 차단은 guard가 유일한 장치), 그 밖은 통과
  (git hook이 진짜 강제).
- **명령 파싱 범위**: `;` `&&` `||` `|` `&` `(` `)` 줄바꿈으로 나눔, heredoc 본문 제외, 앞의 `VAR=값`·`env`·`command`·
  `exec`·`time`·`nohup` 제거, `cd`/`pushd` 추적, `sh|bash|zsh|dash|ksh -c` 안쪽(중첩 3단계까지), `git -C`·`--git-dir=`.
  커밋 옵션: `--no-verify`의 약어(`--no-v` 이상), 짧은 옵션 묶음 안의 `n`(`-m`·`-F`·`-C`·`-c`·`-t` 값 앞까지).
  push: `--no-verify` 금지(pre-push 우회), `--all`/`--mirror`/`--branches`와 matching(`:`) 거부, refspec 대상이 base면 거부,
  refspec이 없거나 `HEAD`면 현재 브랜치. config: `core.hooksPath` 키는 대소문자 무시, 쓰기는 값이 정확히 `.githooks`일
  때만, `--edit`·`core` 섹션 삭제·이름 변경 거부. `git -c core.hooksPath=…`는 커밋이 아니어도 이슈 DB면 거부.
- **파일 규칙**: 대상 경로를 cwd 기준으로 절대화하고 realpath·normcase로 비교한다. `work_dir` 아래는 clone 안에 있어도 허용.

### Phase 9에서 만든 것

| 산출물 | 경로 |
|---|---|
| 마이그레이션 실행기 | `plugin/scripts/db_migrate.py` (`--to <N> [--dry-run]`, `upgrade-plan <plan.json> [--write]`) |
| 예시 마이그레이션 v1→v2 | `plugin/scripts/migrations/0001_example_jira_tags.py` (Jira 스키마에 선택 필드 `tags` 추가 + 기존 Jira 파일에 `tags: []`, `upgrade_plan()`은 계획 그대로) |
| `migrate` 커맨드 | `plugin/commands/migrate.md` (dry-run 미리보기 → 브랜치 준비 → 실행 → `db_build --write` → validate → 커밋·push 안내) |
| v2 플러그인 루트 헬퍼 | `tests/helpers/runner.py:versioned_root(schema=, generator=)` (임시 루트의 `versions.py`를 고침) |
| Phase 9 테스트 | `tests/test_db_migrate.py` (16개) |

### Phase 9 완료 기준 확인 결과

`pytest tests` — **181개 전부 통과**(Phase 9 16개 포함).

| 완료 기준 | 확인 | 어디서 |
|---|---|---|
| 예시 마이그레이션이 샘플 DB를 새 버전으로 올림 | ✅ (config v2, Jira 파일 전부 `tags: []`, 새 스키마로 검증, 두 번째 실행은 "이미 v2") | `test_example_migration_upgrades_sample`, `test_already_current_and_second_run` |
| `migrate/schema-v<N>`에서 `migrate --to <N>` 뒤 `config.py check`·pre-commit·validate 통과 | ✅ (validate 스크립트: `db_lint --changed`·`db_regress --all`·`db_build --verify`. 마이그레이션 전에도 이 브랜치는 버전을 안 본다) | `test_migrate_branch_passes_check_precommit_and_validate` |
| 다른 브랜치 이름에서 `--to`는 종료 코드 2, 버전 불일치는 계속 차단 | ✅ (`feature/x`, `migrate/schema-v3`(`--to 2`), `migrate/ci-actions`, `migrate/schema-v2-extra`. 워킹 트리 그대로) | `test_other_branch_names_exit_2_and_stay_blocked` |
| `db_add apply`가 옛 `schema_version` 계획을 거부(종료 코드 2) | ✅ (메시지에 `upgrade-plan` 안내) | `test_apply_rejects_old_schema_plan` |
| `upgrade-plan`으로 올린 계획을 `sync-pr`가 새 스키마에 재적용 | ✅ (v1로 올린 PR → main에 v2 머지 → `stage`는 2로 거부 → `upgrade-plan --write` → `stage`·커밋·`publish` 성공, PR 브랜치 config v2) | `test_sync_pr_reapplies_upgraded_plan_on_new_schema` |
| 스키마 범위 밖·generator 불일치(local)는 `migrate/schema-v<N>` 말고 모든 쓰기 차단 | ✅ (too-old·too-new·generator-mismatch 모두 main/other에서 차단, migrate 브랜치는 통과, `actions-build`는 generator 영향 없음) | `test_migrate_branch_passes_...`, `test_too_new_schema_blocked_except_on_migrate_branch`, `test_generator_mismatch_blocked_except_on_migrate_branch` |
| (그 밖) 더러운 트리·untracked, clone 최상위 아님, 지원 안 하는 N, 체인 끊김, 다운그레이드, 마이그레이션 예외 → 종료 코드 2, 트리 그대로 | ✅ | `test_dirty_tree_...`, `test_db_must_be_clone_toplevel`, `test_plugin_version_and_missing_chain_exit_2`, `test_downgrade_and_broken_migration_leave_tree_untouched` |
| (그 밖) `upgrade-plan`: `--write` 백업, 이미 현재면 `current`, 계획이 DB보다 새로우면·`upgrade_plan()`이 없으면 2 | ✅ | `test_upgrade_plan_cli`, `test_upgrade_plan_refuses_without_upgrade_fn_or_newer_plan` |

### Phase 9에서 바꾼 이전 산출물

| 대상 | 무엇을 | 왜 |
|---|---|---|
| `docs/design/06-collaboration.md §6.4` | "직접 편집한 브랜치는 자기 브랜치에서 `db_migrate.py --to <N>`" → 새 스키마 형식으로 직접 고침 | `--to`는 `migrate/schema-v<N>`에서만 돌아서 계약(`contracts.md §3.2`)과 어긋났다 |
| `docs/design/contracts.md §3.2` `db_migrate` 행 | 아래 "구현에서 정한 세부" 반영 | 계약 보완 (`CHANGES.md`) |
| `plugin/scripts/db_migrate.py` | 워킹 트리에 있던 미추적 파일을 새로 씀 | 이전 세션의 미완성 상태 |

### Phase 9 구현에서 정한 세부 (계약 보완 후보)

- **`--to N > 플러그인 SCHEMA_VERSION`은 거절(종료 코드 2)**: 배포 플러그인이 v1이면 v2 DB를 만들어도 자기가 못 읽는다. 그래서 예시 마이그레이션(v1→v2)은
  **v2로 고친 임시 플러그인 루트**로만 시험한다. 실제 첫 마이그레이션이 생기면 그 PR이 `SCHEMA_VERSION`을 함께 올리고 예시 파일은 지운다.
- **`--dry-run`은 브랜치·깨끗함을 보지 않는다**(아무것도 안 쓰므로). 실제 실행만 정확한 브랜치 이름 `migrate/schema-v<N>` + 깨끗한 트리 + clone 최상위를 요구한다.
  `config.py check`의 예외는 `migrate/schema-v<숫자>` 패턴 전체라 `migrate/schema-v3`에서는 `--to 2`가 2를 내도 check는 통과한다(이름만 본다는 계약 그대로).
- **메모리에서 모두 적용 후 한 번에 쓴다**: 마이그레이션이 던지면 트리는 그대로. 마이그레이션은 `tree.read/write/delete/exists/glob`만 본다(`.git`·`.cache` 쓰기 금지).
- **`generator_version` 동기화**: `db_build --write`가 두 버전이 같아야 돌므로 `--to`가 `ci_mode != actions-build`일 때 `generator_version`도 플러그인 값으로 맞춘다.
- **`upgrade_plan()`은 `schema_version`을 안 건드린다**: db_migrate가 단계마다 `TO_VERSION`으로 올린다. 어느 단계에든 `upgrade_plan()`이 없으면 전체가 2(계획을 다시 만든다).
- **`upgrade-plan`의 대상 버전은 `--db`의 `schema_version`**(sync-pr는 `<work_dir>/_snapshot`)이다. lock·worktree를 만들지 않는다.
- **`migrate` 커맨드는 `db_pr`를 부르지 않는다**(계획·lock·PR 없음). push는 안내만 한다.
- **테스트 인프라**: 플러그인이 새 버전이 되면 git pre-commit hook이 보는 `plugin.scripts_path`도 새 루트여야 한다(`config.py sync-scripts-path`). sync-pr 테스트가 이를 다시 실행한다. 실제 사용자는 SessionStart hook이 한다.

### Phase 10에서 만든 것

| 산출물 | 경로 |
|---|---|
| 검증 (R1~R6 완성, `resolution`·`fix` 판정) | `plugin/scripts/db_verify.py` |
| 규칙 변경 계산·의존 그래프 | `plugin/scripts/common/rulediff.py` |
| R5 이벤트 diff | `plugin/scripts/db_regress.py --events-diff <ref>` (`events_diff()`는 `db_verify`와 공유) |
| 매처가 호출자의 평가기를 쓰게 함 | `plugin/scripts/match_signatures.py` (`match(..., evaluator=)`, `evaluator_for()`) |
| lint 검증 규칙 | `plugin/scripts/db_lint.py` `fixed-without-verification`, `fixed-without-trace` |
| 검증용 이슈 DB | `tests/fixtures/issue-db-verify/` (CALL-001-01 fix-submitted, CALL-001-02 추가) |
| verify 입력 로그 | `tests/fixtures/verify-logs/` (수정 후·재발·증상만 남음·시나리오 없음) |
| 시나리오 | `tests/mocks/scenarios/call-001-02-positive.yaml`, `verify-call-*.yaml` 4개 |
| 변형 생성 | `tests/helpers/make_variant_dbs.py` (`issue-db-verify`, `verify-logs` 추가) |
| Phase 10 테스트 | `tests/test_db_verify.py` (11개) |

### Phase 10 완료 기준 확인 결과

`pytest tests` — **192개 전부 통과**(Phase 10 11개 포함. 전체 실행에서 collect 뒤 고친 `test_db_pr` 1개는 따로 재실행해 통과).

| 완료 기준 | 확인 | 어디서 |
|---|---|---|
| 너무 넓은 원인 시그니처(음성 fixture·같은 카테고리 다른 유형 양성에서 C=1) → R3 | ✅ (CALL-001.none, 다른 유형 DATA-002-01이 DATA-001-01.log를 잡음 + `allow-cause` 초안) | `test_broad_cause_signature_and_widened_fixed_cause_are_blocked` |
| 다른 카테고리 양성에서 C=1 → R4 + `allow-cause` 초안, `also_allowed` 넣으면 R2·R3·R4 통과, 빠진 fixture는 여전히 실패 | ✅ (IMS-001-01·recurrence) | `test_cross_category_hit_needs_also_allowed_and_scoring_does_not_matter` |
| `cause_weight 0.5`·`confidence.medium 0.7`로 바꿔도 R2·R3·R4·`db_regress` 같음 | ✅ | 같은 테스트 |
| 새 유형 증상 시그니처가 다른 유형 음성에서 S=1 → R3, fixture 표시 | ✅ | `test_new_type_symptom_hitting_other_negative_fails_r3` |
| extractor만 바꿔도 참조 시그니처의 원인이 R1·R2 대상 | ✅ (`why: depends:extractors:ims-dial-attempt`) | `test_extractor_change_selects_dependents_and_event_change_needs_approval` |
| 기존 이벤트를 바꾸는 extractor 수정 → R5 `needs-approval`(3) | ✅ (`ims-registered` fields 제거, R4 통과, `--events-diff` 결과 확인) | 같은 테스트 |
| CALL-001-01 수정 후 로그 → `fix` passed, 손으로 쓴 `verify-fix passed`+`add-fixture fixed` 계획 stage → fixed, `CALL-001-01.fixed.<build>.log` | ✅ | `test_fix_judgements_on_fix_submitted_cause`, `test_verify_fix_plans_reach_stage` |
| 재발 로그 → failed, 계획 적용 → open, `ref`·`fixed_in`이 history로 보존·비움 | ✅ | 같은 두 테스트 |
| 증상만 남은 로그 → partial + 다른 원인 후보(CALL-001-02), 계획 적용 → fix-submitted 유지 + partial 이력 | ✅ | 같은 두 테스트 |
| 시나리오 흔적 없는 로그 → unknown | ✅ | `test_fix_judgements_on_fix_submitted_cause` |
| scenario/recovery 모두 없는 코드 수정 유형 → 판정 없이 unknown(필수 시그니처 없음) | ✅ | `test_fix_stops_without_build_or_required_signatures_and_lint_rules` |
| `fixed_in` 이전 빌드, 빌드 없는 `fixed_in` → 종료 코드 2. 빌드 없는 `fixed_in`에 `verify-fix passed` 계획 → 거부 | ✅ (`fixed-in-build-missing`) | 같은 테스트, `test_fix_judgements_on_fix_submitted_cause` |
| `resolution`: recovery 없음 + 시나리오 흔적 없음 → unknown | ✅ (CALL-001-02) | `test_fix_judgements_on_fix_submitted_cause` |
| record 계획(`new-cause`+recovery)에 `resolution --cause NEW-CAUSE-1 --plan --draft` → passed, 이어서 `add-fixture resolved`+`verify-resolution` 계획 stage → verified, lint 통과 | ✅ (DATA-001-03, draft는 지워짐) | `test_record_new_cause_resolution_draft_then_verified_stage` |
| 카테고리 모든 음성 fixture에 맞는 scenario → R1 흔적 실패. 음성 fixture 없으면 `skipped: 음성 fixture 없음`(`review_required`), pass 아님 | ✅ | `test_trace_signature_matching_every_negative_fails_r1` |
| `fixed` 원인 재검증이 증상만 남으면 partial, 적용하면 fixed 유지 + partial 이력 | ✅ (샘플 CALL-001-01) | `test_recheck_of_fixed_cause_partial_keeps_fixed` |
| 양성 fixture 없는 새 원인 → R1·R2 `skipped: fixture 없음`(`review_required`). pending 원인 → R1~R3 `skipped: 시그니처 없음(pending)` | ✅ | `test_new_cause_without_fixture_and_pending_cause_are_skipped_not_passed` |
| 수정 후 fixture가 있는 원인의 시그니처를 넓히면 R3·R4 차단 | ✅ (샘플 `CALL-001-01.fixed.*`) | `test_broad_cause_signature_and_widened_fixed_cause_are_blocked` |
| (그 밖) `update-fix` open 되돌림 이력, `verify-resolution` pending 거부, `db_lint` 검증 없는 fixed·흔적 없는 코드 수정 fixed | ✅ (앞 둘은 Phase 7 `test_verify_resolution_and_update_fix_rules`) | `test_fix_stops_without_build_or_required_signatures_and_lint_rules` |
| (그 밖) R6 `--extra`·`--extra-normal`, R6 fail은 종료 코드 0 | ✅ | `test_record_new_cause_resolution_draft_then_verified_stage` |

### Phase 10에서 바꾼 이전 산출물

| 대상 | 무엇을 | 왜 |
|---|---|---|
| 이슈 DB `schema/plan.schema.json` (샘플·변형) | `verify-fix`의 `verification.fixture`는 `passed`만 필수 | 05 §5.12 (2)는 실패 때 recurrence fixture를 "넣을지 묻는다"(선택)이고 partial은 넣을 fixture가 없다. Phase 7 스키마가 항상 필수로 두었다 |
| `plugin/scripts/db_add.py` `op_verify_fix` | fixture가 있을 때만 경로 치환·존재 검사 | 위와 같음 |
| `plugin/scripts/db_regress.py` | `prepare()`·`match_errors()`·`parse_logs()` 분리 (동작 같음) | `db_verify`가 같은 판정을 같은 프로세스에서 쓴다 |
| `tests/test_db_pr.py` `test_rule_that_changes_existing_fixture_is_blocked_by_r4` | `not-implemented` 대신 실제 R1·R3·R5 값 | 뼈대 가정 |
| `tools/list_site_todos.py` | `issue-db-verify` 제외 | 샘플 사본 |
| `docs/design/contracts.md §3.2·op 표·상태 값`, `05 §5.12 (1)`, `03 §5.7 (4)` | 아래 세부 반영, 뼈대 문구 정리 | 계약 보완 (`CHANGES.md`) |

### Phase 10 구현에서 정한 세부 (계약 보완 — `contracts.md §3.2`에 반영함)

- **대상 계산은 기준 트리와의 의미 비교**다(`common/rulediff.py`). `--plan`의 기준은 대상 트리 `HEAD`(draft·작업
  worktree 모두 기준 SHA에 있고 계획은 커밋 전 워킹 트리에 있다). 그래서 `--plan`/`--changed`/`--staged`가 같은 코드다.
  계획 op를 해석하지 않으므로 `sync-pr` 재적용이나 직접 편집에도 같은 대상이 나온다.
- **R1 파서 검사**: 조건마다 "소유자의 양성 계열 fixture 중 하나에서 추출"이면 통과(조건 단위, 창 무시). 새로 넣은
  OR 시그니처가 기존 fixture 어디에도 안 나오면 실패한다(그 시그니처를 보여주는 fixture를 넣으라는 뜻).
- **R3 원인 대상 fixture**에 같은 카테고리의 음성 fixture 전부(그 유형 것만이 아니라)를 넣었다. 검사할 fixture가 없으면
  `skipped: 음성 fixture 없음`(리뷰 대상)으로 공허한 통과를 막았다.
- **R6 `fail`은 종료 코드 0**(`blocking: false`): 설계가 "fail이어도 사용자가 진행을 고를 수 있다"라서 stage를 막지 않는다.
  정상 표본을 줄 방법이 계약에 없어서 `--extra-normal`을 더했다.
- **`fix`의 failed는 흔적 검사보다 먼저**: 원인 시그니처 충족(재발) 자체가 시나리오를 수행한 근거다.
- **`fix`의 빌드 비교 불가**(`build_compare` 규칙 없음·`--build` 없음)는 중단하지 않고 `build_check`로 알린다(설계: "사용자에게 묻는다").
- **`--plan --draft` 판정은 같은 draft에서 R1~R6도 돌리고**, R1 흔적 검사 실패면 판정을 `withheld`로 둔다.
- 판정 결과에 **`suggested_ops`**(계획 op 초안)를 붙였다. 스킬(Phase 13)이 fixture 경로(`parse_logcat cut`)와 아이디를 채운다.

### Phase 10에서 발견한 설계 문서 간 긴장 (사용자 판단 필요)

- `03-issue-db.md §5.7 (2)` 표의 recovery 좋은 예 `must_match: ['RILJ.*>\s*SETUP_DATA_CALL']`는 R1 흔적 검사
  ("scenario·recovery 모두 그 카테고리 음성 fixture **전부**에서 충족되지는 않음")를 통과하지 못한다. 음성 fixture는
  정상 로그라서 정상 데이터 연결의 SETUP_DATA_CALL이 모두 들어 있기 때문이다(샘플 DATA-001.none·none.2). 구현은 R1
  규칙을 그대로 따랐고, 테스트의 recovery는 원인에 특정한 흐름(SIM LOADED → 평가 허용)으로 썼다. 선택지:
  (a) 예시를 "원인에 특정한 정상 흐름"으로 고친다, (b) R1 음성 검사를 scenario에만 적용한다.
- **결정 (2026-09-29, 사용자)**: (a). R1 규칙은 그대로 두고 `03 §5.4 (1)` 예시 주석과 `§5.7 (2)` 표의 recovery 좋은 예·나쁜 예를 고쳤다(`CHANGES.md`).

### Phase 11에서 만든 것

| 산출물 | 경로 |
|---|---|
| 월간 리뷰 리포트 (§6.6 항목 17개) | `plugin/scripts/db_review.py` (`[category] [--out] [--as-of] [--json]`, 읽기 전용) |
| `review` 커맨드 | `plugin/commands/review.md` (카테고리 묻기 → 리포트 → 정리 방법·병합 op 안내) |
| 검색·옛 ID 연결 | `plugin/scripts/db_search.py` (ID·Jira·키워드, `merged-into:` 체인, `Renumbered:` 트레일러). `search` 커맨드 연결은 Phase 12 |
| 리뷰·STATS 공통 판정 | `plugin/scripts/common/quality.py` (발생일·급증·fixture 없음·fixed 전환 불가·수정 상태 누락 등) |
| git 이력 조회 | `plugin/scripts/common/history.py` (상태가 시작된 날, `Renumbered:` 트레일러) |
| STATS 완성 | `plugin/scripts/db_build.py` — 유형별 건수 표 추가, 급증·fixture 없음·fixed 전환 불가를 `common/quality.py`로 |
| 병합 절차 지원 | `plugin/scripts/db_add.py` `add-fixture`의 `path`에 이슈 DB 기준 경로(옛 fixture) 허용, 이슈 DB `schema/plan.schema.json` `set-status`의 `id`·`merged-into:` 대상에 temp_id 허용 |
| 리뷰 변형 이슈 DB | `tests/fixtures/issue-db-review/` (`make_variant_dbs.py`의 `review()`, 케이스 목록 `REVIEW_CASES`) |
| 이슈 DB 문서 | 샘플 `docs/review-guide.md` §4 병합 op 순서·경로 |
| Phase 11 테스트 | `tests/test_db_review.py` (6개), `tests/test_db_search.py` (3개) |

### Phase 11 완료 기준 확인 결과

`pytest tests` — **201개 전부 통과**(Phase 11 9개 포함).

| 완료 기준 | 확인 | 어디서 |
|---|---|---|
| 오래된 unresolved | ✅ MOCK-1105(80일) 걸림, MOCK-1104(24일) 안 걸림 | `test_review_report_catches_every_planted_case` |
| 낮은 수락률 | ✅ `DATA-001-01/data-disabled` 2/6. 1위 3건인 `roaming-disabled`(1/3)는 표본 부족이라 안 걸림 | 같은 테스트, `test_manual_feedback_is_not_in_acceptance` |
| 중복 후보 | ✅ DATA-001 ↔ DATA-002 (동시 매칭 fixture 3개 + 제목 유사도 0.84). CALL-001 ↔ IMS-001 동시 매칭은 `related`로 이어져 있어 빠짐 | 같은 테스트 |
| 지원 종료 버전 / 빈 `android_versions`는 아님 | ✅ DATA-002-01 `["14","15"]`만. `[]`인 DATA-001-02 등은 안 걸림 | 같은 테스트 |
| fixed 전환 불가 | ✅ DATA-002-02(vendor-ril), IMS-001-01, SMS-001-01 | 같은 테스트 |
| 시그니처 없는 원인 / fixture 없는 원인 | ✅ DATA-001-03 / DATA-002-01·02 (pending 원인은 fixture 없음에 넣지 않음) | 같은 테스트, STATS는 `test_stats_on_review_db` |
| 사용자 진술만 있는 해결책 | ✅ DATA-001-03(`method`), DATA-001-02(MOCK-1103 `note`) | 같은 테스트 |
| `also_allowed` 누적 | ✅ NETWORK-001-01 fixture(3개), IMS-001-01(다른 유형 fixture 5개) | 같은 테스트 |
| 급증 / 과거 `occurred_on` 일괄 record는 급증 아님 | ✅ NETWORK-001-01 걸림, SMS-001-01(기록 2026-10-18, 발생 2025년) 안 걸림. STATS도 같다 | 같은 테스트, `test_stats_on_review_db` |
| `decision: manual`은 수락률에서 빠짐 | ✅ 피드백 13건 중 manual 4건 제외, 분모 6 | `test_manual_feedback_is_not_in_acceptance` |
| (§6.6 나머지) 오래 안 쓰인 원인, 수정 필요 누적, 수정 상태 누락, 빌드 없는 fix-submitted, 수정 검증 실패·부분 이력 | ✅ | `test_review_report_catches_every_planted_case` |
| (§6.6 나머지) 해결책 미검증 방치, 수정 검증 대기 방치 — git 이력 기준, 이력 없으면 "기간 확인 불가" | ✅ 2026-06-01/2026-10-10 날짜 지정 커밋. 해결책 문구가 바뀐 DATA-001-02, 최근 fix-submitted가 된 DATA-002-02는 안 걸림, 커밋 전 변경은 `uncommitted` | `test_stale_periods_come_from_git_history` |
| 카테고리 범위·오너, 읽기 전용, `--out` Markdown | ✅ | `test_category_scope_and_owners`, `test_review_is_read_only_and_writes_markdown` |
| 병합 후 `db_search`가 옛 ID → 새 ID | ✅ `move` 계획(new-cause → add-fixture(옛 fixture DB 경로) → set-status ×2 → reclassify)이 `db_pr stage`의 lint·회귀·R1~R6을 통과해 PR·머지. `DATA-002-01` → `current: DATA-001-03`, `DATA-002` → `DATA-001`, `MOCK-1201` → 새 원인 | `test_move_merges_type_and_search_follows_old_ids` |
| `Renumbered:` 트레일러 커밋 뒤 옛 ID → 새 ID | ✅ `issue-db-dup-id`에서 나중 DATA-001-03을 DATA-001-04로 옮긴 커밋. 옛 ID로 찾으면 원래 주인과 옮겨간 엔티티가 함께, 새 ID로 찾으면 거꾸로 | `test_renumbered_trailer_links_old_and_new_id` |
| STATS §6.7 항목 | ✅ 유형별 건수 추가(나머지는 Phase 5에 있었음) | `test_stats_on_review_db` |

### Phase 11에서 바꾼 이전 산출물

| 대상 | 무엇을 | 왜 |
|---|---|---|
| 이슈 DB `schema/plan.schema.json` (샘플·변형) | `set-status`의 `id`와 `merged-into:` 대상에 `NEW-CAUSE-<n>`/`NEW-TYPE-<n>` 허용. `reclassify.to`에 `<유형 ID>:unresolved` 허용(사용자 결정 (a)) | op 표는 둘을 temp_id 치환 대상으로 적었는데 스키마가 막았다. 병합 계획(`new-cause` 뒤 옛 원인 `merged-into:<temp_id>`)이 거부됐다 |
| `plugin/scripts/db_add.py` `add-fixture` | `path`가 계획 디렉토리에 없으면 이슈 DB 기준 상대 경로로 찾음(적용 중인 트리에서 읽고 트리 밖은 거부) | §6.6 병합 op "옛 fixture 파일 경로를 `path`로" |
| `plugin/scripts/db_build.py` STATS | 유형별 표 추가. "fixture 없는 원인"에서 pending 원인 제외(§6.6 정의·`db_lint`와 맞춤. 샘플 결과는 같음) | §6.7 "카테고리, 유형, 원인별", §6.6 "R1·R2가 `skipped: fixture 없음`인 원인" |
| `tools/list_site_todos.py` | `issue-db-review` 제외 | 샘플 사본 |
| `docs/design/contracts.md` | `db_review`·`db_search` 옵션·출력, `db_review.py` 세부, op 표 `set-status`·`add-fixture` | 계약 보완 (`CHANGES.md`) |

### Phase 11 구현에서 정한 세부 (계약 보완 — `contracts.md §3.2`·op 표에 반영함)

- **리뷰 기준일은 실행일**(`--as-of`로 바꿈). STATS처럼 "가장 최근 Jira `date`"를 쓰면 Jira가 한동안 안 들어올 때
  방치 기간이 늘지 않는다. 리뷰는 생성 파일이 아니라서 결정성 규칙 대상이 아니다.
- **방치 기간은 git 이력**: `fix`·`resolution_verification`에 상태 전환 날짜가 없다. `type.md`를 바꾼 커밋을 거슬러
  그 상태가 이어진 가장 오래된 커밋의 커미터 날짜를 쓴다. 이슈 DB가 git 최상위가 아니면(다른 레포 안의 시험 트리)
  이력을 쓰지 않고 "기간 확인 불가"로 낸다. pending 원인은 검증할 수 없으므로 "해결책 미검증 방치"에서 뺐다.
- **중복 후보**: "동시 매칭"과 "제목 유사도"를 OR로 본다(둘 다면 둘 다 표시). 제목만으로는 같은 카테고리, 0.8 이상
  (짧은 한국어 제목끼리는 "…되지 않음" 때문에 0.6~0.7이 흔하다). 원인끼리 `related`·fixture `also_allowed`로 이미
  이어진 유형 쌍의 동시 매칭은 뺐다(샘플 CALL-001 ↔ IMS-001이 매달 나오지 않게).
- **수정 필요 누적**은 문턱 없이 open 원인을 Jira 건수 순으로 낸다(설계에 "많은"의 기준 키가 없다).
- **`db_search`**: 질의 모양으로 종류를 정한다(유형/원인 ID, `jira_key_regex`, 그 밖은 키워드). `Renumbered:` 트레일러로
  찾은 옛 ID는 원래 주인이 계속 쓰므로 두 엔티티를 함께 보인다. 유형 ID로 찾으면 소속 원인의 트레일러도 보인다.

### Phase 11에서 발견한 설계 문서 간 긴장 (사용자 판단 필요)

1. **병합되는 유형의 `unresolved` Jira를 옮길 op가 없다.** §6.6 유형 병합은 "Jira 파일은 새 유형 디렉토리로 이동"인데
   `reclassify`의 `to`는 원인 ID(또는 temp_id)만 받는다. 원인 미확정 Jira는 옛(merged) 유형 디렉토리에 남는다(회귀·매칭에는
   영향 없음, README·검색에서는 옛 유형 소속으로 보임). 선택지: (a) `reclassify`의 `to`에 `"<유형 ID>:unresolved"`를 허용,
   (b) 그대로 두고 리뷰 가이드에 "원인을 정한 뒤 옮긴다"고 적는다.
   - **결정 (2026-09-29, 사용자)**: (a). `reclassify.to`에 `<유형 ID>:unresolved`(temp_id 유형 포함)를 허용하고, `from: unresolved`만
     받는다. `note`는 `reclassified from <옛 유형 ID>:unresolved`. 스키마·`db_add`·계약·리뷰 가이드·`review` 커맨드에 반영,
     `test_move_merges_type_and_search_follows_old_ids`가 확인한다.
2. **`GENERATOR_VERSION`을 올리지 않았다.** STATS에 유형별 표가 늘어 생성 결과가 바뀌었다. 규칙은 "생성 결과가 바뀌는
   플러그인 변경은 항상 올린다"지만, 아직 배포된 이슈 DB가 없어(사외 초안) 1로 두었다. 올리면 샘플·변형·뼈대의
   `generator_version`도 함께 바뀐다. 파일럿 전 첫 배포 버전을 1로 두는 것이 맞는지 확인이 필요하다.
   - **결정 (2026-09-29, 사용자)**: 1로 둔다. **`GENERATOR_VERSION`(와 `SCHEMA_VERSION`) 증가 규칙은 첫 배포(S-7 파일럿)부터
     적용한다.** 그 전(사외 초안·사내 보완 중)의 생성 결과 변경은 모두 v1에 포함한다. 사내에서 이 규칙을 다시 따지지 않는다.

### Phase 12에서 만든 것

| 산출물 | 경로 |
|---|---|
| 커맨드 9개 추가 (총 12개) | `plugin/commands/{analyze,record,sync,search,sync-pr,preview,validate,verify-fix,fix-submitted}.md` (기존 `setup`, `review`, `migrate`) |
| 스크립트만 쓰는 커맨드 | `sync`, `search`, `preview`, `sync-pr`, 인자 없는 `validate` (스킬 없이 동작) |
| 스킬 연결 틀 | `analyze`, `record`, `verify-fix`, `fix-submitted`, `validate --cause` (Phase 13 스킬 `telephony-triage`를 부르는 틀만) |
| 오프라인 재현 평가 | `tools/offline_eval.py <라벨셋.yaml> [--db] [--plugin-root] [--json]` |
| 합성 라벨셋 | `tests/fixtures/offline-eval-sample.yaml` (8건: 정답 원인 6, unresolved 1, 일부러 틀린 라벨 1) |
| Phase 12 테스트 | `tests/test_commands.py` (13개) |

### Phase 12 완료 기준 확인 결과

| 완료 기준 | 확인 | 어디서 |
|---|---|---|
| `commands/` 12개가 `01 §3`·`09 §10`과 같다 | ✅ | `test_command_files_match_design_lists` |
| 스킬 연결 5개 로드·인자 힌트 | ✅ frontmatter `description`·`argument-hint` 검사. 실제 Claude Code 로드는 **미확인(S1)** | `test_every_command_has_description_and_argument_hint_where_it_takes_args` |
| `sync`: 끝에 닫힌 PR의 오래된 작업 디렉토리 후보, 확인 전 삭제 없음 | ✅ 본문 스크립트 순서(lock → snapshot → `db_build --cache-only` → release → `cleanup --dry-run --older-than`)를 그대로 실행. 닫힌 PR·120일 전 mtime 작업 디렉토리가 후보로 나오고 `--yes` 전에는 남으며, 열린·최근 PR은 후보가 아님 | `test_sync_sequence_*` |
| `validate`(인자 없음): lint·전체 회귀·R1~R5 | ✅ 본문 순서(`db_lint`·`mask_pii`·`db_regress --all`·`db_verify rules`·`db_build --verify`)를 실행. 깨끗한 DB는 전부 0, 양성 fixture를 깨면 회귀가 잡음, 워킹 트리를 안 바꿈 | `test_argless_validate_chain_*`, `test_validate_changes_are_read_only` |
| `offline_eval.py`가 합성 라벨셋에서 정확도 표 | ✅ 1위 정확도·상위 3 포함률 85.7%(6/7, 일부러 틀린 라벨 1건), 오탐률 0% | `test_offline_eval_*` |
| `setup`, `search`, `sync-pr`, `preview`, `review`, `migrate` 동작 | 스크립트 부분은 각 Phase 테스트(`test_db_pr`·`test_db_search`·`test_db_review`·`test_db_migrate`·`test_db_build`)로 확인. **플러그인 로드 상태의 커맨드 실행은 S1 실험 전이라 미확인** | — |

### Phase 12 구현에서 정한 세부

- **라벨셋 형식**(`tools/offline_eval.py` 머리말): 최상위 `db`(선택)·`tz`·`year`·`minutes`, 항목마다 `key`, `logs`(라벨셋 파일 기준 경로),
  `occurred_at`(타임존 있는 ISO), `sw`·`summary`·`description`(선택), `expect`(원인 ID 또는 `unresolved`). 설계는 "Jira 키,
  로그 경로, 정답 원인 ID 또는 unresolved"만 정했고 발생 시각(파서 `--around`에 필요)은 빠져 있어 항목에 넣었다.
- **`--jira-file`은 받지 않는다**: 설계는 "`analyze --dry-run --jira-file`과 같은 경로"인데 `jira-file` 형식이 느슨해(`field_map` 값이
  사내 필드 이름에 묶임) Jira 메타를 라벨셋에 직접 적는다. 매처 입력은 같은 `--jira-meta` JSON이라 결과 경로는 같다.
- **플러그인 루트**: `--plugin-root` > `plugin/site-defaults.yaml`이 있으면 `plugin/` > 없으면 테스트 헬퍼 루트를 임시로 만든다
  (사외 시험용). 런타임 코드가 아니라 개발 도구라 이 분기는 허용한다.
- **지표**: 1위 정확도·상위 3 포함률은 정답이 원인 ID인 항목만, 오탐률은 정답이 `unresolved`인 항목만 분모로 한다. 파서·매처가
  실패한 항목은 "오류"로 표에 남기고 분모에서 뺀다.
- **`sync-pr` 커맨드는 스킬에 기대지 않는다**: 완료 기준이 "지금 동작"이라 9단계를 본문에 자기완결로 적었다.
- **`${CLAUDE_PLUGIN_ROOT}` 치환(S1)은 아직 확인하지 못했다.** 커맨드 본문은 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py"`를
  쓴다. 치환이 안 되면 config의 `plugin.scripts_path`로 바꾼다.

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
| 실행 파일 탐색 | `subprocess`가 자식 `PATH`로 찾는다 | Windows `CreateProcess`는 **부모 `PATH`** 로 찾고 `.cmd` 스텁을 못 찾는다. 테스트는 `mock_env.resolve()`로 절대 경로를 넘긴다. Phase 6부터 **런타임 코드는 `shutil.which("gh")`로 PATH의 `gh`를 찾아** 부른다(`common/ghcli.py`) | 없음. Ubuntu에서는 PATH의 `gh`와 같다 |
| 출력 인코딩(자식 프로세스) | UTF-8 | 이 PC 경로에 한글이 있어 `git` 출력을 cp949로 디코딩하면 실패한다. 스크립트의 `subprocess` 텍스트 호출은 모두 `encoding="utf-8"`을 지정한다 | 없음 |
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
9. `config.py`는 Phase 6에서 전부 구현했다(D0에는 site-defaults 로드와 종료 코드 2 경로만 있었다).
10. 마스킹 함수는 Phase 4에서 만들었고, 골든 테스트의 마스킹 민감도 검사도 그 함수를
    쓴다. 탐지 규칙(키 이름·형식)은 일반적인 Android 로그 기준이고 사내 로그의 오탐·누락은
    S13에서 확인한다.
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
19. 마스킹 IMSI 옵션 "MCC/MNC 유지"(`08-safety.md §8` 표)와 SIP 도메인 유지 옵션은 만들지
    않았다. 지금은 IMSI 전체를 토큰으로 바꾸고, SIP URI는 사용자 부분만 바꾸고 도메인은 둔다.
    설정 키가 정해지면(`mask.*`) 더한다.

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

`python3 tools/list_site_todos.py`로 갱신한다(Windows 콘솔에서는 `PYTHONIOENCODING=utf-8`). 변형 이슈 DB(`issue-db-lint-errors` 등)는 샘플의 사본이라 세지 않는다. 2026-09-29(Phase 11 끝) 기준 **59곳**:

### S1 (3곳)
- `plugin/scripts/common/mcptools.py:8` — 사내 Claude Code 버전에서 확인한다.
- `plugin/scripts/guard.py:11` — hook 입력 필드(`tool_name`, `tool_input.command|file_path|notebook_path`, `cwd`)와 권한 결정 출력
- `tests/mocks/skills/data-analyzer/SKILL.md:63` — 스킬 이름과 호출 방식 확인.

### S3 (1곳)
- `plugin/scripts/guard.py:13` — 플러그인 hook에 보이는 MCP 도구 이름이 `mcp__<server>__<tool>`이고 `<server>`가 config

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

### S9 (23곳)
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
- `tests/mocks/scenarios/call-001-02-positive.yaml:2` — , TODO(SITE:S10)
- `tests/mocks/scenarios/call-drop.yaml:2`
- `tests/mocks/scenarios/data-001-01-positive.yaml:2`
- `tests/mocks/scenarios/data-001-02-roaming.yaml:2`
- `tests/mocks/scenarios/data-001-03-pending.yaml:4`
- `tests/mocks/scenarios/data-setup-error.yaml:2`
- `tests/mocks/scenarios/dual-sim-ril.yaml:7` — TODO(SITE:S20)
- `tests/mocks/scenarios/network-001-01-positive.yaml:2`
- `tests/mocks/scenarios/sim-001-01-positive.yaml:2`
- `tests/mocks/scenarios/sim-absent.yaml:2`
- `tests/mocks/scenarios/sms-001-01-positive.yaml:2`

### S10 (2곳)
- `tests/mocks/scenarios/ims-001-01-positive.yaml:2`
- `tests/mocks/src/README.md:17`

### S11 (9곳)
- `plugin/scripts/code_roots.py:18` — .
- `plugin/scripts/code_roots.py:39` — 최신 AOSP는 release config 쪽에 있을 수 있다.
- `tests/fixtures/issue-db-sample/ims/IMS-001-ims-registration-failed/type.md:77` — .
- `tests/fixtures/issue-db-sample/network/NETWORK-001-no-service/type.md:68` — .
- `tests/fixtures/issue-db-sample/sim/SIM-001-sim-not-detected/type.md:74` — .
- `tests/fixtures/issue-db-sample/sms/SMS-001-sms-send-failed/type.md:67` — .
- `tests/mocks/src/android16/build/make/core/version_defaults.mk:1` — 사내 트리의 실제 버전 식별 파일로 바꾼다)
- `tests/mocks/src/android17/build/make/core/version_defaults.mk:1` — 사내 트리의 실제 버전 식별 파일로 바꾼다)
- `tests/mocks/src/README.md:10`

### S12 (1곳)
- `tests/mocks/builds.yaml:3` — .

### S13 (2곳)
- `plugin/scripts/common/masking.py:18` — .
- `plugin/scripts/common/masking.py:94` — RIL 데이터 콜 응답의 `cid`(context id)도 셀로 본다(과잉이지만 안전 쪽)

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
- `plugin/scripts/parse_logcat.py:485` — 사내 실제 문자열로 확인한다.
- `tests/mocks/logcat_gen.py:35` — 사내 실제 문자열 확인

> `issue-db.config.yaml` 값, S2 마켓플레이스, S6 Actions)은 Phase 1·2·4·6에서
> 코드가 생길 때 `TODO(SITE:S<n>)`가 늘어난다. 반입 전에 이 목록을 다시
> 뽑는다.

## 반입 체크리스트 상태 (`15-local-draft.md §15.4`)

| 항목 | 상태 |
|---|---|
| 전체 테스트 통과 | 🟡 D0·Phase 1~9 범위 (`pytest tests` 181개, 샘플 `db_regress --all` 20개 통과). eval은 Phase 13 뒤 |
| 사내 정보 없음 | ✅ 사내 자료를 쓰지 않았다 |
| `plugin/site-defaults.yaml` 없고 example만 있음 | ✅ `test_plugin_root_helper_and_missing_site_defaults`가 검사 |
| `SITE_PATHS`의 다른 경로가 비어 있음 | ✅ `test_site_paths_are_absent_in_draft`가 검사 |
| 레포 루트에 `.mcp.json` 없음 | ✅ `test_no_mcp_json_at_repo_root`가 검사 |
| `.local-draft`를 반입 묶음에 넣지 않음 | ✅ `.gitignore` 등록 + `import_draft.py`가 항상 제외 |
| 이슈 DB 뼈대 (`make_db_skeleton.py`) | ✅ Phase 1. `test_skeleton_has_no_types_and_validates`가 검사 |
| `TODO(SITE)` 목록 갱신 | ✅ 위 절 (Phase가 끝날 때마다 다시 뽑는다) |
| `DRAFT_NOTES.md` 최신 | ✅ 이 파일 |

## 다음 세션에서 할 일

1. **사용자 확인**: Phase 2~6은 미리 받은 승인으로 확인 없이 진행했다. 아래 "사용자 확인이 필요한 항목"을
   먼저 보여주고 답을 받는다. Phase 7부터는 Phase마다 확인을 받는다(`CLAUDE.md` §11.0).
2. 새 세션을 열어 **빈 플러그인 실험**을 돌리고 위 "사외 Claude Code 실험 결과" 표를 채운다
   (`tests/mocks/plugin-probe/README.md`). 커맨드 파일 형식(`plugin/commands/setup.md`), `${CLAUDE_PLUGIN_ROOT}`
   치환, MCP 도구 이름 형식이 여기에 걸려 있다.
3. (선택, 사내) **S-0 선행 확인**: `parse_logcat.py`, `match_signatures.py`, `mask_pii.py`를 사내 실제 로그로.
4. 빈 플러그인 실험(2번)에서 **`plugin/hooks/hooks.json`도 함께 확인**한다: 플러그인 hook 로드, `mcp__.*` matcher,
   `permissionDecision` deny/ask, SessionStart, hook 입력의 `tool_name` 형식(`guard.py`의 TODO(SITE:S1·S3)).
5. **Phase 13**: Phase 12 확인을 받은 뒤 `docs/design/11-phases.md` Phase 13 절과 그 "읽을 문서"를 읽는다 (skill-creator로 `SKILL.md`·`reference/`·eval). Phase 12 완료: 커맨드 12개, `tools/offline_eval.py`.

### 사용자 확인이 필요한 항목 (Phase 2~6에서 쌓임)

- 계약 보완 후보: 각 Phase의 "구현에서 정한 세부" 절 (`parse` 출력 형식과 `ril_*` 이벤트, `--jira-meta` 형식,
  매처 출력, 마스킹 규칙, 생성 파일 표기와 급증 정의, 린터 코드, `config.py` 추가 서브커맨드 등).
  `contracts.md`에 옮길지 정한다.
- Phase 1 산출물 변경: 교차 슬롯 음성 fixture 순서(Phase 3), `type.schema.json`의 `must_match {id, pattern}`(Phase 3),
  fixture를 마스킹해서 생성(Phase 4). 
- 설계와 다르게 해석한 곳: Phase 3 완료 기준의 교차 슬롯 C 값은 `--regress`로 확인했다(분석 모드는 S=0이라 원인을
  평가하지 않는다).
- 의존성: `pyyaml`, `jsonschema`, `pytest`만 쓴다. 정규식 시간 상한은 작업 프로세스 방식이다(`regex` 모듈을 쓰면
  더 가볍다, 가정 18).
