# 11. 개발 Phase (할 일·완료 기준·읽을 문서)

> 원본 11장. 11.0 작업 방식은 아래 절(매 세션 요약은 `CLAUDE.md` "작업 방식").
> **사외 초안 모드(D0 → 1~13)와 사내 처음부터 모드(0 → D0 → 1~14)에서만 읽는다.** 사내 보완 모드는 이 파일을 읽지 않는다 (`15-local-draft.md §15.5`. Phase 14는 S-7로 그 표에 있다).
> 모든 테스트·eval은 테스트 헬퍼 플러그인 루트(`tests/helpers/make_plugin_root.py`, `site-defaults.example.yaml` 복사본)에서 돈다 (`15-local-draft.md §15.1`).
> 각 Phase를 시작할 때 이 파일에서 **그 Phase 절만** 읽고, 그 Phase의 "읽을 문서"를 읽는다.

## 11.0 작업 방식 (Claude Code가 지킬 것)

> 이전 `CLAUDE.md §11.0`. 사내 보완 모드는 이 파일을 읽지 않으므로, 모든 모드에 필요한 요약은 `CLAUDE.md`에 있다.

- **`CLAUDE.md` 머리말의 모드 표에 따른 시작점부터** Phase(또는 S 단계) 단위로 진행한다. 사외 초안·사내 처음부터 모드에서는 각 Phase를 시작할 때 `11-phases.md`의 그 Phase 절과 "읽을 문서"를 읽는다 (항상 `contracts.md` 포함. 코드·스킬·이슈 DB 동작을 바꾸면 `12-principles.md`도). 사내 보완 모드(S 단계)에서는 `15-local-draft.md §15.5`의 그 단계 "읽을 것"만 읽는다. Phase(단계)가 끝날 때마다 완료 기준을 점검하고 결과를 요약한 뒤 사용자 확인을 받는다. 확인을 받아야 다음으로 넘어가고, 모드에 맞는 파일(사외 초안 `DRAFT_NOTES.md`, 사내 `SITE_PROFILE.md`)의 "진행 상태"를 갱신한다.
- 각 Phase의 완료 기준은 **그 시점까지 만든 것만으로** 확인할 수 있게 짜여 있다. 뒤 Phase의 기능이 필요하면 멈추고 보고한다.
- 역할 분담:
  - 플러그인 뼈대, 스크립트, 커맨드, Claude hooks, git hooks: Claude Code가 직접 구현한다.
  - `skills/telephony-triage/SKILL.md`와 `reference/`: **skill-creator 스킬**로 작성하고 eval로 검증한다 (Phase 13, 모든 스크립트가 끝난 뒤).
- 플러그인 규격, hooks 스키마, GHE Actions 문법은 구현 전에 최신 공식 문서로 확인한다. 사내에서 외부 공식 문서에 접근할 수 없으면 **빈 플러그인 실험(S1)** 으로 대체하고 결과를 `SITE_PROFILE.md`에 기록한다.
- 사내 확인값은 `SITE_PROFILE.md`에만 쓴다. 이 문서 세트에는 쓰지 않는다 (`14-site.md §14.1`).
- 모든 테스트 로그는 마스킹된 fixture만 쓴다.
- **테스트 실행**: 코드 변경 뒤에는 `tools/related_tests.py --run`(관련 테스트 + 경계 검사)을 기본으로, 전체 `pytest tests`는 (1) 공용 모듈·스키마·테스트 헬퍼·의존성 변경(도구가 `full: true`로 판단) (2) 반입 묶음 만들기 직전(Z) (3) 사용자가 요청할 때만 돌린다.
- Claude Code 세션은 **플러그인 레포 루트에서 연다** (`CLAUDE.md`가 로드되도록). 이슈 DB 레포는 절대 경로로 다룬다.
- Claude Code 플러그인 규격(디렉토리 구조, `plugin.json`/`marketplace.json` 필드, hooks 스키마와 권한 결정 필드, 커맨드와 스킬의 관계, `${CLAUDE_PLUGIN_ROOT}` 치환, MCP 도구 이름 형식, 로컬 플러그인 로드 방법)과 GHE Actions 문법은 버전에 따라 바뀔 수 있다. **구현 전에 최신 공식 문서로 확인하고, 사내에서 공식 문서에 접근할 수 없으면 빈 플러그인 실험(S1)으로 확인한다.** 이 문서와 다르면 확인 결과를 따르고 차이를 사용자에게 보고한다.

- **수동 기록(`record`)의 구현 위치**: 별도 Phase가 없다. 계획 경로와 `source: record` 규칙은 Phase 7(손으로 쓴 record 계획), 검증 상태(`skipped: fixture 없음`, `시그니처 없음(pending)`)는 Phase 10, 리뷰 항목은 Phase 11, 커맨드 틀은 Phase 12, 대화형 흐름과 eval 30~38(수동 기록)은 Phase 13에서 만든다. `also_allowed`/`allow-cause`도 별도 Phase가 없다: 스키마·lint는 Phase 1·5, op·drift는 Phase 7, R2~R4 판정과 초안 제시는 Phase 10, 리뷰 항목은 Phase 11, eval 42는 Phase 13. 설계는 `07-workflow.md §record`, 검증 표는 `05-verification.md §5.12 (1)` "수동 기록 검증".
- **테스트용 이슈 DB**: 합성 샘플은 `tests/fixtures/issue-db-sample/`(파일 트리)에 둔다. 테스트는 헬퍼(`tests/helpers/make_repo.py`)로 이 트리에서 임시 git 레포와 bare 원격을 만들어 쓴다. 변형(오류 주입, 0건 카테고리, 리뷰 케이스 등 `issue-db-*`)은 커밋하지 않고 `tests/helpers/make_variant_dbs.py`가 테스트 때 샘플에서 생성한다(`runner.variant_db(name)`). 샘플 트리를 오염시키지 않는다. 반입·운영용 이슈 DB는 샘플 없는 **뼈대**만 `tools/make_db_skeleton.py`로 만든다 (Phase 1).

### Phase D0. 모의 환경 (두 모드 공통)
- 사외 초안 모드는 여기서 시작한다. 사내 처음부터 모드는 Phase 0 다음에 한다(모의 환경은 Phase 1~13의 테스트에 필요하므로 모드와 무관하다). 사내 보완 모드는 하지 않는다(사외에서 이미 만들어 반입됨).
- 할 일: `15-local-draft.md §15.2`의 모의 Jira MCP(`mock-jira`, 비표준 도구 이름, `tests/mocks/mcp.json`), 모의 원격·`gh` 스텁, 합성 logcat 생성기(슬롯·시계 이상·bugreport 래핑 옵션 포함), 모의 소스 트리, 가상 빌드명, `plugin/site-defaults.example.yaml`(`synthetic_allowed: true`, `jira.exclude_servers: []`), **테스트 헬퍼 `tests/helpers/make_plugin_root.py`**(`15-local-draft.md §15.1`), `DRAFT_NOTES.md`, `.local-draft`(`.gitignore` 등록. 사내 처음부터 모드는 만들지 않는다), `tools/list_site_todos.py`, **`SITE_PATHS`와 `tools/import_draft.py`, 반입 기준선 `.draft-manifest.json`**(`15-local-draft.md §15.6`). 사외 Claude Code 실험(`15.2` "사내 Claude Code 기능" 행: 플러그인 로드, hooks, `${CLAUDE_PLUGIN_ROOT}`, MCP 도구 이름 형식, **`@SITE_PROFILE.md` import가 파일이 없을 때 오류·경고를 내는지**) 결과를 `DRAFT_NOTES.md`에 기록.
- 완료 기준: 모의 Jira MCP에서 이슈 읽기, 모의 원격으로 push와 `gh pr create` 성공, 합성 logcat 생성, 모의 소스 트리에서 심볼 검색이 된다. `make_plugin_root.py`가 만든 루트에는 `site-defaults.yaml`이 있고, 개발 레포 `plugin/`에는 없다. `plugin/`을 직접 `${CLAUDE_PLUGIN_ROOT}`로 주면 `config.py`가 종료 코드 2("사내 기본값 없음")를 낸다. Ubuntu에서 `.githooks/pre-commit`·`pre-push` 스텁이 실행 비트와 함께 커밋된다(`git ls-files -s`로 100755 확인). `tools/import_draft.py`를 가짜 사내 레포에 두 번 반입해서 시험한다: `SITE_PATHS` 경로는 보존된다. 두 번째 반입에서 사외에서 지운 파일은 지워지고, 사내에서 새로 만든 비-`SITE_PATHS` 파일은 지워지지 않고 목록으로 보고되며, 첫 반입 이후 사내에서 고친 사외 파일이 있으면 목록을 보여주고 멈춘다. 레포 루트에 `.mcp.json`이 없다. 이후 Phase 1~13은 이 모의 환경으로 진행한다 (`15-local-draft.md §15.3`).
- 읽을 문서: `15-local-draft.md`, `16-existing-assets.md`, `contracts.md`, `02-config.md`, `14-site.md §14.2`
- 모의 site 백엔드(`builtin.data.*` 이벤트를 내는 가짜)·골든 테스트 틀·어댑터 예시, 모의 분석 스킬, 비표준 Jira 도구 이름도 만든다 (`16-existing-assets.md §16.6`). 백엔드·`jira.tools`·`analyzers`의 구현 위치는 Phase 2(백엔드 인터페이스·어댑터), Phase 6(`jira.tools` setup), Phase 13(심층 분석 호출, `--analyzer`/`--no-analyzer`)이며, 해당 Phase의 읽을 문서에 `16-existing-assets.md`를 더한다.

### Phase 0. 사내 환경 확인 (사내 처음부터 모드에서만)
- 할 일: `14-site.md §14.4` 절차. 문서 정합성 검토(여러 파일 간 참조·표 복사·개수 포함, `REVIEW-OPEN.md` 항목 포함) + 사내 환경 확인(S1~S22). 결과는 `SITE_PROFILE.md`(진행 상태 포함).
- 완료 기준: `14-site.md §14.4` 완료 기준.
- 읽을 문서: 전체 (`CLAUDE.md`, `docs/design/*.md`(`99-deferred.md` 제외), `REVIEW-OPEN.md`). 정합성 검토를 위해 이 Phase만 전부 읽는다. **사내 보완 모드에서는 이 Phase를 하지 않는다** (S-1 축약판을 쓴다). 이 Phase 다음은 Phase D0다.

### Phase 1. 이슈 DB 뼈대와 합성 샘플
- 할 일:
  - 합성 샘플 트리 `tests/fixtures/issue-db-sample/`: `03-issue-db.md §5.2` 디렉토리 구조, `issue-db.config.yaml`(schema_version 1, generator_version 1, `external_parsers: {}`, `matcher.pattern_timeout_ms`, SITE_PROFILE의 S16~S19 값: `jira_key_regex`, `jira_base_url`, `fix_ref_regex`, `reviewers`. 사외 초안은 모의 값), `.gitignore`, `.gitattributes`
  - `schema/` 6종(`plan.schema.json`은 `contracts.md §작업 계획`의 형식(`schema_version`, `base_sha`, `jira.origin`, `feedback.date`, `included_pending`)과 op 표 전체(`allow-cause` 포함), `source`는 9개 값만. `expect.schema.json`은 `.expect.yaml`(`expect_top`, `expect_not`, `also_allowed`, `occurred_at`, `origin`)), `templates/` 3종
  - `schema/`에 `signatures_pending`(원인만, 새 유형은 증상 시그니처 필수), 시그니처 `same_phone`·`sequence`와 조건 `id`, 원인 `cp_evidence`, 피드백 `decision: manual`, 계획 `source`, Jira 기록 `occurred_on` 포함 (`contracts.md §상태 값`). `plan.schema.json`은 `operations`를 순서 있는 배열로 둔다 (적용 순서가 의미를 가짐)
  - `.github/CODEOWNERS`(팀 이름은 SITE_PROFILE 또는 placeholder), `pull_request_template.md`(`06-collaboration.md §6.3`)
  - `CONTRIBUTING.md` (`03-issue-db.md §5.7` + `06-collaboration.md §6.2` 요약 + "push 전 `validate`" + 직접 편집 브랜치의 재동기화 절차 + 수동 기록 안내 + `also_allowed` 규칙), `GLOSSARY.md` 초안(경계 표, 금지 동의어, `06-collaboration.md §6.9`), `docs/` 3종(getting-started `06-collaboration.md §6.9`, review-guide §6.6 — 직접 편집과 `source: review` 계획 파일로 올리는 법 둘 다, branch-protection §6.1)
  - `.githooks/pre-commit`·`.githooks/pre-push` **스텁**: 경고만 출력하고 통과 (Phase 8에서 교체)
  - 샘플 시그니처 중 하나(DATA-001-01)는 `sequence`와 `same_phone`을 쓴다 (`03-issue-db.md §5.4 (1)` 예시). 원인 하나에 `cp_evidence` 예시를 넣는다
  - Phase 0에서 확인한 태그, 로그 문구, RIL 출력 형식으로 `parser-rules/` 초기 규칙을 만든다. 미확인 항목은 `reason: placeholder`로 표시한다.
  - 카테고리별 샘플 유형 1개씩(6개)과 각각의 Jira 기록, 양성 fixture:
    - `DATA-001` SETUP_DATA_CALL이 발생하지 않음 (원인 2개: Data disabled, Roaming disabled)
    - `CALL-001` VoLTE가 동작하지 않음 (`fix.status: fixed` + `verification` 예시(`05-verification.md §5.12 (2)` 형식), `scenario_signatures` 예시, `CALL-001-01.fixed.<build>.log` 포함, IMS-001-01과 `related`)
    - `NETWORK-001`, `SIM-001`, `SMS-001`, `IMS-001` (IMS-001-01은 CALL-001-01과 `related` 양방향)
  - 음성 fixture 1개 이상 (`<유형 ID>.none.log`, 기대값 "이슈 DB 전체에서 S=1인 유형 없음"). **교차 슬롯 음성 fixture** `DATA-001.none.2.log`(슬롯 0의 증상 + 슬롯 1의 원인 로그, `logcat_gen.py`로 합성)
  - `tools/make_db_skeleton.py <out_dir>`: 샘플 트리에서 유형 디렉토리·Jira·fixture·피드백을 뺀 **운영용 뼈대**(스키마, 템플릿, config, CODEOWNERS, docs, `.githooks`, GLOSSARY, CONTRIBUTING, placeholder `parser-rules`, 빈 카테고리 디렉토리)를 만든다. 반입과 사내 운영 레포는 이것으로 시작한다 (`15-local-draft.md §15.4`).
- 완료 기준: 샘플이 모든 JSON 스키마를 통과한다(스키마 검증은 임시로 `jsonschema` CLI 사용 가능). 파일 배치와 fixture 이름이 `03-issue-db.md §5.2`, `contracts.md §fixture`와 같다. `make_db_skeleton.py` 결과에 유형·Jira·fixture가 없고 스키마를 통과한다. placeholder 항목 목록을 사용자에게 보고한다.
- 읽을 문서: `contracts.md`, `02-config.md`, `03-issue-db.md`, `04-parser-matching.md §5.8`, `05-verification.md §5.12 (2)`(verification 형식), `06-collaboration.md §6.1·6.2·6.3·6.6·6.9`, `SITE_PROFILE.md`

### Phase 2. logcat 파서 엔진
- 할 일: **파서 백엔드 인터페이스**(`parser_backends/base.py`)와 백엔드 선택(`parser.backend`), 공통 후처리(마스킹 자리, extractor, 태그 매핑)를 먼저 만든다 (`16-existing-assets.md §16.3`). reference 백엔드의 **공통 처리(포맷·시간·RIL 페어링·윈도우)는 제품 수준**으로 만들고 builtin 판별 로직은 넣지 않는다. data 판별은 사내에서 검증된 기존 파서를 site 백엔드로 포팅해서 넣는다(S-4a). 아래는 reference 백엔드 기준이다. `parse_logcat.py parse`. 포맷 변형 처리(연도·타임존은 `--tz`/`--year` 인자로만 받음, 사용자 config를 읽지 않음. 백엔드·외부 파서 설정은 `site-defaults.yaml`에서만 읽음, `contracts.md §3.2` 설정 읽기), RIL 페어링, 윈도우 자르기(`--around`/`--full`), extractor 실행기, `tag`/`tag_regex` 지원, `sanitize_build`(`common/`, ref 이름 검사 포함), **`phone_id` 추출**(태그 접미사·메시지 접두어, 없으면 `null`)과 RIL 페어링 키 `(pid, phone_id, serial)`, **`coverage`**(파일 시각 범위, `window_in_range`, 시계 역행·점프 감지), **`extract-bugreport`**(logcat 섹션과 `build.json`만, 다른 섹션은 읽지 않음). 규칙은 `--rules`에서 로드한다 (하드코딩 금지). 규칙 파일 스키마 검증 포함. 어댑터 실행(`external_parsers`, `${CLAUDE_PLUGIN_ROOT}` 치환, `--no-external`). `--mask`와 `cut`은 인터페이스만 만들고 마스킹 연결은 Phase 4.
- fixture(`tests/fixtures/logs/`): 정상 데이터 연결, SETUP_DATA_CALL 없음(+DATA_DISABLED / +ROAMING_DISABLED), SETUP_DATA_CALL 에러 응답, call drop, 서비스 없음, SIM absent, SMS 전송 실패, IMS 등록 실패
- 완료 기준: fixture별 이벤트 JSON 스냅샷 테스트 통과(연도 없는 threadtime에 `--tz`/`--year`를 주면 UTC 시각이 기대값과 같음). 듀얼 SIM 합성 로그에서 이벤트의 `phone_id`가 슬롯별로 나오고, 접미사가 없는 태그는 `null`이다. 같은 serial을 두 슬롯이 쓰는 로그에서 RIL 요청·응답이 슬롯별로 짝지어진다. 발생 시각이 파일 범위 밖인 호출에서 `coverage.window_in_range: false`가 나오고, 시각이 역행하는 합성 로그에서 `clock_anomalies`가 나온다. 합성 bugreport(zip·txt)에서 `extract-bugreport`가 logcat 섹션만 꺼내고 dumpsys 섹션의 문자열이 결과 파일에 없으며 `build.json`에 fingerprint가 있다. `parser-rules/`만 바꿔도 코드 수정 없이 결과가 바뀐다. `parser.backend`를 모의 site 백엔드로 바꾸면 `builtin.data.*` 이벤트가 extractor 이벤트와 함께 나오고(`source` 구분), extractor가 `builtin.`/`ext.` 접두어 이벤트를 만들려 하면 거부된다. 백엔드 이름·버전이 이슈 DB `parser_backend`와 다르면 경고한다. 이슈 DB `external_parsers`에 있는 카테고리의 어댑터가 없거나 버전이 낮으면 경고한다. `sanitize_build`가 `A..B`, `X.lock`, 끝 `.`을 유효한 브랜치 이름으로 바꾼다. `tests/test_golden.py`가 모의 골든으로 통과하고, 골든을 일부러 바꾸면 실패한다.
- 읽을 문서: `contracts.md §3.2·§fixture·§기존 자산 연결 계약`, `04-parser-matching.md §5.8`, `07-workflow.md §Step 3`, `02-config.md §4`(시각 정렬), `16-existing-assets.md §16.3`

### Phase 3. 매처
- 할 일: `match_signatures.py`. `04-parser-matching.md §5.11` 의미와 점수, **원인 평가 범위(분석 모드는 2단계: S=1 유형의 원인만, 회귀·검증 모드는 모든 active 원인의 C를 독립 평가)**, `must_event`, **`same_phone`(기본 true, `null`은 와일드카드)과 `sequence`(첫 충족 시각 단조 증가)**, 패턴당 타임아웃(`matcher.pattern_timeout_ms`, 초과 시 `error`로 표시하고 계속), `status` 필터, 수정 상태 판단(`03-issue-db.md §5.9`, `build_compare`, ≥ 비교, 빌드 없음 → 판단 불가), related 조회, `signatures_pending` 원인은 매칭하지 않고 `pending_causes`로 출력, 수락률 가중치(1위 분모, `decision: manual` 제외)와 `--no-feedback-weight`, **회귀·검증 모드 `--regress`**, 마스킹 안 된 입력 거부. `common/`에 시그니처·extractor **컴파일 함수**를 만들고 매처는 메모리 컴파일로 동작한다 (파일 캐시 `.cache/compiled.json` 읽기·쓰기 테스트는 Phase 5).
- 완료 기준 (테스트 입력 이벤트는 `masked: true`로 만든 테스트 데이터):
  - "없음 + DATA_DISABLED" fixture → `DATA-001 > DATA-001-01` 1위, medium 이상
  - 원인 로그를 지운 fixture → "DATA-001, 원인 미확인"
  - 음성 fixture → S=1인 유형 없음
  - 증상은 없고 다른 유형의 원인 시그니처만 충족하는 입력 → 분석 모드에서는 그 원인이 후보에 없고, `--regress`에서는 그 원인이 C=1로 나온다(점수 0.6은 참고 값). `scoring.cause_weight`를 0.5로 바꿔도 `--regress`의 S/C 출력은 같다
  - CALL-001 fixture에 fixed_in 이전/같은 빌드/이후 SW → "이미 수정됨" / "회귀 의심" / "회귀 의심"
  - `deprecated` 원인은 후보에 나오지 않는다. `signatures_pending` 원인은 점수 후보가 아니라 `pending_causes`로만 나온다
  - `--regress`면 bonus 0, 피드백 가중치 끔, 분석 범위 = 파일 전체
  - 교차 슬롯 fixture(`DATA-001.none.2.log`) → 분석 모드에서 DATA-001-01 C=0, `same_phone: false`로 바꾼 사본에서는 C=1. `sequence`가 있는 시그니처는 순서를 뒤집은 로그에서 C=0. 일부러 넣은 느린 정규식은 타임아웃으로 `error`가 되고 다른 후보는 그대로 나온다
- 비고: 이 Phase가 끝나면 사내 **S-0 선행 확인**(`15-local-draft.md §15.5`)을 할 수 있다. 사외에서는 기다리지 않고 Phase 4로 간다.
- 읽을 문서: `contracts.md`, `04-parser-matching.md §5.11`, `03-issue-db.md §5.9`, `02-config.md §5.3`

### Phase 4. 마스킹
- 할 일: `common/` 마스킹 함수, `mask_pii.py` (치환 모드, `--check` 모드(`--changed`/`--staged`), `--events` 모드, `allow_patterns`). `parse_logcat.py parse --mask`(extractor 전 줄 단위 마스킹, 백엔드·외부 파서 이벤트의 `msg`·`fields` 포함)와 `cut`에 마스킹 연결.
- 완료 기준: `08-safety.md §8` 항목별 누락/과잉 테스트 통과(자격증명 행 `<CRED#n>` 포함: SIP Digest `response=`·`nonce=`, AKA `RES`, `password=`). Jira 응답 JSON의 텍스트 필드(요약·설명·코멘트)를 `mask_pii --events` 경로로 마스킹하면 전화번호·IMEI가 토큰이 된다(`08-safety.md §8.1`). 번호 토큰: 한 파일 안에서 같은 셀 ID는 같은 `<CELL#n>`, 다른 셀 ID는 다른 번호가 된다. **이미 `<CELL#1>`이 있는 입력에 새 셀 ID가 있으면 `<CELL#2>`부터 받는다(기존 토큰과 겹치지 않음).** 빌드 번호·타임스탬프가 오탐되지 않는다. 같은 입력은 같은 출력이고, 마스킹된 입력에 다시 적용해도 같다(멱등). `parse --mask` → 매처 파이프라인이 Phase 3 결과와 같다. 원본 식별자가 든 줄에서 extractor가 마스킹된 값을 추출한다. 모의 site 백엔드가 원본 값을 담은 `builtin.*` 이벤트 필드도 마스킹된다. `cut` 결과 파일에 원본 식별자가 없다.
- 읽을 문서: `contracts.md §3.2`, `08-safety.md §8`, `04-parser-matching.md §5.11 (1)`

### Phase 5. 생성기, 린터, 회귀
- 할 일:
  - `db_build.py`: README(`03-issue-db.md §5.6`), 카테고리 README, STATS(`06-collaboration.md §6.7`, 수락률은 `06-collaboration.md §6.5`대로 `manual` 제외, 최근 N일·급증은 `occurred_on` 기준), CHANGELOG, 로컬 캐시(`06-collaboration.md §6.8`, `common/` 컴파일 함수 사용), 결정성 규칙(`03-issue-db.md §5.2`), `generator_version` 검사, 모드 `--write`/`--verify [--staged]`/`--preview <dir>`/`--cache-only`
  - `db_lint.py`: `01-architecture.md §3.1`의 lint 책임 전부 (fixture 파일명(`<n1>`/`<n2>` 구분), 시그니처·extractor 원본 식별자, `jira_key_regex`, `fix.ref` 형식(`fix_ref_regex`), 금지 동의어, `signatures_pending` 경고와 pending 원인의 `unverified` 고정, 양성 fixture 없음 경고, `builtin.*`·`ext.*` 참조 검사, `--residual`, 검증 규칙 중 "근거 없는 verified 금지"·"새 원인 fixed 금지(base ref 범위)"), `--all`/`--ref`/`--changed`(merge-base)/`--staged`
  - `db_regress.py`: `contracts.md §fixture` 기대값, `--all`/`--changed`/`--staged`(parser-rules 변경 시 전체), 항상 `--regress`, 실패 원인 출력(음성 fixture면 S=1이 된 유형·시그니처 전역 키)
- 완료 기준: 샘플 이슈 DB에서 README가 `03-issue-db.md §5.6`과 같은 구조로 나오고 6개 카테고리가 모두 나온다. 0건 카테고리 표시는 변형 `issue-db-empty-category`(make_variant_dbs.py가 테스트 때 생성)와 `make_db_skeleton.py` 결과(6개 카테고리 모두 "아직 등록된 이슈가 없습니다")로 확인한다. 두 번 실행하면 바이트 단위로 같다. `--preview`와 `--cache-only`는 워킹 트리를 바꾸지 않는다. 캐시 해시가 다르면 매처가 재컴파일한다. 린터가 변형 `issue-db-lint-errors`(make_variant_dbs.py가 테스트 때 생성)의 일부러 넣은 오류(ID 중복, Jira 중복, 금지 동의어, 없는 related, 절대 경로 code_refs, 잘못된 id_prefix, 규칙 밖 fixture 이름(`.resolved.log`, 양성 `.1.log` 등), 시그니처·extractor의 원본 IMSI 패턴, 옛 ID 잔존, pending 표시 없이 빈 시그니처, 유형에 붙은 `signatures_pending`, 빈 `symptom_signatures`, `verify-resolution` evidence 없는 verified, `fix_ref_regex`에 맞지 않는 `fix.ref`, 현재 백엔드 `builtin_events()`에 없는 `builtin.*` 참조, 이슈 DB `external_parsers`에 없는 카테고리의 `ext.*` 참조, 시그니처의 특정 마스킹 번호 고정(`<CELL#1>`), 중첩 수량자 정규식(`(a+)+`), `sequence`에 없는 조건 id·중복 id·`must_not_match` 참조, `jira/*.yaml` `note`와 `cp_evidence`의 원본 전화번호, `also_allowed`에 자기 원인·같은 유형 원인·없는 ID, 없는 Jira 키나 fixture 경로를 가리키는 `resolution_verification.evidence`, `synthetic_allowed: false`인 루트에서 `origin: synthetic` fixture)를 모두 잡고, `.resolved.1.log`·`.extra.1.log`·다른 유형 원인을 담은 `also_allowed`는 통과시킨다. `decision: manual` 피드백이 수락률에 들어가지 않는다. `date`는 최근이지만 `occurred_on`이 오래된 Jira 여러 건이 최근 30일 건수·급증에 들어가지 않는다. 회귀가 샘플 fixture 전부 통과한다. 음성 fixture를 일부러 깨면 어느 유형의 어떤 시그니처가 잡았는지 출력된다. `signatures_pending` 원인의 양성 fixture가 회귀에 `"<유형 ID>:unresolved"` 기대값으로 포함된다(변형 `issue-db-pending`, make_variant_dbs.py가 테스트 때 생성).
- 읽을 문서: `contracts.md`, `02-config.md §5.3`, `03-issue-db.md`, `04-parser-matching.md §5.11`, `06-collaboration.md §6.5·6.7·6.8·6.9`

### Phase 6. 설정, 코드 경로, setup
- 할 일: `config.py`(`check --db [--for write|dry-run]`: 스키마·생성기 버전·**파서 백엔드·외부 파서**·gh 인증 → `writable`/`push_allowed` 판정, `migrate/schema-v<N>` 브랜치 예외, 설정 우선순위(사용자 config > `site-defaults.yaml` > 내장. `site-defaults.yaml` 없으면 종료 코드 2, example은 읽지 않음), `jira.tools` 매핑, `jira.exclude_servers`, `sync-scripts-path`, `jira.read_tools` 전체 이름, `jira.timezone`, `logcat.*`, `code_profiles`/`recent_code_roots`), `code_roots.py`(Step 2-1 후보 정렬, 검증, 트리 버전 추정 — Phase 0에서 확인한 파일 위치 반영, `resolve`, `find-symbol`), `db_pr.py lock`(`--take-over` 포함)·`snapshot --job`(세션 lock, `contracts.md §3.2`), `commands/setup.md`
- 완료 기준: config 대화형 생성, 잘못된 경로 거부, **비표준 이름의 `mock-jira`에서 `jira.tools` 후보를 골라 확인받고 `read_tools`에 포함**(테스트 헬퍼 루트, `exclude_servers: []`), `exclude_servers: ['mock-*']`인 복사본에서는 `mock-jira`가 후보에서 빠짐, **`site-defaults.yaml`이 없는 플러그인 루트에서는 setup과 `config.py check`가 종료 코드 2("사내 기본값 없음")로 멈추고 example을 읽지 않음**, Jira read_tools 확인 절차(전체 도구 이름 저장), **gh 인증 실패 시 읽기 설정(1~8)은 끝난 상태로 "쓰기 불가" 안내 후 종료**, 스키마·생성기 버전 확인은 **스냅샷(origin/<base>) 기준**이다(사용자 clone이 옛 버전이어도 origin 기준으로 판정), 버전 불일치면 읽기 전용 표시, `--db`의 현재 브랜치가 `migrate/schema-v<N>`이면 버전 불일치에서도 gh 인증만 보고, `--for dry-run`은 gh 인증 없이 `push_allowed: false`로 통과, `core.hooksPath`가 정확히 `.githooks`로 설정됨, setup 후 사용자 clone의 브랜치와 워킹 트리가 그대로다(스냅샷에만 캐시 생성). 다른 작업 키의 lock이 있으면 `lock acquire`와 `snapshot`이 종료 코드 2로 보유자를 알리고, 같은 작업 키의 lock이 10분 이내에 갱신됐으면 `--take-over` 없이는 종료 코드 2이고 `--take-over`면 이어받으며, 4시간 넘게 갱신되지 않은 lock은 가져오고, `release --force`로 풀린다. 코드 경로 선택기가 버전 일치 프로필을 먼저 추천하고, 잘못된 루트를 거부하고, 버전 불일치를 경고한다.
- 읽을 문서: `contracts.md §3.2·§기존 자산 연결 계약`, `02-config.md`, `07-workflow.md §Step 1·Step 2·Step 2-1`, `06-collaboration.md §6.4`, `16-existing-assets.md §16.1`, `15-local-draft.md §15.1`

### Phase 7. 이슈 DB 반영, PR, sync-pr
- 할 일:
  - `db_add.py`: `apply`, `drift`, `renumber`(브랜치 안, "내 ID"만), `check-ids`, `similar`. op 표 전부(`allow-cause` 포함. 검증 op의 판정 로직 없이 적용 규칙만), 계획 `source`별 규칙(pending 피드백은 `analyze`만, `signatures_pending`은 `record`만, `source`는 9개 값만 허용), `schema_version` 검사, 임시 ID·fixture 번호 적용 시점 할당, type.md 엔티티 단위 재작성, 파서 규칙 항목 병합, related 양방향, 피드백 기록(`feedback.date` 사용)과 pending 규칙, `verify-resolution` evidence 존재 검사, `update-fix`의 `fixed` → `fix-submitted` 거부, drift 표(`contracts.md §작업 계획`).
  - `db_pr.py`: `cleanup`, `preflight`, `stage`(drift 검사, `--dry-run`, 다른 worktree의 `tt/<br>` 검사, `state.json`), `summary`(`source`·`jira.origin` 라벨, 검증 실행/건너뜀 표, 리뷰어 계산(`allow-cause` 대상 fixture의 카테고리 오너 포함), `approved_hash`), `publish`(`state.json` 대조, refspec push, `included_pending` 이동, `base_sha` 갱신), `discard`(lock 해제). 도구 브랜치 `tt/*`.
  - `sync-pr`: 계획 재적용(`06-collaboration.md §6.3`). 계획 없는 브랜치는 수동 절차 안내만.
  - 사후 lint(`06-collaboration.md §6.3` ⑤): ID 중복·Jira 중복을 **보고**한다 (정리는 메인테이너 수동).
  - `db_verify.py rules` **뼈대**: R4만 실제 실행, R1~R3·R5는 `not-implemented`, R6은 `skipped` (`05-verification.md §5.12 (1)`). `--plan`/`--draft`/`--changed`/`--staged` 인터페이스와 종료 코드 `3` 경로(`TT_FORCE_VERIFY_EXIT=3`)는 이때 만든다.
  - Step 8 전체와 공통 쓰기 절차는 **스킬 없이** 테스트한다: 손으로 쓴 `tests/fixtures/plans/*.json`(analyze·record·import·review 계획 포함)을 `db_pr stage/summary/publish/discard`에 직접 넣는다.
- 완료 기준: 테스트용 이슈 DB 레포(샘플 트리로 만든 임시 레포 또는 GHE 샌드박스)에서
  - 손으로 쓴 plan으로 `append`, `new-cause`, `new-type`, `unresolved`, `reclassify`가 모두 PR까지 생성된다. main에 없는 Jira의 `reclassify`는 거부되고, main에 이미 있는 Jira의 `append`는 중단된다
  - 손으로 쓴 `source: record` 계획이 같은 경로로 PR까지 가고, `summary`와 PR 본문에 "수동 기록"과 실행/건너뛴 검증이 나온다. `jira.origin: file` 계획은 "Jira 메타데이터: 오프라인 파일" 라벨이 붙는다. `signatures_pending` 새 원인은 `record` 계획에서만 적용되고(그 밖이면 거부), pending 피드백은 `source: analyze`에서만 포함된다
  - **pending 원인이 든 record PR이 main에 뒤처졌을 때 `sync-pr`(계획 재적용)가 그 원인을 pending 그대로 올린다**
  - `record` 계획의 `verify-resolution`이 기록 대상 Jira 자신을 evidence로 쓰면 거부된다. `new-cause` 뒤의 `verify-resolution`(evidence: `resolved` fixture)은 새 원인을 `verified`로 만들고, 순서가 반대면 거부된다
  - 같은 계획으로 `stage`를 두 번(수정 요청 재적용) 실행해도 `<wt>`의 diff가 한 번 적용한 결과와 바이트 단위로 같다 (이전 적용분이 남지 않음)
  - 작업 중 사용자 clone의 브랜치·워킹 트리가 바뀌지 않는다. **사용자 로컬 `issue/<KEY>` 브랜치(원격보다 앞선 커밋 포함)가 있어도, 그 브랜치가 사용자 clone에 checkout돼 있어도** stage·publish·discard가 그 브랜치를 바꾸지 않는다. discard 후 worktree, `tt/*` 브랜치, `state.json`, lock이 남지 않는다
  - `tt/<br>`가 다른 worktree에 checkout돼 있으면 `stage`가 종료 코드 2를 낸다
  - 도구 브랜치 잔여물, 원격에 있는 브랜치 각각에서 Step 8-2 선택지대로 동작한다 ("plan으로 브랜치 갱신"은 lease push)
  - `source`가 9개 값 밖(예: `migrate`)인 계획은 `db_add apply`가 거부한다. `stage --dry-run`은 gh 인증 없이 확인 화면(`summary`)까지 간다. `TT_FORCE_VERIFY_EXIT=3`이면 `stage`가 `3`을 집계한다
  - **drift**: 계획의 `set-resolution` 대상 원인의 해결책을 다른 PR이 main에서 먼저 바꾸면 `stage`가 적용 전에 drift(종료 코드 1)를 낸다. 결정을 계획에 반영하고 `base_sha`를 바꾸면 통과한다. 계획의 `update-parser-rule` 대상 키를 main이 기능 필드까지 바꿨으면 drift이고, 이력 필드만 바꿨으면 drift가 아니다. 계획의 `allow-cause` 대상 fixture의 `also_allowed`를 main이 먼저 바꿨으면 drift다
  - **`allow-cause`**: `.expect.yaml`이 없는 양성 fixture에 적용하면 기본 기대값 + `also_allowed`로 파일을 만들고, 있으면 `also_allowed`에 추가한다. 자기 원인·같은 유형 원인을 넣으면 거부된다. `summary`의 리뷰어에 그 fixture 카테고리 오너가 들어간다
  - 같은 계획을 두 번 `stage`해도 피드백 파일의 이름과 `date`가 같다(`feedback.date`)
  - `verify-resolution`의 evidence가 없는 Jira 키·fixture 경로면 거부된다. `update-fix`로 `fixed` 원인을 `fix-submitted`로 바꾸는 계획은 거부되고, `not-a-bug` 원인을 `fix-submitted`로 바꾸는 계획은 통과한다
  - **두 브랜치에서 같은 유형에 동시에 같은 번호(DATA-001-03)의 새 원인과 같은 번호의 fixture를 만들고** 순서대로 머지할 때, 두 번째 PR이 `sync-pr`(계획 재적용)로 텍스트 충돌 없이 DATA-001-04로 올라가고, 먼저 머지된 DATA-001-03과 섞이지 않고, PR 제목·본문이 새 ID로 고쳐진다
  - `sync-pr` 재적용 때 이전에 이 PR로 올린 pending 피드백(`included_pending`)이 다시 포함된다
  - 원격 브랜치가 마지막 publish(`pr.head_sha`) 이후 다른 사람에 의해 바뀌었으면 `sync-pr`가 바뀐 내용을 보여주고 덮어쓰기/중단을 묻는다. 계획이 없는 브랜치는 `sync-pr`가 수동 재동기화 절차를 안내하고 아무것도 바꾸지 않는다
  - `sync-pr` 도중 원격 브랜치가 바뀌면 push가 거부된다. 승인 후 파일이 바뀌거나, 커밋이 둘이거나, 커밋 메시지나 브랜치가 `state.json`과 다르면 `publish`가 거부된다
  - `cleanup --dry-run`은 현재 작업 키의 worktree를 대상에 넣지 않고, `--yes` 없이는 아무것도 지우지 않는다. discard 없이 끝나는 경로(읽기 전용 종료, 계획 저장 후 종료)에서 `lock release`가 호출되면 다음 작업이 바로 lock을 잡는다
  - 변형 `issue-db-dup-id`(make_variant_dbs.py가 테스트 때 생성)에서 사후 lint가 ID 중복과 Jira 중복을 보고한다 (아무것도 바꾸지 않는다)
  - 기존 fixture 결과를 바꾸는 규칙은 R4에서 차단된다
- 읽을 문서: `contracts.md`, `01-architecture.md §3.1`, `02-config.md §5.3`(리뷰어 계산), `03-issue-db.md §5.4·5.5·5.7·5.9`, `04-parser-matching.md §5.8`, `05-verification.md §5.12 (1)`(뼈대·수동 기록 검증 표), `06-collaboration.md §6.2·6.3`, `07-workflow.md §Step 8·공통 쓰기 절차·record·sync-pr`

### Phase 8. git hooks(pre-commit·pre-push)와 Claude hooks
- 할 일: Phase 1의 스텁을 실제 `.githooks/pre-commit`(`db_precommit.py --db "$(git rev-parse --show-toplevel)"`)과 **`.githooks/pre-push`**(base 브랜치 대상 거부, `TT_PUBLISH_TOKEN`이 `state.json`의 `approved_hash` 또는 `manual`이 아니면 거부)로 교체, `db_precommit.py`(오케스트레이터, `--staged`), `guard.py`와 `hooks.json`(`08-safety.md §9`의 **8종**, 레포 판별, `mcp__.*` 매처 + 서버 판정, 최선 노력 명령 파싱, **Write/Edit 경로 판정**). hook 설치 자체는 Phase 6 setup에서 이미 한다.
- 완료 기준: 수동 편집한 README 커밋이 차단된다. PII가 든 커밋이 차단된다. `plugin.scripts_path`가 무효하면 커밋이 차단되고 안내가 나온다. `--no-verify`/`-n`/`-c core.hooksPath=` 우회와 `core.hooksPath` 변경·해제가 차단되고(정확히 `.githooks`로 설정하는 명령은 허용되어, hooks 설치 후 setup을 다시 실행해도 통과한다), `core.hooksPath`가 정확히 `.githooks`가 아닌 레포(unset, 다른 값)에서는 이슈 DB 커밋이 차단된다. worktree에서 커밋하면 그 worktree가 검사된다. read_tools에 없는 Jira 서버 도구 호출이 거부되고 다른 MCP 서버 도구는 영향이 없다. `cd <이슈 DB> && git commit --no-verify`도 차단된다. `git push origin HEAD:refs/heads/main`도 main push로 차단된다. `python -c`로 실행한 `git push origin HEAD:refs/heads/main`은 guard를 지나치지만 `pre-push`가 거부한다. `TT_PUBLISH_TOKEN` 없이 push하면 `pre-push`가 거부하고, `db_pr publish`의 push와 `TT_PUBLISH_TOKEN=manual`은 통과한다. Write 도구로 사용자 clone 안의 `type.md`를 쓰면 거부되고, `<work_dir>/<키>/wt/` 안의 파일 쓰기는 허용된다. config가 없으면 git 규칙이 적용되지 않는다. **다른 레포에서는 어떤 git hook 규칙도 동작하지 않는다.** `TT_FORCE_VERIFY_EXIT=3`으로 `db_verify rules`가 종료 코드 3을 내면 pre-commit이 경고 후 통과한다.
- 읽을 문서: `contracts.md §3.2·종료 코드·브랜치`, `08-safety.md`, `06-collaboration.md §6.3`, `02-config.md §4`

### Phase 9. 스키마 마이그레이션
- 할 일: `db_migrate.py`(`--to`: `--db`가 clone이고 현재 브랜치가 `migrate/schema-v<N>`이며 깨끗할 때만 워킹 트리를 직접 바꿈, `upgrade-plan`), 예시 마이그레이션 1개(`upgrade_plan()` 포함), `migrate` 커맨드(실행 후 `db_build --write` → `validate` → 커밋 → push 안내. PR·계획·lock 없음)
- 완료 기준: 예시 마이그레이션이 샘플 이슈 DB를 새 버전으로 올린다. `migrate/schema-v<N>` 브랜치에서 `migrate --to <N>`을 실행한 뒤 `config.py check`·pre-commit·`validate`가 버전 불일치를 차단하지 않고 통과하고, 다른 브랜치 이름에서는 `migrate --to`가 종료 코드 2로 거부되며 버전 불일치도 여전히 차단된다. 옛 `schema_version`의 계획은 `db_add apply`가 거부하고(종료 코드 2), `upgrade-plan`으로 올린 계획은 `sync-pr`(재적용)로 새 스키마에서 올라간다. 버전 범위 밖, `generator_version` 불일치(local 모드)에서 `migrate/schema-v<N>` 브랜치 외 모든 쓰기가 막힌다.
- 읽을 문서: `contracts.md`, `06-collaboration.md §6.3·6.4`

### Phase 10. 검증
- 할 일: `db_verify.py`(`rules` R1~R6 완성 — 의존 그래프 기반 대상 계산, 증상 시그니처의 R1·R3, R1 흔적 검사, `skipped` 사유(`fixture 없음`·`음성 fixture 없음`은 `review_required`, `시그니처 없음(pending)`), `--draft` worktree, R5 `needs-approval`; `resolution`, `fix`(둘 다 `--plan --draft` 포함) 판정 — 시나리오 흔적 전제), `db_regress.py --events-diff`, 검증 op(`set-resolution`, `verify-resolution`, `verify-fix`)의 판정 연결(`verify-fix` passed는 빌드 있는 `fixed_in` 필요, pending 원인의 `verify-resolution` 거부), `update-fix` open 되돌림 시 이력 보존(`history`), `db_lint` 검증 규칙(검증 없는 fixed 금지, 코드·설정 수정 유형의 fixed에 scenario/recovery 필수). 테스트용 이슈 DB 변형 `issue-db-verify`(make_variant_dbs.py가 테스트 때 생성)에서 CALL-001-01을 `fix-submitted`로 바꾸고 수정 전/후/재발/시나리오 없음 fixture를 만들어 쓴다.
- 완료 기준:
  - 너무 넓은 원인 시그니처 초안(음성 fixture 또는 같은 카테고리 다른 유형의 양성 fixture에서 C=1)이 R3에서 걸린다
  - 새 시그니처가 **다른 카테고리**의 양성 fixture에서 C=1이면 R4에서 걸리고, 결과에 그 fixture와 `allow-cause` 초안이 나온다. 그 fixture의 `.expect.yaml`에 `also_allowed`로 그 원인을 넣으면 R2·R3·R4가 통과한다. 반대로 `also_allowed`에 없는 원인이 C=1이면 여전히 실패한다
  - `scoring.cause_weight`를 0.5, `confidence.medium`을 0.7로 바꿔도 R2·R3·R4·`db_regress` 결과가 같다(판정이 S/C만 쓴다)
  - 새 유형의 증상 시그니처가 다른 유형의 음성 fixture에서 S=1이면 R3에서 걸리고, 결과에 그 fixture가 나온다
  - extractor만 바꿔도 그것을 참조하는 시그니처의 원인이 R1·R2 대상이 된다
  - 기존 이벤트를 바꾸는 extractor 수정이 R5 `needs-approval`(종료 코드 3)로 표시된다
  - CALL-001-01 수정 후 로그(시나리오 흔적 있음)로 `db_verify fix` → `passed`. 손으로 쓴 `verify-fix {result: passed}` + `add-fixture(kind: fixed)` 계획을 `db_pr stage`에 넣으면 fixed 전환과 `CALL-001-01.fixed.<build>.log` 생성
  - 재발 로그 → `db_verify fix` `failed`. `verify-fix {result: failed}` 계획을 적용하면 open 전환, `ref`·`fixed_in`이 `verification_history`로 보존되고 비워짐
  - 증상만 남은 로그 → `partial`, 다른 원인 후보 출력. `partial` 계획 적용 시 `fix-submitted` 유지 + partial 이력
  - 시나리오 흔적 없는 로그 → `unknown`
  - scenario/recovery 시그니처가 모두 없는 코드 수정 유형 원인 → `db_verify fix`가 판정 없이 `unknown`(필수 시그니처 없음)
  - `fixed_in` 이전 빌드 로그, 빌드 없는 `fixed_in` → `db_verify fix` 중단(종료 코드 2). 빌드 없는 `fixed_in`에 `verify-fix passed` 계획을 적용하면 거부
  - `db_verify resolution`: recovery 없음 + 시나리오 흔적 없음 → `unknown`
  - 손으로 쓴 `record` 계획(`new-cause` + recovery 시그니처)에 `db_verify resolution --cause <temp_id> --plan --draft`로 해결책 적용 후 로그를 판정하면 `passed`이고, 이어서 `add-fixture(kind: resolved)` + `verify-resolution`을 넣은 계획을 `db_pr stage`에 넣으면 새 원인이 `verified`로 들어가고 lint가 통과한다
  - 그 카테고리의 모든 음성 fixture에 충족되는 scenario 시그니처 추가가 R1 흔적 검사에서 걸린다. 그 카테고리에 음성 fixture가 없으면 흔적 검사는 `skipped: 음성 fixture 없음`(`review_required: true`)이고 `pass`로 집계되지 않는다
  - `fixed` 원인의 재검증 로그가 증상만 남으면 `partial`이고, 그 계획을 적용하면 `fixed`가 유지된 채 `partial` 이력만 추가된다
  - 양성 fixture가 없는 새 원인은 R1·R2가 `skipped: fixture 없음`(`review_required: true`)이고 `pass`로 집계되지 않는다. `signatures_pending` 원인은 R1~R3 `skipped: 시그니처 없음(pending)`
  - 수정 후 fixture가 있는 원인의 시그니처를 넓히면 R3·R4에서 차단된다
- 읽을 문서: `contracts.md`, `05-verification.md`, `03-issue-db.md §5.4·5.9`, `04-parser-matching.md §5.11`

### Phase 11. 리뷰와 통계
- 할 일: `db_review.py`와 `review [category]` 커맨드 (`06-collaboration.md §6.6` 항목 전부), STATS 항목 완성(`06-collaboration.md §6.7`), 병합(`move/...`) 절차 지원, `db_search.py`(옛 ID → 새 ID 연결: `merged-into:` 체인과 `Renumbered:` 트레일러).
- 완료 기준: 변형 `issue-db-review`(make_variant_dbs.py가 테스트 때 생성)에 일부러 만든 케이스(오래된 unresolved, 낮은 수락률, 중복 후보, 지원 종료 버전, 빈 `android_versions`는 지원 종료가 아님, fixed 전환 불가, 시그니처 없는 원인, fixture 없는 원인, 사용자 진술만 있는 해결책, `also_allowed` 누적, 급증)를 리포트가 모두 잡고, `decision: manual` 피드백은 수락률에서 빠진다. 과거 `occurred_on`의 Jira를 한꺼번에 record한 경우는 급증으로 잡지 않는다. 병합 후, 그리고 `Renumbered:` 트레일러가 있는 커밋 뒤에 `db_search.py`가 옛 ID를 새 ID로 연결한다 (`search` 커맨드 연결은 Phase 12).
- 읽을 문서: `contracts.md §renumber 참조·상태 값`, `06-collaboration.md §6.5·6.6·6.7`, `03-issue-db.md §5.5`

### Phase 12. 나머지 커맨드
- 할 일: `09-commands.md §10`의 12개 커맨드를 얇은 래퍼로 만든다. 인자 없는 `validate`는 스크립트만 호출하므로 여기서 완성한다. `analyze`, `record`, `validate --cause`, `verify-fix`, `fix-submitted`는 Phase 13의 스킬을 호출하는 형태로 먼저 틀만 만든다. `commands/analyze.md` 예:

  ```markdown
  ---
  description: Jira 이슈와 logcat으로 telephony 이슈 분석 및 이슈 DB 분류
  argument-hint: <JIRA-KEY> [logcat 경로...] [--code <프로필|경로>] [--dry-run] [--jira-file <yaml>] [--analyzer | --no-analyzer]
  ---
  telephony-triage 스킬의 워크플로우(Step 0~8)를 다음 인자로 실행한다: $ARGUMENTS
  스크립트는 ${CLAUDE_PLUGIN_ROOT}/scripts/ 에서 호출한다.
  logcat 경로가 없으면 config의 log_dir에서 후보를 보여주고 선택받는다.
  --code가 없으면 Step 2-1에 따라 코드 경로를 묻는다.
  ```

  (`${CLAUDE_PLUGIN_ROOT}`가 본문에서 치환되지 않으면(S1) `plugin.scripts_path`를 쓰는 문구로 바꾼다.)
  `tools/offline_eval.py <라벨셋.yaml>`도 여기서 만든다: 항목마다 `analyze --dry-run --jira-file`과 같은 경로(파서 → 매처)를 스크립트로 돌려 1위 정확도, 상위 3 포함률, 오탐률을 표로 낸다(스킬을 부르지 않는다). 사외는 합성 라벨셋(`tests/fixtures/offline-eval-sample.yaml`)으로 시험한다.
- 완료 기준: 로컬에서 플러그인을 로드한 뒤 `setup`, `sync`, `search`, `sync-pr`, `preview`, `review`, `migrate`가 동작하고, `validate`(인자 없음)가 lint·전체 회귀·R1~R5를 실행한다. `sync` 끝에 닫힌 PR의 오래된 작업 디렉토리 후보가 나오고 확인 전에는 지워지지 않는다. `offline_eval.py`가 합성 라벨셋에서 정확도 표를 낸다. 스킬 연결 커맨드 5개는 로드되고 인자 힌트가 보인다. `commands/` 파일 목록(12개)이 `01-architecture.md §3`, `09-commands.md §10`과 같다.
- 읽을 문서: `09-commands.md`, `01-architecture.md §3`, `07-workflow.md §validate·sync-pr·record`, `contracts.md §3.2`

### Phase 13. SKILL.md (skill-creator 사용)
- 할 일: `10-skill-eval.md`의 구성과 입력으로 skill-creator 스킬을 실행한다. **SKILL.md 본체는 analyze 핵심 흐름만(500줄 이내)**, 나머지 흐름은 `reference/`로 나눈다 (`10-skill-eval.md §SKILL 구성`). Step 5-1 심층 분석(`analyzers`, 기본 `ask`, `--analyzer`/`--no-analyzer`)과 `jira.tools` 호출을 포함한다 (모의 분석 스킬로 시험).
- 완료 기준: `10-skill-eval.md`의 트리거 테스트 전 항목, eval 45개(수동 기록 30~38, 기존 자산 39~41, `allow-cause` 42, Jira 텍스트 마스킹 43, 슬롯 44, 후보 없음·범위 밖·bugreport 45 포함) 통과. 결과물은 `plugin/skills/telephony-triage/`. SKILL.md 본체가 500줄 이내이고, 각 커맨드는 자기 흐름의 `reference/` 파일만 읽는다. `analyze`, `record`, `validate --cause`, `verify-fix`, `fix-submitted` 커맨드가 스킬과 연결되어 동작한다.
- 읽을 문서: `10-skill-eval.md`, `07-workflow.md`, `contracts.md`, `16-existing-assets.md §16.1·16.5`, `12-principles.md`, 그리고 `10-skill-eval.md §skill-creator 입력`의 db-authoring 구성 목록에 있는 절

### Phase 14. 배포와 파일럿
- 사내 보완 모드는 `15-local-draft.md §15.5`의 **S-7**로 한다(내용 같음).
- 할 일: `marketplace.json`으로 사내 마켓플레이스 등록(S2). 이슈 DB README에 설치/시작 가이드 링크.
- 파일럿 전 게이트: `tools/offline_eval.py`로 과거 Jira 라벨셋(`15-local-draft.md §15.5` S-5)의 1위 정확도가 합의한 기준 이상인지 확인한다. 파일럿: 카테고리별 오너가 실제 이슈 10~20건씩 처리한다. 첫 월간 리뷰를 진행한다. placeholder 규칙 확정, 시그니처 오탐/누락, 충돌(drift·ID 중복·`also_allowed` 발생 빈도 포함), 온보딩 시간, PR까지 걸린 시간과 중도 취소 비율(기여 부담), 분석 스킬 호출 비율과 토큰 사용을 점검한 뒤 전체 확대한다.
- 이후 확장 후보: Jira 첨부 자동 다운로드, `99-deferred.md`의 설계(3-way replay, 사후 ID 재배치 자동화, 동시 작업을 위한 읽기 임대). 파일럿에서 충돌·동시 작업이 병목일 때만 검토한다.
- 완료 기준: 파일럿 결과(처리 건수, 오탐/누락, 충돌, 온보딩 시간, PR 소요 시간, 취소 비율)를 사용자에게 보고하고 전체 확대 여부를 결정받는다.
- 읽을 문서: `14-site.md`(S2), `06-collaboration.md §6.6·6.9`, `01-architecture.md §3`
