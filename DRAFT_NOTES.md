# DRAFT_NOTES — 사외 초안 진행 기록

> 사외 초안 모드의 진행 상태·가정·실험 결과를 적는 파일이다
> (`docs/design/15-local-draft.md §15.1`). 사내 Claude Code가 설계 문서를 다시
> 다 읽지 않고도 초안 상태를 파악하게 하는 것이 목적이다.
> 이 파일은 **반입 때 사내로 같이 간다**. `.local-draft`는 가지 않는다.

## 진행 상태

- 모드: **사외 초안** (`.local-draft` 있음)
- 완료 Phase: **D0, 1** (2026-09-28)
- 다음 Phase: **2** (logcat 파서 엔진)
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
8. 파서 백엔드 인터페이스 파일(`plugin/scripts/parser_backends/base.py`)과
   reference 백엔드는 **Phase 2**에서 만든다. D0의 모의 site 백엔드는
   계약에 적힌 함수 세 개(`parse`, `builtin_events`, `version`)만 같은
   이름·형식으로 제공하고 자체 파싱을 한다. Phase 2에서 `base.py`를
   상속하도록 바꾼다.
9. `config.py`는 D0에서 **site-defaults 로드와 종료 코드 2 경로만** 있다.
   `check`/`set`/`sync-scripts-path`는 Phase 6에서 구현한다(지금은 종료
   코드 2로 "Phase 6에서 구현한다"를 낸다).
10. 마스킹 함수(`mask_pii`)는 Phase 4다. 골든 테스트의 마스킹 민감도
    검사는 그때까지 `tests/test_golden.py` 안의 임시 치환을 쓴다.
    Phase 4에서 `mask_pii`로 바꾼다.
11. 의존성은 `pyyaml`, `jsonschema`, `pytest`만 썼다. 사내 반입 규정과
    오픈소스 승인 대상이다(사용자 확인 필요).

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

`python3 tools/list_site_todos.py`로 갱신한다. 2026-09-28(Phase 1 끝) 기준 **50곳**.
Phase 1에서 샘플 이슈 DB가 생기면서 S5·S9·S11이 늘고 S16~S19가 새로 생겼다:

### S1 (1곳)
- `tests/mocks/skills/data-analyzer/SKILL.md:63` — 스킬 이름과 호출 방식 확인

### S4 (1곳)
- `plugin/site-defaults.example.yaml:38` — 사내 Jira 시각 타임존

### S5 (3곳)
- `plugin/site-defaults.example.yaml:50` — 사내 GHE 호스트
- `plugin/site-defaults.example.yaml:51` — 사내 org
- `tests/fixtures/issue-db-sample/.github/CODEOWNERS:3` — org·팀 이름

### S7 (1곳)
- `plugin/site-defaults.example.yaml:54` — logcat 시각 타임존

### S9 (16곳) — 로그 문구·태그·RIL 출력 형식
- `tests/fixtures/issue-db-sample/data/DATA-001-no-setup-data-call/type.md:119`
- `tests/fixtures/issue-db-sample/parser-rules/extractors.yaml:10` (extractor 14개 전체)
- `tests/fixtures/issue-db-sample/parser-rules/ril.yaml:3`
- `tests/fixtures/issue-db-sample/parser-rules/tags.yaml:7,23,27,30,34`
- `tests/mocks/logcat_gen.py:61` — RILJ 요청/응답 출력 형식
- `tests/mocks/parser_backends/site/__init__.py:55` — 판별 규칙 문구
- `tests/mocks/scenarios/{call-001-01-positive,data-001-01-positive,data-001-02-roaming,network-001-01-positive,sim-001-01-positive,sms-001-01-positive}.yaml:2`

### S10 (2곳)
- `tests/mocks/scenarios/ims-001-01-positive.yaml:2` — IMS 로그 문구
- `tests/mocks/src/README.md:17` — 벤더 RIL 태그·소스 구조

### S11 (7곳) — 소스 경로
- `tests/fixtures/issue-db-sample/{ims,network,sim,sms}/*/type.md` — 아직 `code_refs`를 못 채운 원인 4개
- `tests/mocks/src/android16/build/make/core/version_defaults.mk:1`
- `tests/mocks/src/android17/build/make/core/version_defaults.mk:1`
- `tests/mocks/src/README.md:10` — 트리 버전 식별 파일

### S12 (1곳)
- `tests/mocks/builds.yaml:3` — 빌드명 체계 (샘플 `issue-db.config.yaml`의 `build_compare`가 이것을 쓴다)

### S16 (1곳)
- `tests/fixtures/issue-db-sample/issue-db.config.yaml:12` — `jira_key_regex`

### S17 (1곳)
- `tests/fixtures/issue-db-sample/issue-db.config.yaml:11` — `jira_base_url`

### S18 (1곳)
- `tests/fixtures/issue-db-sample/issue-db.config.yaml:32` — `fix_ref_regex`

### S19 (2곳)
- `tests/fixtures/issue-db-sample/.github/CODEOWNERS:5` — 리뷰어 형식
- `tests/fixtures/issue-db-sample/issue-db.config.yaml:68` — `reviewers.format`

### S20 (3곳)
- `plugin/site-defaults.example.yaml:47` — Jira 슬롯 필드 유무
- `tests/mocks/logcat_gen.py:66` — 슬롯 메시지 접두어
- `tests/mocks/scenarios/README.md:10`

### S21 (1곳)
- `tests/mocks/logcat_gen.py:35` — bugreport 섹션 헤더

> 아직 코드가 없는 곳(S3 `jira.tools` 확정, S8 태그 수집 목록, S13 마스킹
> 오탐, S14 보안 규정, S15 Ubuntu/파이썬 버전, S16~S19
> `issue-db.config.yaml` 값, S2 마켓플레이스, S6 Actions)은 Phase 1·2·4·6에서
> 코드가 생길 때 `TODO(SITE:S<n>)`가 늘어난다. 반입 전에 이 목록을 다시
> 뽑는다.

## 반입 체크리스트 상태 (`15-local-draft.md §15.4`)

| 항목 | 상태 |
|---|---|
| 전체 테스트 통과 | 🟡 D0·Phase 1 범위 (`pytest tests` 37개). `db_regress`·eval은 Phase 2~13 뒤 |
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
2. **Phase 2** 시작: `docs/design/11-phases.md` Phase 2 절과 그 "읽을 문서"를
   읽고 파서 백엔드 인터페이스와 `parse_logcat.py`를 만든다.
   - Phase 1의 `parser-rules/`(태그 15개, RIL 요청 6·unsol 5, extractor 14)가
     파서의 규칙 입력이다. 하드코딩하지 않고 `--rules`로 읽는다.
   - Phase 2의 fixture는 `tests/fixtures/logs/`에 따로 만든다(이슈 DB 안의
     fixture와 섞지 않는다).
   - D0의 모의 site 백엔드를 `base.py` 상속으로 바꾸고, 모의 골든을 다시 확인한다.
