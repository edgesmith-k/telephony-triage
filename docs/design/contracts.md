# 공통 계약 (Single Source of Truth)

> 여러 문서가 참조하는 정의는 **이 파일에만** 둔다. 다른 문서는 표를 복사하지 않고 `contracts.md §<절>`로 참조한다.
> 여기의 값이 다른 문서와 다르면 이 파일이 우선이다. 다른 문서를 고칠 때 이 파일도 함께 확인한다.

목차
- §3.2 스크립트 CLI 계약 (공통 규칙, `--db` 기본값, 스크립트별 출력·동작, `db_pr` 세부: 도구 브랜치·세션 lock·작업 상태 파일). 서브커맨드·옵션과 `analysis.json` 키는 `contracts-cli.md`(생성)
- §종료 코드
- §작업 계획 (plan.json 형식, `source`, op 표, drift)
- §fixture (명명, 기대값)
- §브랜치
- §renumber 참조
- §상태 값
- §기존 자산 연결 계약 (Jira 도구 매핑, 파서 백엔드, 외부 파서, 분석 스킬, `SITE_PATHS`)

---

## 3.2 스크립트 CLI 계약

### 공통 규칙

- 모든 스크립트는 `${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py`로 호출한다 (`01-architecture.md §3`).
- 결과는 `--json`일 때 stdout에 JSON으로 낸다. 로그 원문은 출력하지 않는다.
- 종료 코드는 §종료 코드 표를 따른다.
- **`--db <path>` 기본값** (`guard.py`·`db_pr.py` 제외 전부. `db_pr.py`는 사용자 clone·스냅샷·작업 worktree를 동시에 다루는 오케스트레이터라 `--db`를 받지 않고 항상 config의 `issue_db.path`를 쓴다):
  1. `--db`를 주면 그 값.
  2. 생략했고 cwd가 이슈 DB 레포(또는 그 worktree) 안이면 `git rev-parse --show-toplevel`. 판별 기준은 toplevel에 `issue-db.config.yaml`이 있는지다.
  3. 그 밖에는 config의 `issue_db.path`.
- **`--db` 위치**: 서브커맨드가 있는 스크립트(`db_verify`, `db_add`, `db_pr` 등)는 `--db`를 서브커맨드 앞뒤 어디에 줘도 된다(공통 부모 파서). 문서 예시는 서브커맨드 뒤에 쓴다.
- **명시 규칙**: 아래 호출은 기본값에 기대지 않고 항상 `--db`를 쓴다.
  - analyze·record 읽기(파서·매처·lint·캐시·검색·`config.py check`): `--db <work_dir>/_snapshot` (`07-workflow.md §Step 1`)
  - Step 8, `record`의 쓰기, `sync-pr`, `verify-fix`, `validate --cause`, `fix-submitted`, import/review/move 계획 PR: `--db <wt>` (작업 worktree)
  - `.githooks/pre-commit`: `--db "$(git rev-parse --show-toplevel)"`
- **`--staged`**: index 내용을 기준으로 검사한다. 워킹 트리의 unstaged 변경은 무시한다. 비교 기준(base)은 `HEAD`다.
- **`--changed <ref>`**: `git merge-base <ref> HEAD`와 현재 트리(`--db`)의 차이만 검사한다. 뒤처진 브랜치에서 그사이 main에 들어온 변경이 범위에 섞이지 않게 하기 위해서다. 비교 기준(base)은 그 merge-base다.
- **범위 확장 규칙**: `parser-rules/` 변경이 범위에 포함되면 `db_regress`의 `--changed`/`--staged`는 전체 fixture로 확장한다.
- **빌드명 정규화** `sanitize_build(<빌드>)`: `[A-Za-z0-9._+-]` 밖의 문자를 `_`로 바꾸고, 두 개 이상 연속된 `.`은 `_` 하나로, 첫 글자 `.`와 끝 글자 `.`는 `_`로, 끝의 `.lock`은 `_lock`으로 바꾼다. fixture 파일명(§fixture)과 브랜치 이름(§브랜치)이 같은 함수(`common/`)를 쓴다. 브랜치 이름은 만들기 전에 `git check-ref-format --branch`로 한 번 더 검사하고, 실패하면 종료 코드 2다.
- **작업 키 검증**: 작업 키·경로·브랜치에 쓰는 Jira 키는 쓰기 전에 `jira_key_regex`(`02-config.md §5.3`)로 검사한다. analyze·record는 이것을 첫 동작으로 한다 (`07-workflow.md §Step 0`).
- **마스킹 함수**는 `common/`에 있고 `mask_pii.py`와 `parse_logcat.py`가 공유한다. 이미 마스킹된 텍스트(`<IMSI#1>` 같은 치환 토큰)를 다시 넣어도 결과가 같다 (멱등). 입력에 이미 토큰이 있으면 새 값의 번호는 종류별 기존 최대 번호 다음부터 준다 (`08-safety.md §8`).
- **설정 읽기**: `parse_logcat.py`는 사용자 config를 읽지 않는다(시각은 `--tz`/`--year` 인자). 파서 백엔드·외부 파서 설정과 플랫폼 상수(`platform.*`: 슬롯 표기·RIL 태그·bugreport 섹션 헤더, 소스 트리의 `required_dirs`·`version_sources`는 `code_roots.py`)는 플러그인 `site-defaults.yaml`에서만 읽는다(`platforms.load()`, `02-config.md`). `platform:`이 잘못되면 종료 코드 2. 설정 층 순서는 코드 기본값 ⊂ site-defaults ⊂ 이슈 DB 규칙이다(마지막 층은 아직 구현하지 않았다). 이 파일이 없으면 모든 스크립트가 종료 코드 2로 멈춘다("사내 기본값 없음(S-3 미완료)"). **예외는 `guard.py`**: 모든 도구 호출에 걸리는 PreToolUse hook이라 2로 끝나면 이슈 DB와 무관한 작업까지 막히므로, 경고만 내고 사용자 config로 판정한다(`08-safety.md §9` 설정 없음 처리). `site-defaults.example.yaml`은 코드가 읽지 않는다 (§기존 자산 연결 계약).

### 스크립트별 출력·동작

서브커맨드·옵션 전체(사용법·기본값·상호 배제)와 `triage.py run`의 `analysis.json` 키 구조는 `contracts-cli.md`(생성, `tools/gen_contracts.py`)에 있다. 이 표는 출력과 동작만 적는다.

| 스크립트 | 서브커맨드 | 출력·동작 |
|---|---|---|
| `config.py` | `show` / `check` / `sync-scripts-path` / `set` | config 내용(`--keys`면 점 표기 키만 `{user_config, values{키: 값}, missing[]}`, 없으면 이전과 같다), 호환성 판정(`writable`, `push_allowed`, 사유). `--for`의 기본값은 `write`(스키마·생성기·파서 백엔드·외부 파서 버전 + gh 인증). `dry-run`은 버전만 보고 gh 인증은 보지 않는다(`push_allowed: false`). `--db`의 현재 브랜치가 `migrate/schema-v<N>`이면 스키마·생성기 버전 불일치를 차단하지 않고 gh 인증만 본다(마이그레이션이 버전을 올리는 커밋이므로, `06-collaboration.md §6.4`) |
| | `site-defaults` | `site-defaults.yaml` 내용 |
| | `init` | config 생성 (setup 1). `--answers`가 없으면 stdin으로 항목별로 묻는다. 경로가 없으면 거부한다. 홈·work_dir은 권한 700 |
| | `jira-candidates` | 등록된 MCP 서버에서 `jira.tools`·읽기 도구 후보 (setup 4). `exclude_servers` 적용 |
| | `set-jira` | 사용자가 확인한 값을 저장. `read_tools`에 `jira.tools` 값을 포함한다 |
| | `install-hooks` | `git config core.hooksPath .githooks`, 값이 정확히 `.githooks`인지 확인 (setup 5) |
| | `gh-status` | gh 인증 확인 (setup 9). 실패면 로그인 안내와 종료 코드 2 |
| `code_roots.py` | `suggest` / `validate` / `resolve` / `find-symbol` | `validate`는 aosp에 `platform.source_tree.required_dirs`가 모두 있어야 한다(기본 `frameworks/opt/telephony`). 후보, 검증 결과, 경로 |
| `parse_logcat.py` | `parse` / `markers` | 이벤트 JSON (`07-workflow.md §Step 3`). 이벤트마다 `phone_id`(슬롯, 없으면 `null`)와 `line_ref`(`{file_index(입력 로그 목록의 0부터 순번), line_no(1부터, 외부 파서 이벤트는 null)}` 또는 `null`, 이벤트의 마지막 키, `04-parser-matching.md §5.8 (6)`). 머리에 `coverage: {first_ts, last_ts, window_in_range: true\|partial\|false, clock_anomalies: [{ts, kind: backward\|jump, delta_sec}]}`(`--full`이면 `window_in_range: true`). 최상위 `uncollected_tags: [{tag(마스킹, ≤40), lines, warn(W/E/F 줄 수)}]`(있을 때만, 상위 5개, `(W/E/F 수, 줄 수, 태그)` 내림차순): `tags.yaml`에 없어 줄 레코드로 남지 않고 버려진 줄을, **수집된 줄 레코드와 같은 pid**의 것만 `(태그, pid, 레벨)`로 센 관측 누락 힌트다(pid가 없는 줄은 건너뜀. 분류·점수에 쓰지 않음, `07-workflow.md §Step 3`). `--mask`면 **extractor 실행 전에** 각 줄(백엔드·외부 파서 이벤트의 `msg`·`fields` 포함)을 마스킹하고 `masked: true`, 아니면 `masked: false`. `--no-external`은 분석 모드 디버그용이다 (§기존 자산 연결 계약). `--between`은 명시 구간이다(타임존 있는 ISO 둘, 시작 ≤ 끝이 아니면 종료 코드 2, `input.mode: "between"`, `input.window`는 그 구간). **`markers <logcat...> --rules <db>/parser-rules [--tz] [--year] [--step-events]`**: 시험 자동화의 스텝 마커 줄을 모은다(`07-workflow.md §Step 3`). 마커 태그는 `tags.yaml`에 없으므로 `parse` 출력이 아니라 백엔드의 줄 레코드(`event: null`)에서 `TAG: msg` 전체를 `site-defaults.yaml`의 `failed_step.marker_patterns`(이름 그룹 `step`·`status`)로 찾는다(**사용자 config로 덮어쓸 수 없다**). 패턴은 `matcher.pattern_timeout_ms` 안에서 원문에 돌려 맞은 줄만 고르고, 그 줄만 마스킹한 뒤 마스킹된 텍스트에서 그룹을 다시 뽑는다(원문 값은 출력에 나가지 않는다). 출력 `{schema, markers: [{ts, step, status: start\|pass\|fail, tag, msg(≤200, 마스킹)}], total, truncated, coverage: {first_ts, last_ts}, warnings[]}`(상한 2000, 정규식 오류·시간 초과는 경고 `marker-pattern`). 패턴이 비면 마커 없이 `coverage`만 낸다(**기본은 비어 있다** — 실제 logcat에는 스텝 마커가 없다). **`--step-events`**: 이슈 DB `issue-db.config.yaml`의 `step_events`(`02-config.md §5.3`; 스텝 이름은 인자로 받지 않는다) 규칙마다 로그 흔적을 더한다 — 출력에 `step_events: [{rule(규칙 목록 위치), ts, seq(파서 줄 순번), label(이벤트·요청·태그 이름, 로그 본문 없음)}]`(`(ts, seq, rule)` 순, 규칙당 1000·전체 5000 상한 → 경고 `step-events-truncated`+`truncated_rules`, 잘못된 규칙은 경고 `step-event-rule`로 건너뜀). 한 번의 파싱: `ril` 규칙은 원 레코드의 `ril`(요청·방향), `match`는 마스킹한 `TAG: msg` 검색, `event`는 `postprocess` 이벤트의 이름·`fields` 정규식. 플래그가 없으면 출력은 그대로다 |
| | `extract-bugreport` | bugreport에서 logcat 섹션(system/radio/main)만 `<dir>/logcat-<buffer>.txt`로, 헤더의 `Build fingerprint`·`Build` 줄만 `<dir>/build.json`으로 꺼낸다. **dumpsys 등 다른 섹션은 읽지 않는다.** 섹션 헤더 형식은 S21. 결과 목록 JSON |
| | `cut` | 판별 근거(또는 지정 시각) 주변 최소 구간. 마스킹 함수를 거친 **마스킹된 상태로만** 파일을 쓴다. `--evidence`는 근거의 `line_ref`가 가리키는 줄(입력에 있고 (시각, 태그)가 같을 때)을 앵커로 삼고, 아니면 그 근거만 (시각, 태그)가 같은 모든 줄로 대신하며 경고 `evidence-ref-mismatch`를 낸다(`parse`와 **같은 로그를 같은 순서로** 줘야 한다). 출력에 `anchors_by: {line_ref, ts_tag}`(방식별 근거 수). 종료 코드는 그대로다 |
| `mask_pii.py` | — (파일) | 치환 결과 또는 검출 목록 |
| | — (`--events`) | 외부에서 받은 이벤트 JSON의 `msg`와 `fields`를 마스킹, `masked: true`. 분석 경로는 `parse --mask`를 쓴다 |
| `jira_fields.py` | `check-key` / `extract` | `check-key`: `{key, valid, regex}`, 맞지 않으면 종료 코드 1. `extract`: `{key, key_valid, origin, jira: {key, origin, model, sw, android_version, carrier, occurred_on}, occurred_at(UTC), occurred_at_local, logcat: {tz, year, year_source}, sim_slot, components[], text: {summary, description, comments[], comments_total}(마스킹됨), missing[], meta_out}`. **선택 키(실패 스텝, 있을 때만)**: `text.test_steps`(마스킹 ≤1000자), `failed_step_auto {text, source}`(자동: field > description > test_steps), `failed_step {text, source}`(cli > 자동 > steps_file; source = cli\|field\|description\|test_steps\|steps_file), `jira.failed_step`, `warnings[]`(정규식 오류, 읽지 못한 steps-file). `missing`에는 넣지 않는다. 코멘트 예산: `--comments last:<N>`은 뒤에서 N개, `--comment-chars <N>`은 하나당 N자(기본 `all`·0 = 자르지 않음). `--meta-out`은 `match_signatures --jira-meta` 입력 `{key, occurred_at, sw, summary, description}`(`failed_step`은 있을 때만 더한다). `--consume`은 읽은 원본을 지운다(원문을 work_dir에 남기지 않음, `08-safety.md §8.1`). 코멘트 작성자 등 사람 이름 필드는 내지 않는다 |
| `match_signatures.py` | — | `--jira-meta`의 `failed_step`은 선택(키워드 보너스 입력). 후보 목록 `[{type, cause, score, confidence, S, C, evidence[], fix_judgement, related[]}]`(근거 `{signature, condition, ts, tag, msg, event, fields, phone_id, line_ref, event_index}` — `line_ref`는 이벤트의 로그 줄 위치, `event_index`는 입력 `events[]` 안의 순번이며 판정·점수에는 쓰지 않는다)와 후보 유형의 `pending_causes[]`(시그니처 없는 원인). `--top N`(기본 3)이면 후보 N개, `types[]`는 S=1·`causes[]`는 C=1인 것만, `pending_causes[]`는 N개만 내고 뺀 개수를 `omitted`에 적는다. 판정 목록 전체는 `--top 0`(회귀·검증 호출자는 함수를 직접 부르므로 영향 없음). 입력 이벤트가 `masked: true`가 아니면 종료 코드 2. 원인 평가 범위는 모드별로 다르다 (`04-parser-matching.md §5.11 (1)`). 후보 정렬 = score 내림차순, 동점은 bonus(근접+키워드) 합 내림차순, 다음 유형·원인 ID (`04 §5.11 (2)`). **스텝 기준 우선 유형**(분석 모드이고 `--jira-meta`에 `failed_step`이 있을 때만): 우선 유형 후보는 순위 키에만 `scoring.step_focus_bonus_max`를 더해 정렬한다(키 `(-(score+step), -(근접+키워드+step), 유형, 원인)`, `score`·`confidence`·S·C 불변). 있을 때만 후보 `bonus.step`과 최상위 `step_focus: {types[], by{유형: ["records:N"\|"map"]}}`를 낸다. 회귀·검증 모드는 우선 유형·새 키 없음(출력이 이전과 같다). 설정은 `issue-db.config.yaml`의 `scoring.step_focus_bonus_max`(0~0.1, 기본 0.05)·`step_focus: {min_records(기본 2, ≥1), map[{pattern, types[], categories[]}]}`이고 `db_lint`가 검사한다(값 오류는 `schema`, 안전하지 않은 `pattern`은 `regex-unsafe`) `confidence`는 규칙 일치 수준이며 진단 신뢰도·자동 게시 근거가 아니다 |
| `db_search.py` | — | `{query, kind: type-id\|cause-id\|jira\|keyword, terms[{term, aliases[]}] (keyword만), results[], links[], git_history}`. `results[]`는 유형·원인(해결책·수정 상태·`related`·`secondary_categories`·`code_refs[{ref, symbol, android_versions}]`·Jira 최근 5건 `jira`·`jira_latest`)·Jira 기록. keyword는 질의 전체의 부분 일치(옛 순서, `phrase: true`)가 먼저, 이어서 단어별 검색(불용어·조사·부정 접두 제거, `GLOSSARY.md` `## 검색 별칭`, 위치 가중치 3·2·1, `matched` ≥ 최대치의 절반, Jira는 최대치만)이 `matched[]`·`score`·`phrase: false`로 덧붙는다(검색용, 분류·매칭에 쓰지 않음). 유형 항목에도 `jira`(최근 5건, 미해결 포함)·`jira_latest`. 코드·설정 수정 유형이면서 scenario·recovery 시그니처가 없는 원인(pending 제외)에만 `verify_fix_blocked`(사유 문자열)가 붙는다(`db_verify fix`가 종료 코드 2로 거부하는 조건, `99-deferred.md §F`; 기본 출력 불변 원칙의 예외이고 다른 원인 항목은 바이트 그대로, `--format markdown`은 렌더하지 않는다). 드라이버 3, search 10으로 부른다. 옛 ID → 새 ID 연결은 `links[]` `{from, to, via: merged-into\|renumbered, commit?, date?}`와 결과의 `current`(merged-into 체인의 끝)·`merged_from` (§renumber 참조). 결과가 없어도 종료 코드 0. `--format markdown`(opt-in, 기본 `json`)은 `reference/search.md §3` 보여주기 규칙의 마크다운을 낸다(전체 결과에서 렌더하고 `--brief`는 무시, `--json`과 함께 쓰면 종료 코드 2). `--brief`(opt-in, 기본 출력 불변)는 항목에서 `path`·`chain`·`merged_from`·`code_refs`·`resolution_type`·`signatures_pending`·`type_title`·`category`와 빈 값·id와 같은 `current`, 최상위 `db`를 뺀다(`links[]`는 그대로, `code_refs`·병합 체인이 필요한 호출·record 대화형 후보 보기에는 쓰지 않는다) |
| `db_add.py` | `apply` | 변경 파일 목록, ID·fixture 번호 할당 내역 |
| | `drift` | 계획의 `base_sha` 이후 `<ref>`에서 계획 대상이 바뀐 목록 `[{op_index, op, target, field, plan_value, plan_base_value, current_value}]` (§작업 계획 drift)와 `ids_at_base`(계획에 `new-type`·`new-cause`가 있으면 `base_sha` 트리 기준으로 할당했을 임시 ID `[{temp_id, id}]`, 없거나 계산할 수 없으면 `null`). `base_sha`가 없거나 문자열이 아니면 종료 코드 2. 아무것도 바꾸지 않는다 |
| | `renumber` | 브랜치 안 재할당 내역 (직접 편집한 브랜치의 수동 보조. "내 ID"만 대상, §renumber 참조) |
| | `check-ids` / `similar` | ID 충돌 목록 / 유사 유형 상위 3개 |
| `db_build.py` | — | 생성 파일 또는 차이 목록 |
| `db_lint.py` | — | 오류/경고 목록. `issue-db.config.yaml`의 `step_events`는 형식 오류를 `schema`, 대상이 정확히 하나가 아님(`observable: false`면 없어야 함)·없는 `event`(extractor 이벤트 ∪ 예약 `ril_*` ∪ `builtin.*`이 아님)·`ext.*`(미지원)·없는 `ril` 이름·잘못된 `dir`·`event` 없는 `fields`를 새 코드 **`step-event`**, 패턴 안전성을 `raw-identifier`·`fixed-token`·`regex-unsafe`로 보고한다 |
| `db_regress.py` | — | fixture별 기대·실제 결과, 이벤트 변화. 음성 fixture 실패면 S=1이 된 유형과 시그니처 전역 키를 함께 낸다. `--events-diff`는 현재 트리의 **모든** fixture를 `<ref>` 트리의 parser-rules와 현재 parser-rules로 파싱해 이벤트(줄 레코드 제외)를 비교한다: 식별 `(ts, phone_id, tag, event)`, `fields`가 다르면 `changed`, 한쪽에만 있으면 `added`/`removed`. 출력 `{ref, base_sha, summary: {fixtures, added, removed, changed, existing_changed}, fixtures: [{fixture, added[], removed[], changed[], existing_changed}]}`(변화 있는 fixture만). 판정하지 않으므로 종료 코드는 0(사용 오류 2) |
| `db_verify.py` | `rules` | R1~R6 결과표 `[{id, status, reason, targets[], review_required, checks[]}]` (상태는 §상태 값)와 `changes`(대상 계산 근거). 기본 출력은 행 6개를 모두 내되 **pass 행만** 세부를 접는다(`checks_passed: n`, 최상위 `folded` 한 줄). `fail`·`skipped`·`needs-approval`·`review_required` 행은 `checks[]`·`allow_cause_drafts` 등 세부 전부. `--verbose`는 전체. 종료 코드·status는 같다(`resolution`·`fix --plan --draft`가 끼우는 `rules`도 같다) |
| | `resolution` | 판정 `passed/failed/unknown`과 근거, 충족한 흔적 시그니처와 그 시각 |
| | `fix` | 판정 `passed/partial/failed/unknown`과 근거, 충족한 흔적 시그니처와 그 시각 |
| `db_pr.py` | `lock status` / `lock acquire` / `lock release` | lock 보유자 `{job, command, started_at, updated_at, expired}`, 획득·해제 결과 |
| | `snapshot` | `{fetched, snapshot_sha, pulled, pull_skipped_reason}` (`07-workflow.md §Step 1`) |
| | `cleanup` | 비정상 종료로 남은 worktree·도구 브랜치(`tt/*`) 목록과 정리 결과. `--older-than`(기본 90)을 주면 계획의 PR이 닫혔거나 머지됐고(`gh pr view --json state`) `state.json`·파일 mtime이 그보다 오래된 작업 디렉토리(`<work_dir>/<작업 키>/`)도 대상에 넣는다. `sync`가 끝날 때 `--dry-run --older-than` 결과를 보여주고 사용자 확인 후 `--yes`로 지운다(자동 삭제 없음) |
| | `preflight` | `{tool_branch, user_branch: {exists, ahead_of_remote}, remote_sha, open_prs[], jira_in_main}` |
| | `stage` | 적용·검사 결과 JSON (변경 파일, ID 할당, `ids_at_base`, drift, 검사, 검증). stdout은 기본 요약(통과 단계·apply 세부를 접고 `detail`·`folded`), `stage.json`은 항상 전체, `--verbose`면 stdout도 전체. `--then-summary`: 종료 0·3이면 같은 프로세스에서 `summary --format markdown`을 이어 부르고 stdout은 그 마크다운만이다(`summary --format markdown`과 같은 바이트, stage JSON은 `stage.json`에만; `--json`·`--verbose`와 함께 쓰면 종료 코드 2). 종료 1·2는 기존과 같고 summary를 부르지 않는다. stage 성공·summary 실패는 종료 코드 2(stderr `stage 성공, summary 실패: <사유>`, stdout은 stage 요약 JSON + `summary_error`) — `summary --format markdown`만 다시 부른다. 계획을 읽을 때 형식부터 검사한다: JSON 아님·객체 아님·알 수 없는 최상위 키(`ops`→`operations` 같은 힌트)·필수 키 없음이면 종료 코드 2와 `계획 형식 오류:`로 시작하는 메시지(detail `unknown_keys`·`missing_keys`)이고 이전 작업 파일은 건드리지 않는다. 하위 스크립트가 Traceback으로 끝나면 메시지에는 마지막 줄과 "내부 오류 — 스크립트 버그로 보고"만 싣는다 |
| | `summary` | push 전 확인 화면 JSON (`07-workflow.md §Step 8-5`)과 `approved_hash`. `--format markdown`(opt-in, 기본 `json`)은 같은 확인 화면을 `reference/write-flow.md §4` 절 순서·문구의 마크다운으로 stdout에 낸다(JSON 대신, 머리의 대상 제목을 못 읽으면 "(제목 없음)", 마지막 줄 `approved_hash: <해시>`; 해결책 검증 상태는 계획 op만 보고 `<원인> — unverified(<사유>)`/`verified(verify-resolution)`로 내며 사유 고정 어휘는 "신규 원인 (new-cause)", "신규 유형 (new-type)", "해결책 변경 (set-resolution)", "근거: 사용자 진술"(새 원인 본문 `resolution_verification.method` 기준)이고 그 밖의 op는 op 이름만(예: `verify-resolution`) 보이며 해결책을 바꾸는 op가 없으면 "해당 없음 (이번 계획은 해결책을 바꾸지 않음)"; `--json`과 함께 쓰면 종료 코드 2; `state.json`·`pr.json`·종료 코드는 `json`과 같다). `ids[]` 행은 `{temp_id, id}`에 계획 당시 번호를 알 때만 `expected_at_base`가, 계획 `pr.ids`(publish 기록)와 다를 때만 `previous_id`가 붙고(`apply.ids`는 그대로), 달라졌으면 PR 본문 ID 줄이 `NEW-CAUSE-1 → DATA-001-04 (계획 당시 DATA-001-03)`이다. `fix_changes[]`(적용된 `update-fix`·`verify-fix` op가 있을 때만, **마지막 키**): `{cause, from, to, history{result, ref, fixed_in[빌드]}\|null, line}` — `from`은 stage 기준 커밋(`state.base_sha`)의 `type.md`, `to`는 작업 worktree의 `type.md`의 `fix.status`이고, `history`는 이번에 `verification_history`에 새로 들어간 항목이다. `line` 예: `CALL-001-01: fixed → open (이전 ref MOCKCL-12345·fixed_in MOCKB77_U2_20260920 → verification_history 보존, 결과 reverted)`. PR 본문에 `### 수정 상태 변경` 절로 줄을 싣는다 |
| | `publish` | push 결과, PR 번호·링크, `pr_ids_recorded`(계획 `pr.ids`를 기록했는지, §작업 계획 `pr`). `--commit`이면 `commit: {committed, sha?, skipped?}`, `--and-discard`면 `discard: {…}`(아래 `db_pr.py` 세부) |
| | `discard` | 정리 결과 |
| | `find-plan` | sync-pr 1~4번 보조: 계획 찾기·원격 변경 확인 |
| `db_precommit.py` | — | 검사 요약 (git pre-commit hook 전용) |
| `db_review.py` | — | 리뷰 리포트(Markdown, `--out`이면 그 파일). `--json`이면 `{db, head, as_of, category, owners, thresholds, feedback{total, manual, used_for_acceptance}, summary, items[{key, title, criterion, action, count, entries[], undetermined[]}]}`. 읽기 전용(lock·스냅샷 없음). 기준일은 실행일(`--as-of`로 바꿈). 항목 판정 세부는 아래 `db_review.py` 세부 |
| `db_migrate.py` | (`--to`) / `upgrade-plan` | 마이그레이션 결과 / 새 스키마로 올린 계획 (마이그레이션 모듈이 `upgrade_plan()`을 제공할 때만, 없으면 종료 코드 2). `--to`는 **`--db`의 워킹 트리를 직접 바꾼다**: `--db`가 이슈 DB clone이고 현재 브랜치가 `migrate/schema-v<N>`이며 깨끗할 때만 실행한다(아니면 종료 코드 2). 메인테이너가 자기 로컬 브랜치에서 직접 편집하는 흐름이므로 계획·worktree·lock을 쓰지 않는다 (`06-collaboration.md §6.4`). `--to <N>`은 플러그인 `SCHEMA_VERSION` ≥ N > 이슈 DB 버전일 때만(아니면 종료 코드 2), 현재 브랜치는 **정확히** `migrate/schema-v<N>`(`config.py check`의 예외는 `migrate/schema-v<숫자>` 패턴 전체). `--dry-run`은 브랜치·깨끗함을 보지 않고 아무것도 쓰지 않는다. 마이그레이션은 메모리에서 모두 적용한 뒤 한 번에 쓰므로 실패하면 트리가 그대로다. `schema_version`은 db_migrate가 올리고, `generator_version`은 `ci_mode`가 `actions-build`가 아니면 플러그인 값으로 함께 맞춘다(`db_build --write`가 두 값이 같아야 돌기 때문). 마이그레이션 모듈 계약: `FROM_VERSION`·`TO_VERSION`·`migrate(tree)`·(선택)`upgrade_plan(plan)`. `upgrade-plan`은 계획의 `schema_version`을 `--db`의 버전까지 올리고(`--write`면 원본을 `<plan>.v<옛 버전>.bak`으로 남기고 덮어씀), 그 사이 `upgrade_plan()`이 없는 마이그레이션이 있으면 종료 코드 2 |
| `guard.py` | — | stdin: hook 입력 JSON → 권한 결정 JSON (`08-safety.md §9`) |
| `jira_bridge.py` | — | stdin: PostToolUse hook 입력 JSON. 도구가 config `jira.tools.get_issue`·`get_comments`일 때만 `{hookSpecificOutput: {hookEventName: PostToolUse, updatedToolOutput}}`: 원문은 `<work_dir>/<KEY>/jira_raw.json`(키는 `jira_key_regex` 검사, `get_comments`는 `comments`에 합침), 모델에는 마스킹 요약(요약·설명 앞부분·코멘트 마지막 3개, 각 200자). 실패하면 원문 대신 오류 문구(fail closed). 다른 도구는 출력 없음. 항상 종료 코드 0 (`08-safety.md §9` 9번) |
| `triage.py` | `run` / `explore` / `release` | `run --offline-db <db>`는 `--out <dir>`·`--logs`와 `--jira-meta` 또는 `--jira-file`을 함께 준다. analyze Step 0~4와 Step 5 resolve를 위 스크립트의 `main()`으로 같은 프로세스에서 수행한다(각 스크립트 계약 그대로). 완료: `JOB/analysis.json`(≤ 4KB, stdout도 같음. 키 구조는 `contracts-cli.md §triage.py run → analysis.json 키`) + `JOB/report.md`(Step 6 초안, LLM 몫은 `TODO(LLM)`, 근거 줄 끝에 로그 줄 위치 `(f<입력 순번>:L<줄>)`; `analysis.json` 근거 키는 그대로 `{ts, tag, msg, event}`) + `JOB/trace.jsonl` + (후보 없음 또는 1위 C=0이고 `explore.when`이 `never`가 아닐 때) `JOB/explore-input.json`(`{around, failed_step(마스킹)|null, limit, anchor{source, step, start, fail}|null}`, 마스킹된 값만; `run`이 쓰고, 캐시 적중이어도 다시 쓴다). `run`은 이전 `timeline.md`·`explore-input.json`을 먼저 지운다. **`explore <KEY> [--out <dir>]`**: 사용자가 탐색 분석에 동의한 뒤(또는 `--explore`·`explore.when: always`) `JOB/explore-input.json`과 `JOB/events.json`으로 `JOB/timeline.md`(마스킹된 요약 타임라인, `explore.timeline_max_lines` 줄 상한, `07-workflow.md §Step 5-2`)를 만들고 `report.md`의 탐색 분석 줄을 `- 탐색 분석 (추정, timeline.md n/m줄): TODO(LLM) …`로 바꾼다. `JOB`은 `--out`(오프라인 분석 디렉토리) 또는 `<work_dir>/<KEY>`, 출력 `{timeline, lines, total}`, 종료 코드 0 = 완료, 1 = 해당 없음(`explore-input.json` 없음), 2 = 사용 오류(키 형식·작업 디렉토리 없음·`events.json` 없음·입력 손상). lock·trace·상태 파일은 건드리지 않는다. 같은 입력이면 같은 바이트다. `explore`는 판정에 쓰지 않는다. **`must_show`**(있을 때만): `report.md`에서 `- ` 뒤 줄 본문 그대로(마스킹됨)이며 우선순위 순이다 — 분석 전용 안내 > 읽기 전용 안내 > 1위가 바뀐 재분석 > 실패 스텝 > 장비 시각 미사용 > `로그 범위` 줄(후보 없음·1위 C=0·로그 범위 일부/밖·시계 이상일 때만) > 분석 범위 밖 오류 이벤트 > 파서 규칙에 없는 태그(최대 6개 수집). 4KB 압축 시 `read_only_hint`는 must_show에 읽기 전용 줄이 있으면 먼저 뺀다(`읽기 전용:`), 마지막 단계로 줄당 160자로 줄이고 앞 4개만 남긴다(`truncated`의 의미는 그대로). 스킬은 이 줄들을 사용자에게 그대로 보여 준다. **`step_anchor`**(실패 스텝 앵커·실패 스텝·시계 정렬·스텝 순서 시도가 있을 때만 키가 있다): `{outside_errors?(앵커가 있고 Jira 발생 시각이 분석 범위 밖·로그 범위 안일 때 그 시각 근처의 범위 밖 오류 이벤트 수, 0이면 키 없음, 근거·점수에 쓰지 않음; trace 단계 `3-parse-outside`), source: log_marker\|steps_file\|step_order\|jira\|symptom_scan, step(≤80, 4KB 압축 시 40), step_from: "marker"(마커의 스텝을 쓴 경우만), span: [시작\|null, 실패], jira_gap_min, focus[≤3 유형 ID], clock{mode: manual\|none, offset_sec?(manual), reason?(none, "시계 차 모름"; 4KB 압축 시 먼저 뺌)}, order{matched, observable, missed, last{step(≤40), ts}(step_order일 때, 4KB 압축 시 가장 먼저 뺌), reason?(앵커를 못 정해 `jira`로 돌아갈 때)}}`. 앵커 우선순위는 `anchor=off` > `log_marker` > `steps_file`(**수동 시계 차 `--clock-offset`(또는 `failed_step.clock_offset`)이 있을 때만**; 단말 = 장비 + 값, 하루 이내, 형식 오류는 종료 코드 2) > `step_order`(스텝 순서 정렬, 시계 불필요) > `jira` > `symptom_scan`(`07-workflow.md §Step 3`). `clock`은 steps-file 시각을 시도했을 때만 있고 앵커가 `jira`로 돌아가도 남는다. 앵커(`log_marker`·`steps_file`·`step_order`)가 있으면 분석 범위는 `parse --between`, 근접 중심은 스텝 실패 시각이고(`JOB/match_meta.json`) `request_hash`에 [출처, 범위]가 더해진다. 마커 스캔(`parse_logcat markers`, trace 단계 `3-markers`)은 `failed_step.marker_patterns`가 있거나 `--steps-file`이 있을 때만 돌고, `--steps-file`이 있고 스냅샷의 `step_events`가 비어 있지 않으면 `--step-events`가 붙는다(`07-workflow.md §Step 3`). `--steps-file`은 txt/csv/tsv·html·zip(안의 파일 하나를 메모리에서만 읽음)이다. 실패 스텝 원문 플래그는 같은 프로세스에서 마스킹하고 하위 스크립트 인자·`trace.jsonl`·`triage-state.json`에 남기지 않으며, 있을 때만 `jira.json`·`jira_meta.json`·`report.md` 머리·`timeline.md` 머리·후보 없음 `db_search` 첫 질의(구절 전체 → 토큰 → 요약 토큰)·`request_hash`에 반영된다. 사용자 결정 지점: `{status: needs_input, needs_input: {kind, question, options[], answer}}`(kind: `lock`·`plan`·`jira`·`year`·`reanalyze`·`open_pr`·`logs`·`code`·`code_confirm`·`time`·`window`; **`--answer anchor=off`**만 질문 없이 쓰는 입력이다 — 실패 스텝 앵커를 끄고 Jira 발생 시각 기준으로 분석) → 같은 명령에 `--answer kind=값`을 붙여 재실행(답·진행은 `JOB/triage-state.json`, 같은 lock owner면 멱등). 사용자 중단은 `status: stopped`(lock 해제). 종료 코드 0 = ok·needs_input·stopped, 1 = Jira 키 형식 불일치, 2 = 사용·환경 오류(하위 스크립트 메시지 그대로, 잡은 lock은 풀고 끝남. `--analysis-only`를 `--dry-run`·`--offline-db`와 함께 준 경우, `--more-logs`를 `--logs`(argparse 상호 배제)·`--offline-db`와 함께 준 경우, `--more-logs`인데 이전 분석 로그가 없는 경우(`이전 분석 로그가 없다 — --logs로 시작한다`)도 2). lock은 ok·needs_input에서 유지되며 `release <KEY>`(저장된 owner 사용) 또는 `db_pr discard`로 푼다. **`--analysis-only`**(RF-7, `07-workflow.md §분석 전용`)는 이슈 DB에 기록하지 않는 분석 전용 실행이다: `mode: analysis-only`(`read_only_reasons`·`open_prs` 키 없음, `plan`은 `{exists, source, pr_number}`만), 호환성 검사는 `--for dry-run`, `--jira-file`을 `--dry-run` 없이 받고, cleanup 점검·기존 계획 질문과 pending 피드백 삭제·열린 PR 확인·재분석 질문을 건너뛰며(`existing`은 알리기만), lock은 잡되(스냅샷을 옮기므로) needs_input에서는 유지하고 **ok로 끝나면 풀어** `lock_released: true`(`lock_owner` 없음)를 낸다 — 풀린 lock 때문에 이어지는 `db_pr stage`는 거부된다(`db_pr` 변경 없음). 푸는 쪽 `lock release`가 `steps-pasted.txt`를 지운다. `mode`는 입력 해시에 없어 이어서 보통 analyze를 하면 core를 재사용한다. `--offline-db`는 lock·스냅샷·config 없이 주어진 DB로 Step 3~4만(오프라인 평가, `tools/offline_eval.py`). **입력 재사용(RF-7, `07-workflow.md §입력 재사용`)**: `request_hash` = 입력 해시(부분별 `parts` {logs, jira, db, config, plugin, args} 각 16자리의 해시, 파싱 전에 계산), `run` = 결과(core)를 계산한 실행 번호, `reuse` = `{hit: true, run}`(재사용) \| `{hit: false, prev_run, changed[부분] \| reason: refresh\|cache-missing, added_logs[≤5], prev_top, top_changed}`(이전 실행이 있을 때 다시 계산) — 첫 실행·`--offline-db`에는 `reuse`가 없고(오프라인 출력은 그대로), 4KB 압축 시 `added_logs`·`prev_top` 순으로 뺀다. 적중하면 `parse_logcat`·`match_signatures`·`db_search`·`code_roots resolve`를 부르지 않고(trace `{step: reuse, hit}`) `JOB/analysis-cache.json`(`{format(2), request_hash, run, parts, core, files{events, match: [크기, mtime_ns]}}`, 마스킹된 값만, ok로 계산한 실행만 쓴다)의 core로 `report.md`·`analysis.json`을 다시 쓴다. 적중 조건: `--refresh` 아님·`triage-state.json`의 `job.cache.request_hash`와 같음·`events.json`·`match.json`이 기록한 크기·mtime 그대로(타임라인은 캐시 파일이 아니다)·resolve한 코드 경로가 있음. 잔여 worktree·도구 브랜치(`cleanup`)는 묻지도 지우지도 않는다: `db_pr cleanup --dry-run`만 하고 대상이 있으면 상태 `cleanup_targets=<n>`(`cleanup_done`과 함께)과 `notes`로 알린다(정리는 `sync`, `--answer cleanup=…`은 무시). 코드 경로 자동 선택 성공은 상태 `code_auto=<프로필>`로 남는다(`answers` 아님, 무효면 기록하지 않음). `triage-state.json`은 스키마 2(`schema`, `job{logs[{path, name, sha, size}], runs[≤10 {n, at, request_hash, mode, logs[이름], top, reused}], cache{request_hash, parts, run}}`)이고 `job`은 lock owner가 바뀌어도(세션 변경) 남는다(스키마 표시가 없는 파일은 `job` 없이 첫 실행으로 본다). `--refresh`는 스냅샷을 다시 만들고 재사용도 끈다(`reason: refresh`). **`--more-logs <경로…>`**(RF-7, `07-workflow.md §추가 로그 재분석`)는 `job.logs`(이전 분석의 로그) **뒤에** 로그를 붙여 다시 분석한다(기존 `f<순번>` 유지): 이미 있는 경로는 조용히, sha256이 같은 다른 경로는 경고(`more-logs-duplicate: …`)하고 건너뛰며, 합친 목록을 `job.logs`·세션 `logs` 키에 남긴다(`--logs`는 목록을 통째로 바꾼다). 로그 부분 해시가 바뀌어 Step 3~5를 합친 로그 전체로 다시 계산하고(`reuse.changed: [logs]`·`added_logs`), 새로 계산한 결과가 이전 실행과 `request_hash`가 다르면 덮어쓰기 전에 이전 `analysis.json`·`report.md`를 `JOB/runs/<n>/`(n = 이전 실행 번호, 최근 5개만 유지, `events.json`·`match.json` 제외)에 보관한다 |

`db_verify.py` 세부
- `rules --plan <p>`: 계획이 무엇을 바꾸는지로 검사 대상을 정한다. `--draft <dir>`가 있으면 `<dir>`에 origin/<base> 기준 분리(detached) worktree를 만들고 계획을 적용해서 검사한 뒤 worktree를 지운다 (Step 7 초안 검증). `--draft`가 없으면 `--db`에 계획이 이미 적용돼 있다고 보고 검사한다 (Step 8-4). R6 표본은 계획의 `extra_samples`와 `--extra`를 합친다.
- `--draft`를 쓰는 호출(`rules`, `resolution`, `fix`)은 세션 lock이 그 작업 키 것인지 확인한다. 작업 키는 `<dir>`의 상위 디렉토리 이름이다 (`<work_dir>/<작업 키>/draft`).
- `rules --changed <ref>` / `--staged`: 변경분으로 검사 대상을 정한다 (`validate`, pre-commit, CI).
- R1·R2 대상 = 변경된 원인 시그니처 + **변경된 extractor/태그/RIL 항목을 참조하는 시그니처**(의존 그래프)의 소속 원인 fixture. 대상 원인에 양성 fixture가 하나도 없으면 R1·R2는 `skipped`(`reason: fixture 없음`)이고 결과에 `review_required: true`를 붙인다. `skipped`는 통과가 아니다 (§상태 값).
- 새로 넣거나 바꾼 `symptom_signatures`(와 그것이 참조하는 규칙)는 R1(추출)·R3(모든 음성 fixture에서 S=0) 대상이다 (`05-verification.md §5.12 (1)`).
- `fix --plan <p> --draft <dir>`: 계획(예: `update-signature`)을 draft worktree에 적용한 트리로 판정한다 (`05-verification.md §5.12 (2)`).
- `resolution --plan <p> --draft <dir>`: 계획을 draft worktree에 적용한 트리로 판정한다. 스냅샷에 아직 없는 새 원인(`record`의 `new-cause`)의 해결책을 판정할 때 쓴다. 이때 `--cause`에는 계획의 `temp_id`를 줄 수 있고, draft에 적용하며 할당된 실제 ID로 판정한다 (`05-verification.md §5.12 (1)` 수동 기록 검증).
- `resolution`, `fix`는 항상 회귀·검증 모드(`--regress`, `04-parser-matching.md §5.11 (4)`)로 판정한다.
- **기준 트리와 대상 계산**: `rules`는 기준 트리와 대상 트리를 **의미 단위로** 비교해 대상을 정한다(`common/rulediff.py`: 시그니처는 소유자·종류·id별 내용, parser-rules는 키별 기능 필드). 기준 트리는 `--plan`이면 대상 트리의 `HEAD`(draft·작업 worktree 모두 기준 SHA에 있다), `--changed <ref>`면 merge-base, `--staged`면 `HEAD`다. 그래서 `--plan`과 `--changed`/`--staged`가 같은 규칙으로 대상을 고른다. 새 원인은 시그니처가 없어도 대상이다(pending이면 `시그니처 없음(pending)`). 의존 그래프는 보수적이다: tags 항목 변경은 그 태그를 쓰는 extractor의 이벤트와 패턴에 태그 이름이 든 `must_match`(`tag_regex` 항목이면 같은 카테고리 소유자의 `must_match` 전부), ril 항목 변경은 패턴에 그 이름이 든 `must_match`와 `ril_error`·`ril_timeout`·`ril_no_response`를 쓰는 `must_event` 전부.
- **R1 파서 검사**: 대상 시그니처의 조건(`must_match`, `must_event`+`fields`)마다 소유자(증상 시그니처면 그 유형)의 양성·`recurrence`·`extra` fixture 중 하나에서 추출되면 통과. 흔적 검사는 `05-verification.md §5.12 (1)` R1 그대로(scenario는 그 원인의 양성 fixture에서 충족, scenario·recovery 모두 그 카테고리 음성 fixture 전부에서 충족되면 실패).
- **R3 원인 대상 fixture**: 같은 카테고리의 음성 fixture, 같은 카테고리의 다른 원인 양성·`recurrence`·`extra` fixture(다른 유형 포함), 대상 원인의 `fixed`·`resolved` fixture. 검사할 fixture가 하나도 없으면 `skipped: 음성 fixture 없음`(`review_required`).
- **항목 모으기**: 한 항목에 대상이 여럿이면 `fail` > 리뷰 필요한 `skipped` > `pass` > 그 밖의 `skipped` 순으로 항목 상태를 정하고, 대상별 결과를 `checks[]`에 둔다.
- **R6**: 표본은 계획 `extra_samples`(`expect`) + `--extra`(`match`) + `--extra-normal`(`nomatch`). `match`는 대상 원인 중 하나가 C=1(원인 대상이 없으면 대상 유형 S=1), `nomatch`는 모든 active 유형 S=0. R6 `fail`은 사용자가 진행을 고를 수 있으므로 **종료 코드에 넣지 않는다**(`blocking: false`).
- **`resolution`·`fix` 출력**: `{judgement, reason, cause, type, requested, C, S, satisfied_traces[{signature, kind, ts}], errors[], suggested_ops[]}`. `fix`는 더해서 `trace`(판정에 쓴 흔적), `other_candidates`(partial), `build_check{status: after\|undetermined\|not-given}`, `fix_status`, `user_confirmation_required`(흔적 시그니처가 없는 비코드 수정 유형). `suggested_ops`는 판정에 맞는 계획 op 초안이다(fixture 경로·아이디는 스킬이 채운다). 판정은 데이터이므로 종료 코드는 0이다.
- **`fix` 중단(종료 코드 2)**: `fix.status`가 `fix-submitted`·`fixed`가 아님, pending 원인, 코드·설정 수정 유형인데 scenario·recovery 시그니처가 모두 없음(`--plan --draft`면 계획 적용 후 트리 기준, `fixed` 재검증이면 안내에 `회귀라면 analyze Step 7로 open 되돌림을 안내한다`를 더한다), `fixed_in`에 빌드 있는 항목 없음, `--build`가 비교 가능한 모든 `fixed_in` 빌드보다 이전. 비교 불가면 `build_check: undetermined`로 판정을 이어가고 스킬이 사용자에게 묻는다. `failed`(원인 시그니처 충족)는 흔적 검사보다 먼저 본다(재발 자체가 시나리오 수행 근거다).
- **`--plan --draft`의 판정**: 같은 draft에서 `rules`도 돌려 출력 `rules`에 넣는다. R1 흔적 검사가 실패하면 판정을 쓰지 않는다(`withheld: true`, `withheld_judgement`, 판정 `unknown`).

`db_review.py` 세부 (`06-collaboration.md §6.6`)
- **기준일**: 실행일(`--as-of`로 바꿀 수 있다). 리뷰는 "지금 방치된 것"을 찾는 로컬 보고서이고 생성 파일이 아니므로 결정성 규칙(`03-issue-db.md §5.2`, STATS의 "가장 최근 Jira `date`")을 따르지 않는다. 발생일·급증·"fixture 없는 원인"(pending 원인 제외)·"fixed 전환 불가" 판정은 STATS와 같은 코드(`common/quality.py`)다.
- **방치 기간**(해결책 미검증, 수정 검증 대기, Jira 없는 원인의 나이): 이슈 DB 파일에 상태 전환 날짜가 없으므로 **git 이력**으로 구한다. 그 원인의 `type.md`를 바꾼 커밋을 최신부터 거슬러 보며 조건이 계속 참인 가장 오래된 커밋의 커미터 날짜가 시작일이다(해결책 미검증은 `resolution` 문구가 같고 `unverified`인 구간). `--db`가 git 최상위가 아니거나 이력이 없으면(`no-history`), 커밋 전 워킹 트리 상태면(`uncommitted`) 그 원인은 `undetermined[]`("기간 확인 불가")로 따로 낸다. pending 원인은 `verify-resolution`이 거부되므로 "해결책 미검증 방치"에서 뺀다.
- **오래된 원인 미확정**은 Jira 기록 `date`(기록한 날) 기준, **오래 안 쓰인 원인**은 마지막 발생일(`occurred_on`, 없으면 `date`)이 `stale_months` 전보다 이전인 원인. Jira가 없는 원인은 git 이력의 추가 시점으로 본다.
- **중복 후보**: active 유형의 양성·`recurrence`·`extra` fixture를 회귀·검증 모드로 매칭해서 다른 유형의 증상 시그니처도 S=1인 쌍(두 유형의 원인이 `related`로 이어졌거나 그 fixture의 `also_allowed`에 상대 유형 원인이 있으면 이미 알려진 연관이라 뺀다), 또는 같은 카테고리에서 제목 유사도(`db_add similar`와 같은 계산) 0.8 이상인 쌍.
- **수정 필요 누적**: `fix.status: open`이고 Jira가 1건 이상인 원인을 Jira 건수 순으로 낸다(따로 문턱이 없다).
- **`also_allowed` 누적**: 한 fixture의 `also_allowed` 3개 이상, 또는 한 원인이 다른 유형 fixture 5개 이상에서 허용.
- 카테고리를 주면 그 카테고리 엔티티(원인·유형·Jira·시그니처 소유자)만 낸다. 쌍 항목(중복 후보, `also_allowed`)은 한쪽이라도 그 카테고리면 낸다. `owners`는 CODEOWNERS의 `/<category>/` 규칙(마지막 규칙이 이긴다)이다.

`db_pr.py` 세부 (오케스트레이션 소유자, `01-architecture.md §3.1`)
- **도구 브랜치**: `db_pr`는 로컬에 도구 전용 브랜치 `tt/<br>`만 만든다. 사용자 clone의 로컬 브랜치 `<br>`는 만들지도, 덮어쓰지도, 지우지도 않는다. 원격 브랜치 이름은 `<br>`다 (§브랜치).
- **세션 lock** (v1은 사용자별로 한 번에 한 작업): `<work_dir>/session.lock` = `{job, command, started_at, updated_at}`.
  - 스냅샷을 옮기거나 worktree를 만드는 흐름(analyze, record, `sync`(작업 키 `sync`), `sync-pr`, `verify-fix`, `validate --cause`, `fix-submitted`, setup 6번(작업 키 `setup`), review/move 계획 PR)은 시작할 때 `lock acquire <작업 키>`로 잡는다. 다른 작업 키의 lock이 있으면 종료 코드 2와 보유자 정보를 낸다. 같은 작업 키의 lock이면: `updated_at`이 **10분 이내**면 다른 세션이 같은 작업을 진행 중일 수 있으므로 종료 코드 2와 보유자 정보를 내고, 사용자가 확인하면 스킬이 `acquire <작업 키> --take-over`로 이어받는다. 10분이 넘었으면 그대로 이어받는다(같은 작업을 하던 이전 세션이 비정상 종료한 경우).
  - `snapshot`, `stage`, `summary`, `publish`, `discard`, `db_verify ... --draft`는 lock이 그 작업 키 것인지 확인하고 `updated_at`을 갱신한다. 아니면 종료 코드 2. 이때 만료 여부는 보지 않는다(만료는 다른 작업이 가져갈 수 있다는 뜻일 뿐, 아직 같은 작업 키가 남아 있으면 그대로 이어간다). (`<wt>`·`<draft>`의 작업 키는 상위 디렉토리 이름이다.)
  - 4시간 넘게 갱신되지 않은 lock은 만료로 보고 `acquire`가 가져온다. 만료 전이라도 사용자가 "그 세션은 끝났다"고 확인하면 스킬이 `release <작업 키> --force`로 푼다. 스크립트는 호출마다 끝나는 프로세스이므로 프로세스 생존 여부로 판단하지 않는다.
  - **해제**: 작업의 모든 종료 경로에서 lock을 푼다. `discard`는 자동으로 푼다. `discard` 없이 끝나는 경로(analyze 읽기 전용 모드·계획 저장 후 종료, `validate --cause`의 failed/unknown, `verify-fix`의 unknown, 사용자가 중간에 그만둠, `sync`·setup 완료)에서는 스킬이 `lock release <작업 키>`를 호출한다. `--force` 없는 `lock release`는 그 작업 디렉토리의 `steps-pasted.txt`도 지운다(lock이 이미 없어도). `cleanup`은 lock 보유 작업이 아닌 작업의 남은 `steps-pasted.txt`를 지운다 (`08-safety.md §8.1`).
  - 읽기 전용 커맨드(`search`, `review`, `preview`, 인자 없는 `validate`)는 lock을 잡지 않는다. 스냅샷을 옮기지 않기 때문이다.
- **작업 상태 파일**: `<work_dir>/<작업 키>/`에 `plan.json`(§작업 계획), `state.json` = `{base_sha, branch, approved_hash, commit_message, staged_at}`(`stage`가 `base_sha`·`branch`를, `summary`가 `approved_hash`·`commit_message`를 쓰고 `publish`가 읽는다), `included_pending/`(이미 PR에 올린 pending 피드백 사본)을 둔다. `wt/`, `draft/`는 worktree다.
- `snapshot --job <작업 키>`: `git -C <issue_db.path> fetch origin` → lock 확인 → 분석 전용 읽기 스냅샷 `<work_dir>/_snapshot`을 만들거나(`git worktree add --detach <work_dir>/_snapshot origin/<base>`) 옮긴다(`git checkout --detach origin/<base>`) → 사용자 clone의 현재 브랜치가 `<base>`이고 깨끗할 때만 `git -C <issue_db.path> pull --ff-only`(아니면 건너뛰고 사유 반환). **사용자 clone에서 checkout은 하지 않는다.** 스냅샷은 읽기 전용이고, 파일을 쓰는 것은 `.cache/`(`db_build --cache-only`)뿐이다.
- `cleanup`: `git worktree prune` 후 **lock 보유 작업 키가 아닌** `<work_dir>/*/wt`·`<work_dir>/*/draft`와 그 `state.json`, worktree가 없는 도구 브랜치 `tt/*`를 대상으로 한다 (lock이 없으면 전부 대상). 스킬은 자기 작업의 lock을 잡은 뒤에 부른다. `tt/` 밖의 브랜치는 대상이 아니다. `--dry-run`은 목록만 내고, `--yes`는 지운다. 스킬은 `--dry-run` 결과를 보여주고 사용자 확인을 받은 뒤 `--yes`로 호출한다.
- `preflight`: `git fetch origin`, 도구 브랜치 `tt/<br>` 존재, 사용자 로컬 `<br>` 존재와 원격보다 앞선 커밋 여부, 원격 `<br>` SHA, `gh pr list --search "<원인 ID 또는 JIRA-KEY>" --state open` 결과, origin/<base>에 같은 Jira 파일이 있는지 반환한다. 아무것도 바꾸지 않는다. `--branch`는 필수다.
- `stage`:
  1. lock 확인. `tt/<br>`가 `<wt>`가 아닌 다른 worktree에 checkout돼 있으면 종료 코드 2.
  2. 기준 SHA(= 이때의 `origin/<base>` SHA)와 `<br>`를 `state.json`에 쓴다.
  3. **drift 검사**: 계획의 `base_sha`가 기준 SHA와 다르면 `db_add drift --onto <기준 SHA>`를 돌린다. drift가 있으면 적용하지 않고 목록과 함께 종료 코드 1을 낸다. drift가 계산한 `ids_at_base`는 stage 결과와 `state.json`에 싣고, drift를 건너뛴 재`stage`(같은 기준 SHA·같은 `base_sha`)는 이전 `state.json`의 값을 이어받는다. 스킬이 사용자 결정을 계획에 반영하고 `base_sha`를 기준 SHA로 바꾼 뒤 다시 `stage`한다 (§작업 계획 drift).
  4. `git worktree add --no-track -B tt/<br> <wt> <기준 SHA>`. 이미 있는 `<wt>`면 **재적용**: 그 안에서 `git checkout -f -B tt/<br> <기준 SHA>` → `git reset --hard <기준 SHA>` → `git clean -fd`. 커밋 전이라 HEAD가 이미 기준 SHA여도 추적 파일의 이전 적용분이 남지 않게 하기 위해서다.
  5. `config.py check --db <wt>`로 기준 트리의 쓰기 가능 여부를 확인한다: `--dry-run`이면 `--for dry-run`(gh 인증 없이), 그 밖에는 `--for write`. 불가면 종료 코드 2.
  6. `db_add apply`. 계획 `source`가 `analyze`일 때만 pending 피드백을 포함한다: `<work_dir>/<작업 키>/included_pending/`(이미 이 PR에 올린 것)과 지금 `~/.telephony-triage/pending-feedback/`에 있는 파일.
  7. (`ci_mode`가 `actions-build`가 아니면) `db_build --write` → `db_lint --changed origin/<base>` → `mask_pii --check --changed origin/<base>` → `db_add check-ids`(기준 SHA에 그사이 들어온 ID와의 충돌, `07-workflow.md §Step 8`) → `db_regress --all` → `db_verify rules --plan`(`--verbose`로 불러 `stage.json`에 전체를 남긴다).
  - **출력**: stdout은 기본 요약이다 — 통과(code 0) 단계는 `{code}`(lint 건수·mask `checked`·regress `summary`·verify 접힌 결과표), `apply`는 `{ids, changed, fixtures, feedback, pending_included, rejected}`, `config_check`는 `{for, writable, push_allowed, reasons}`이고 `detail`(= `stage.json` 경로)·`folded` 한 줄을 붙인다. 비0 단계·apply 실패·drift는 전체다. 전체는 `stage.json`(항상 전체)이나 `stage --verbose`로 본다. 종료 코드·`result` 값은 같다.
  - 모든 호출에 `--db <wt>`를 명시한다. `<br>`가 사용자 clone에 checkout돼 있어도 영향이 없다.
- `summary`: 확인 화면에 필요한 값(계획 `source`와 표시 라벨 — `record`면 "수동 기록", `jira.origin: file`이면 "Jira 메타데이터: 오프라인 파일" —, 변경 파일, ID·fixture 번호 할당, README 미리보기, 주요 diff, 자동 검사, 검증 결과표(실행/건너뜀과 사유), 승인 필요 항목, 리뷰어, 커밋 메시지)과 `approved_hash`를 낸다. `approved_hash`는 워킹 트리 전체(`.gitignore` 적용)를 임시 index로 올려서 구한 트리 해시다: `GIT_INDEX_FILE=<임시> git add -A && GIT_INDEX_FILE=<임시> git write-tree`. `approved_hash`와 커밋 메시지를 `state.json`에 쓴다. `--format markdown`은 같은 값을 `write-flow.md §4` 절 순서의 마크다운으로 stdout에 낸다(상태 파일은 같고, 규칙이 정해지지 않은 경우는 "(규칙 없음 — 원값: …)"으로 보인다).
- `publish --commit`: HEAD가 `state.json`의 `base_sha`(아직 커밋 없음)일 때 먼저 커밋한다 — (1) 현재 워킹 트리의 승인 해시가 `--approved`·`state.json`의 `approved_hash`와 같은지(다르면 종료 코드 1, `problems`에 "승인 뒤 파일이 바뀌었다", 커밋 안 함), (2) 유효 `core.hooksPath`가 정확히 `.githooks`인지(아니면 UsageError 종료 코드 2, guard 규칙 5와 같다), (3) `git add -A`, (4) guard 규칙 3·4와 같은 검사(`common/checks.py`의 `PROFILES["guard"]`를 staged 범위로 실행, 실패면 종료 코드 1과 guard와 같은 문구 — `checks.guard_deny_messages`를 공유하고 안내 꼬리만 "계획을 고쳐 3번(stage --then-summary)부터"; config가 YAML 오류·비매핑이면 UsageError 2), (5) `state.json`의 `commit_message`를 작업 디렉토리(worktree 밖)의 임시 파일에 써서 `git commit -F <파일>`(셸을 거치지 않는다, `--no-verify` 없음 — **git pre-commit hook이 돈다**), 임시 파일 삭제. pre-commit이 실패하면 종료 코드 1, `commit: {committed: false}`, `problems`에 hook 출력 끝 800자, push 안 함. 이미 커밋이 있으면 커밋을 건너뛰고 `commit: {skipped: "이미 커밋됨"}`로 아래 검사를 이어간다(멱등: lease 거부 뒤 재시도). `--commit`이 없으면 아래 검사만 한다(기존 동작).
- `publish --and-discard`: publish 종료 코드 0일 때만 `discard`를 이어 부르고 `discard` 결과를 출력에 싣는다. publish가 stdout JSON을 내고 끝난 1·2는 같은 종료 코드로 `discard: {discarded: false, skipped}`(정리하지 않는다, worktree·lock 보존): `published: false`면 `skipped: "publish 실패 — worktree·lock 보존"`, push는 됐고 PR 생성만 실패한 2(`published: true`, `gh_error`)면 `skipped: "PR 생성 실패 — worktree·lock 보존"`과 `next`(PR을 수동 처리하거나 publish 재시도를 정한 뒤 `db_pr discard <wt>`). publish 안의 UsageError로 끝나는 2(hooksPath 불일치, 승인 정보 없음, git 실패)는 stderr만 내고 stdout JSON이 없으므로 `discard` 키가 없고 정리하지 않는다(작업물 보존). publish 0·discard 실패는 종료 코드 2, `published: true`·`pr.url`은 그대로이고 `discard: {discarded: false, error, next}`(PR은 만들어졌다 — publish를 다시 하지 말고 `discard`만 다시 한다).
- `publish`: `state.json`과 비교해서 다음을 모두 확인한다 (하나라도 다르면 종료 코드 1, 확인을 다시 받는다): `HEAD^{tree}`가 `--approved`와 같고 `state.json`의 `approved_hash`와 같다, `HEAD^`가 `state.json`의 `base_sha`이고 `HEAD^2`가 없다(기준 위의 커밋 1개, 머지 커밋 아님), 커밋 메시지가 `state.json`의 메시지와 같다, `<br>`가 `state.json`의 `branch`이고 base 브랜치가 아니다. 그 뒤 환경변수 `TT_PUBLISH_TOKEN=<approved_hash>`를 붙여 `git push --force-with-lease=refs/heads/<br>:<sha> origin HEAD:refs/heads/<br>` (이슈 DB의 `.githooks/pre-push`가 토큰을 `state.json`의 `approved_hash`와 비교하고, push하는 커밋 트리·대상 브랜치도 그 `state.json`과 대조하며, base 브랜치 대상 push를 거부한다, `08-safety.md §9`. `--lease new`면 `--force-with-lease=refs/heads/<br>:`로 원격에 브랜치가 없어야 함) → `GH_HOST=<ghe_host> gh pr create`(또는 이미 PR이 있으면 `gh pr edit`) → 계획의 `pr`(`number`, `branch`, `head_sha`)과 `base_sha`(= `state.json`의 `base_sha`) 기록 → 포함된 pending 피드백 원본을 `included_pending/`로 옮기고 계획 `included_pending`에 PR 번호와 함께 기록.
- `discard`: `git worktree remove --force <wt>`, 도구 브랜치 `tt/<br>` 삭제, `state.json`·붙여넣은 스텝 원문 `steps-pasted.txt` 삭제, **lock 해제**. 사용자 로컬 `<br>`와 원격 브랜치, `plan.json`은 건드리지 않는다.
- 커밋은 `publish --commit`이 한다: 승인 해시·`core.hooksPath`·guard 프로필 검사(규칙 3·4)·pre-commit을 거친다. 스킬은 직접 `git add`·`git commit`을 하지 않는다 (`07-workflow.md §Step 8-6`). Claude hook(`guard.py`)은 `publish` 토큰이 있으면 옵션과 무관하게 `ask`로 확인을 강제한다(규칙 7).

---

## 종료 코드

| 코드 | 의미 | 처리 |
|---|---|---|
| `0` | 성공 (경고 포함) | 계속 |
| `1` | 검사 실패 (drift 포함: 계획 대상이 main에서 바뀌어 사용자 결정이 필요) | 차단. 원인을 보여준다 |
| `2` | 사용 오류·환경 오류 (인자, 경로, config, git/gh 실패, 버전 불일치로 쓰기 거부, 마스킹 안 된 입력, 다른 작업의 세션 lock) | 중단. 설정 방법을 안내한다 |
| `3` | **승인 필요** (`needs-approval`). 검사는 통과했지만 사람 승인이 필요한 변화가 있음 (예: R5에서 기존 이벤트 변경) | pre-commit: 경고 후 통과. 확인 화면과 PR 본문에 "승인 필요"로 표시하고, 메인테이너 승인을 리뷰 조건으로 둔다 |

- `3`을 낼 수 있는 스크립트: `db_verify.py rules`, `db_pr.py stage`(하위 결과 집계; `--then-summary`면 종료 3에서도 확인 화면이 나온 정상 경로다).
- `db_pr.py publish --and-discard`: publish 0이고 `discard`가 실패하면 `2`(PR은 만들어졌다 — `discard`만 다시 한다).
- 여러 검사를 묶는 스크립트(`db_pr stage`, `db_precommit`)는 `1`이 하나라도 있으면 `1`, 없고 `2`가 있으면 `2`(`db_precommit`; `stage`는 `2`에서 중단), 없고 `3`이면 `3`(`db_precommit`은 경고 출력 후 `0`), 모두 통과면 `0`. 집계 구현은 `common/checks.py::aggregate`.
- 개발·테스트용으로 `TT_FORCE_VERIFY_EXIT=3` 환경변수가 있으면 `db_verify rules`는 판정 뒤 종료 코드 `3`을 낸다 (Phase 7 뼈대에서 종료 코드 `3` 경로를 확인하기 위한 것).

---

## 작업 계획

위치: `<work_dir>/<작업 키>/plan.json` (로컬 전용, 커밋하지 않음). 스키마: 이슈 DB `schema/plan.schema.json`. 작업 키는 analyze·record면 `<JIRA-KEY>`, 그 밖에는 브랜치 이름에서 `/`를 `-`로 바꾼 것(예: `verify-fix-<원인 ID>-<build>`). `sync-pr`는 원래 계획이 있는 디렉토리 이름을 작업 키로 쓴다.

```json
{
  "source": "analyze",
  "schema_version": 1,
  "started_at": "2026-09-27T18:02+09:00",
  "base_sha": "<계획의 결정을 내린 기준 트리 SHA>",
  "jira": {"key": "ABC-12345", "origin": "mcp", "model": "...", "sw": "...", "android_version": "16",
           "carrier": "...", "date": "2026-09-27", "occurred_on": "2026-09-26", "failed_step": "3 | Enable data", "note": "로밍 SIM 테스트 중 발생"},
  "operations": [
    {"op": "append", "cause": "DATA-001-02"},
    {"op": "new-cause", "temp_id": "NEW-CAUSE-1", "type": "DATA-001", "cause": {"title": "...", "resolution": "...", "signatures": []}, "body": "..."},
    {"op": "add-fixture", "for": "NEW-CAUSE-1", "kind": "positive", "path": "<work_dir>/ABC-12345/fixtures/cut-1.log"},
    {"op": "add-code-ref", "cause": "DATA-001-01", "code_ref": {"ref": "aosp:<상대 경로>", "symbol": "<클래스#메서드>", "android_versions": ["17"]}}
  ],
  "extra_samples": [{"path": "<work_dir>/ABC-12345/extra/a.log", "expect": "match"}],
  "feedback": {"date": "2026-09-27T18:30+09:00", "suggested": [], "decision": "new-cause", "final": "NEW-CAUSE-1"},
  "commit_message": "[NEW-CAUSE-1] add ABC-12345: ...",
  "pr": {"number": null, "branch": "issue/ABC-12345", "head_sha": null},
  "included_pending": []
}
```

- `source` (필수): 계획을 만든 흐름. 값은 §상태 값. 다음을 정한다.
  - 확인 화면과 PR 본문의 라벨: `record`면 **"수동 기록"** 과 실행/건너뛴 검증 목록을 표시한다 (`07-workflow.md §record`).
  - pending 피드백 포함: `analyze`일 때만.
  - `signatures_pending` 허용: `record`일 때만 (op 표 `new-cause`).
  - `sync-pr`는 원래 계획을 그대로 다시 적용하므로 `source`와 라벨이 유지된다 (`06-collaboration.md §6.3`).
- **이어서 하기**: 같은 작업 키에 계획이 있을 때 새 흐름의 `source`가 기존 계획과 같으면 이어서 할지 새로 시작할지 묻는다. **다르면 "새로 시작(기존 계획 덮어씀)"만 허용한다.** 같은 Jira의 계획을 만들거나 재개할 때(analyze 새로 시작·이어서 하기, record 모두)는 그 Jira의 pending 피드백을 지운다 (`03-issue-db.md §5.4 (3)`).
- `started_at`: 이 작업을 시작한 시각(analyze·record는 Step 0의 lock 획득 시각). 파일럿 지표 "PR까지 걸린 시간"(`started_at` → `pr` 기록 시각)의 기준이다 (`15-local-draft.md §15.5` S-7). 재적용해도 바뀌지 않는다.
- `schema_version`: 계획을 만들 때의 이슈 DB 스키마 버전. 적용 대상 트리와 다르면 `db_add apply`는 종료 코드 2를 내고, 해당 마이그레이션이 `upgrade_plan()`을 제공하면 `db_migrate upgrade-plan`으로 계획을 먼저 올리라고 안내한다. 제공하지 않으면 계획을 다시 만든다 (`06-collaboration.md §6.4`).
- `base_sha`: 계획의 결정을 내린 기준 트리 SHA. analyze·record는 계획을 저장할 때의 스냅샷 SHA, 그 밖의 흐름은 계획을 만든 시점의 스냅샷 SHA다. `publish`가 성공하면 그 적용 기준 SHA로 바뀐다. drift 검사의 기준이다 (아래 drift).
- `jira`: `jira.schema.json`의 필드와 맞춘다 (`key`, `model`, `sw`, `android_version`, `carrier`, `date`, `occurred_on`, `note`). `cause`는 op가 정하고, `analyzed_by`는 적용 시 config의 `user.ghe_id`로 채운다. `occurred_on`은 Jira 발생 시각의 날짜(발생 시각을 모르면 생략)다. Jira가 없는 작업(fix-submitted, verify-fix)은 `null`. **Jira 요약·설명·코멘트 원문 필드는 두지 않는다.** `note`는 사용자가 확인한 한 줄이고 마스킹을 거친 값이다 (`08-safety.md §8.1`).
  - `origin`: `mcp | file`. Jira MCP로 읽었으면 `mcp`, `--jira-file`이면 `file`. 기록 파일에는 쓰지 않는다. `summary`는 `file`이면 "Jira 메타데이터: 오프라인 파일" 라벨을 붙인다. **analyze는 `origin: file` 계획으로 PR을 만들지 않는다**: `--dry-run`으로 만든 계획을 실제 analyze가 이어받으면 Step 8 전에 Jira MCP로 다시 읽어 `jira`를 덮고 `origin: mcp`로 바꾼다. record는 `file`을 허용한다 (`06-collaboration.md §6.9`).
- 새 원인/유형은 계획 안에서 **임시 ID**(`temp_id`: `NEW-CAUSE-<n>`, `NEW-TYPE-<n>`)로 표현한다. `new-cause`, `new-type`(과 그 첫 원인)은 `temp_id`가 필수다. 실제 ID는 적용 시점에 최신 main 기준 다음 빈 번호로 할당하고, 계획 안의 모든 참조(op 필드, fixture 경로, 피드백, 커밋 메시지)를 치환한다. `sync-pr`로 다시 적용하면 그때의 main 기준으로 다시 할당된다.
- fixture 원본은 `work_dir`에 **마스킹된 상태로만** 둔다 (`parse_logcat.py cut`).
- `extra_samples`: R6 추가 표본. `expect`는 `match`(같은 증상) 또는 `nomatch`(정상). 이슈 DB에 넣으려면 별도 `add-fixture`(`kind: extra` 또는 `negative`)를 추가한다.
- `feedback`: 피드백 파일 내용(`03-issue-db.md §5.4 (3)`). `date`는 계획을 저장한 시각이고 피드백 파일의 `date`와 파일명 timestamp에 그대로 쓰인다(재적용해도 바뀌지 않는다). `record`는 `{"date": ..., "suggested": [], "decision": "manual", "final": <원인 ID | temp_id | unresolved>}`다.
- `pr`: push 전에는 `number`, `head_sha`가 `null`. `db_pr publish`가 채운다. `publish`는 이번 적용의 `ids`(`{임시 ID: 최종 ID}`, 선택 필드라 `schema_version`은 올리지 않는다)도 기록하되, 검증에 쓴 `base_sha`의 `schema/plan.schema.json`에 `pr.properties.ids`가 있을 때만 쓴다(옛 DB에만 해당: 없으면 기록하지 않고 출력 `pr_ids_recorded: false`, 기록했으면 `true`). `summary`는 이전 적용과 비교해 `ids[].previous_id`와 "X → Y 재할당"을 내고, 기록이 없는 옛 PR은 "재할당 내역: 확인 불가 (이전 적용 ID 기록 없음)"을 낸다.
- `included_pending`: 이 PR에 함께 올린 pending 피드백 목록 `[{file, pr}]`. 파일 사본은 `<work_dir>/<작업 키>/included_pending/`에 있고, `sync-pr` 재적용 때 다시 포함된다.

### op 표

| op | 필수 필드 | 대상 엔티티 | 적용 규칙 | ID 참조 필드 (temp_id 치환·renumber) |
|---|---|---|---|---|
| `append` | `cause` | Jira 파일(신규) | `cause`의 유형 디렉토리 `jira/<KEY>.yaml` 생성. 같은 Jira가 이미 있으면 중단 | `cause` |
| `unresolved` | `type` | Jira 파일(신규) | `cause: unresolved`로 생성. 같은 Jira가 이미 있으면 중단 | `type` |
| `new-cause` | `temp_id`, `type`, `cause`, `body` | 유형 `causes[]`, 본문 `### <ID>` 섹션 | 템플릿 `cause.yaml`로 만들고 원인 ID 순서에 넣는다. `resolution_verification: unverified`로 만든다(같은 계획에서 뒤에 오는 `verify-resolution`만 이것을 `verified`로 바꿀 수 있다). `fix.status`는 `fixed` 금지. `cause.signatures`가 비었으면 `cause.signatures_pending: true`가 있어야 하고, 이것은 계획 `source: record`일 때만 허용한다(`import` 포함 그 밖이면 apply 거부, `16-existing-assets.md §16.4`). 그때 `resolution_verification`은 `unverified`로 고정 | `temp_id`, `type` |
| `new-type` | `temp_id`, `category`, `type`, `first_cause`(`temp_id` 포함), `body`, `dir_slug` | 유형 디렉토리(신규) | 템플릿 `type.md`로 생성. 디렉토리명 `<유형 ID>-<dir_slug>`. **`type.symptom_signatures`는 모든 `source`에서 필수**(비었으면 apply 거부, 유형에는 `signatures_pending`을 둘 수 없다). 첫 원인에는 `new-cause` 규칙을 그대로 적용(원인 시그니처는 `record`에서만 pending 가능) | `temp_id`, `first_cause.temp_id` |
| `reclassify` | `jira`, `from`, `to` | Jira 파일 | `jira`가 기준 트리(main)에 **있어야 한다**(없으면 apply 거부). 파일을 `to` 유형 디렉토리로 이동, `cause: <to>`, `note`에 `reclassified from <from>` 추가. `to`가 `<유형 ID>:unresolved`면 원인 미확정 Jira(`from: unresolved`만)를 그 유형으로 옮기고 `cause: unresolved`를 유지한다(유형 병합, `note`는 `reclassified from <옛 유형 ID>:unresolved`) | `to` (새 원인·새 유형일 때) |
| `update-fix` | `cause`, `fix` (+선택 `history`) | 원인 `fix` | 필드 병합. `open`으로 되돌리면 현재 `verification`·`ref`·`fixed_in`을 `verification_history`에 한 항목으로 보존한 뒤 비운다. 그 항목의 `result`는 `history.result`(`failed \| reverted`)를 쓰고, 없으면 이전 검증이 있을 때 `passed`, 없을 때 `reverted`다. `history`의 `build`, `jira`, `fixture`, `note`도 항목에 넣는다 (`03-issue-db.md §5.9`). `fixed`로 바꾸는 것은 금지(`verify-fix` op로만). `wont-fix`·`not-a-bug` → `fix-submitted`는 허용, **`fixed` → `fix-submitted`는 거부**(먼저 `verify-fix` 실패나 회귀 의심으로 `open`으로 되돌린다). `fix.ref`는 `fix_ref_regex`에 맞아야 한다 | `cause`, `history.fixture` |
| `add-related` | `a`, `b` | 두 원인 `related` | 양쪽에 함께 추가 | `a`, `b` |
| `add-code-ref` | `cause`, `code_ref` (`{ref, symbol, android_versions?}`) | 원인 `code_refs[]` | 추가만. 기존 항목은 고치지 않는다 | `cause` |
| `add-parser-rule` | `file`, `rule` | parser-rules 항목 | 키(`tag`/`tag_regex`, `name`, `id`)가 없어야 한다. 이력 필드 필수 | `rule.added_for` |
| `update-parser-rule` | `file`, `key`, `rule` | parser-rules 항목 | 키가 있어야 한다. 기능 필드를 바꾸고 `reason`, `added_on`을 갱신 | `rule.added_for` |
| `update-signature` | `owner`, `kind`, `sig_id`, `signature` | 시그니처 | `owner`는 유형 ID(`kind: symptom`) 또는 원인 ID(`kind: cause\|recovery\|scenario`). `sig_id`가 있으면 교체, 없으면 추가. 대상 원인에 `signatures_pending: true`가 있고 `kind: cause` 시그니처가 생기면 pending을 지운다 | `owner` |
| `set-resolution` | `cause`, `resolution` | 원인 `resolution` | `resolution_verification`을 `{status: unverified}`로 초기화 | `cause` |
| `verify-resolution` | `cause`, `verification` | 원인 `resolution_verification` | 적용 결과 `status: verified`(op의 `verification`에는 `status`를 넣지 않는다), `evidence`·`by`·`date` 필수(Jira 키 또는 `resolved` fixture 경로). evidence의 Jira 키는 `jira_key_regex`에 맞고 **적용 후 트리에 그 원인의 Jira 기록으로 존재**해야 하며, fixture 경로는 존재해야 한다(아니면 apply 거부. `db_lint`도 같은 검사). 대상 원인이 `signatures_pending`이면 거부. `cause`는 같은 계획의 `temp_id`여도 되고, 그 원인을 만드는 `new-cause`/`new-type`·`set-resolution`보다 **뒤에** 와야 한다. `record` 계획에서는 기록 대상 Jira(`jira.key`) 자신을 evidence로 쓸 수 없다(거부) | `cause`, `verification.evidence[]` |
| `verify-fix` | `cause`, `result`, `verification` (`build`·`date`·`by` 필수, `fixture`는 `passed`만 필수) | 원인 `fix` | `passed`: `fixed_in`에 `build`가 있는 항목이 있어야 한다(없으면 거부. 먼저 `fix-submitted`로 빌드 추가). `fix.status: fixed`, `verification` 기록. `failed`: `open`으로, 기록과 `ref`·`fixed_in`을 `verification_history`에 보존 후 비움. `partial`: 상태 유지(`fix-submitted`. 재검증 대상이 `fixed`면 `fixed` 유지 — 원인 시그니처는 여전히 불충족이므로 이 원인의 수정은 유효하다고 본다), `verification_history`에 `partial` 추가 | `cause`, `verification.fixture` |
| `set-status` | `id`, `status` | 유형 또는 원인 `status` | `active \| deprecated \| merged-into:<ID>`. 대상은 같은 계획의 `temp_id`여도 된다(병합: `new-cause` 뒤 옛 원인을 `merged-into:<temp_id>`로). 대상은 적용 시점에 있어야 하고 같은 종류(유형↔유형, 원인↔원인)여야 한다 | `id`, `status`의 `merged-into:` 대상 |
| `add-fixture` | `for`, `kind`, `path` (+`build`: `fixed`·`recurrence`일 때) | fixture 파일, `.expect.yaml` | `path`는 절대 경로, 계획 디렉토리 기준 상대 경로, 없으면 **이슈 DB 기준 상대 경로** 순으로 찾는다(병합 계획이 옛 원인의 fixture를 새 원인 이름으로 복사할 때. 적용 중인 트리에서 읽고 트리 밖은 거부). 이름은 §fixture 표로 정한다. 번호 `<n1>`/`<n2>`는 **적용 시점에 최신 main 기준 다음 빈 번호**로 할당한다(계획에 쓰지 않음). `build`는 `sanitize_build`를 거친다. `expect`나 `occurred_at`이 기본값과 다를 때만 `.expect.yaml`을 쓴다 | `for`, 파일명, `expect` 값 |
| `allow-cause` | `fixture`(유형 디렉토리 기준 경로 또는 같은 계획의 `add-fixture` 대상), `cause` | 그 fixture의 `.expect.yaml` `also_allowed` | `also_allowed`에 `cause`를 추가한다(`.expect.yaml`이 없으면 기본 기대값으로 만들고 추가). 대상 fixture가 양성·`recurrence`·`extra`·`"<유형 ID>:unresolved"` 기대값일 때만. `cause`는 그 fixture의 대상 원인 자신이나 같은 유형의 원인일 수 없다(같은 유형 안의 충돌은 시그니처 설계 문제). 같은 로그에 실제로 두 현상이 있을 때만 쓴다(§fixture). 대상 fixture가 다른 카테고리면 그 카테고리 오너가 리뷰어에 추가된다(`02-config.md §5.3`) | `cause`, `fixture` 경로 |

- op는 `operations`의 **순서대로** 적용한다. 같은 대상에 대한 뒤의 op가 앞의 결과를 바꿀 수 있다(예: `new-cause` → `verify-resolution`).
- 새 유형/원인의 `add-fixture`는 `for`에 `temp_id`를 쓴다.
- `kind`는 §fixture 표의 종류 이름(`positive`, `negative`, `fixed`, `resolved`, `recurrence`, `extra`)이다. `negative`의 `for`는 유형 ID다.
- 직접 편집한 브랜치의 임의 필드·본문·파일 변경은 계획 op로 표현하지 않는다(v1에는 replay 전용 op가 없다, `99-deferred.md`).

### drift (계획 대상 변경 검사)

계획은 `base_sha` 트리를 보고 내린 결정이다. 적용할 main이 그 뒤 바뀌었으면, 계획이 건드리는 대상이 main에서 먼저 바뀌었는지 `db_add drift`가 확인한다. `db_pr stage`가 `base_sha`와 기준 SHA가 다를 때 자동으로 돌린다 (analyze Step 8, 재개한 계획, `sync-pr` 모두).

| op | drift로 보는 경우 |
|---|---|
| `append`, `unresolved`, `add-related`, `add-code-ref`, `add-fixture`, `new-cause` | 대상 원인·유형이 `active`가 아니게 됨 (deprecated, merged-into) |
| `new-type` | 같은 카테고리에 제목·증상 시그니처가 같은 유형이 생김 (`db_add similar` 기준 상위 1개가 동일) |
| `reclassify` | 그 Jira 파일의 `cause`가 `from`이 아니게 됨, 또는 파일이 없어짐 |
| `update-fix`, `verify-fix` | 대상 원인의 `fix`가 바뀜 |
| `set-resolution`, `verify-resolution` | 대상 원인의 `resolution` 또는 `resolution_verification`이 바뀜 |
| `update-signature` | 같은 `sig_id` 시그니처가 바뀌거나 없어짐, 추가하려는 `sig_id`가 이미 생김 |
| `add-parser-rule` / `update-parser-rule` | 추가하려는 키가 이미 생김 / 대상 키의 기능 필드가 바뀌거나 없어짐 (이력 필드만 바뀐 것은 drift가 아니다) |
| `set-status` | 대상의 `status`가 바뀜 |
| `allow-cause` | 대상 fixture가 없어짐, 또는 그 `.expect.yaml`의 `also_allowed`·`expect_top`이 바뀜 |

- drift 항목은 `{op_index, op, target, field, plan_value, plan_base_value, current_value}`다. 사용자에게는 세 값을 모두 보인다: **계획 값**(`plan_value`, 그 op가 쓰려는 값, op가 그 필드를 쓰지 않으면 `null`)·**계획 당시 main 값**(`plan_base_value`)·**현재 main 값**(`current_value`). `plan_base_value`를 "계획 값"으로 보이지 않는다.
- drift 항목마다 사용자가 고른다: **계획 값 유지**(op 그대로) / **main 값 유지**(그 op 삭제) / **직접 입력**(op 수정). 결정을 계획에 반영하고 `base_sha`를 기준 SHA로 바꾼 뒤 다시 `stage`한다.
- 스키마 변경으로 op 형식이 달라진 경우는 drift가 아니라 `schema_version` 불일치로 처리한다 (위 `schema_version`).

---

## fixture

### 명명

위치: `<유형 디렉토리>/fixtures/`. 구분자는 `.`이다. 파일 종류는 파일명 **전체를 아래 정규식과 fullmatch**해서 판별한다. 맞지 않는 파일명은 `db_lint` 오류다.

- `<유형 ID>` = `[A-Z][A-Z0-9]*-\d{3}`, `<원인 ID>` = `<유형 ID>-\d{2}`
- `<build>` = `[A-Za-z0-9_+-][A-Za-z0-9._+-]*` (`sanitize_build` 결과, §3.2)
- `<n1>` = `[1-9]\d*` (1부터 시작하는 번호), `<n2>` = `[2-9]|[1-9]\d+` (2부터 시작하는 번호)

| 종류 (`kind`) | 파일명 | 용도 | 기본 기대값 |
|---|---|---|---|
| `positive` (양성) | `<원인 ID>.log`, `<원인 ID>.<n2>.log` | 원인 판별 | `expect_top: <원인 ID>` (그 원인 C=1, 다른 원인 C=0) |
| `fixed` (수정 후) | `<원인 ID>.fixed.<build>.log` | verify-fix 통과 로그 | `expect_not: <원인 ID>` |
| `resolved` (해결책 적용 후) | `<원인 ID>.resolved.<n1>.log` | 해결책 검증 로그 | `expect_not: <원인 ID>` |
| `recurrence` (재발) | `<원인 ID>.recurrence.<build>.log` | verify-fix 실패·회귀 로그 | 양성과 동일 |
| `negative` (음성) | `<유형 ID>.none.log`, `<유형 ID>.none.<n2>.log` | 정상 로그 | `expect_top: none` |
| `extra` (R6 추가 표본) | `<원인 ID>.extra.<n1>.log` | 같은 증상의 다른 로그 | 양성과 동일 |

- `resolved`와 `extra`는 첫 파일이 `.1`이다 (`.resolved.1.log`). `positive`와 `negative`는 첫 파일에 번호가 없고 둘째부터 `.2`다.
- 경로는 **유형 디렉토리 기준 상대 경로**로 쓴다: `fixtures/DATA-001-03.fixed.BUILD_X.log`. `fix.verification.fixture`, `verification_history[].fixture`, `resolution_verification.evidence`의 fixture 항목도 같은 형식이다.
- 기대값을 바꾸려면 같은 이름에서 `.log`를 `.expect.yaml`로 바꾼 파일을 둔다 (`DATA-001.none.expect.yaml`).

### 기대값 (`.expect.yaml`)

| 필드 | 의미 |
|---|---|
| `expect_top: <원인 ID>` | 그 원인이 C=1이고, **`also_allowed`를 제외한 이슈 DB의 다른 모든 active 원인은 C=0** (판정은 S/C 값만 쓴다. 점수·신뢰도는 결과표의 참고 값이다) |
| `expect_top: "<유형 ID>:unresolved"` | 그 유형이 S=1이고, `also_allowed`를 제외한 모든 active 원인이 C=0 |
| `expect_top: none` | **이슈 DB 전체에서 S=1인 active 유형이 없음** (음성 fixture는 유형별 이름이지만 기대값은 전역이다. 새 유형의 증상 시그니처가 다른 유형의 정상 로그를 잡으면 여기서 걸린다) |
| `expect_not: <원인 ID>` | 그 원인이 C=1이면 실패 |
| `also_allowed: [<원인 ID>...]` (선택) | 이 fixture에서 C=1이어도 되는 **다른 유형의** 원인. 같은 로그에 실제로 두 현상이 있을 때만 쓴다(예: 데이터 fixture에 등록 거절도 실제로 있음). 대상 원인 자신, 같은 유형의 원인, 없는 ID는 `db_lint` 오류. 추가는 `allow-cause` op로 하고, 다른 카테고리 fixture에 추가하면 그 카테고리 오너가 리뷰한다. 누적은 월간 리뷰가 본다(`06-collaboration.md §6.6`) |
| `occurred_at: <ISO 시각>` (선택) | fixture 원본의 발생 시각. 회귀 판정에는 쓰지 않고, 결과에 근거 시각과의 거리를 함께 보여줄 때 쓴다 |
| `origin: synthetic` (선택) | 사외 모의 환경에서 생성한 합성 fixture 표시 (`15-local-draft.md §15.2`) |

- 회귀는 항상 회귀·검증 모드(`--regress`)로 돈다: 분석 범위 = fixture 전체, bonus = 0, 피드백 가중치 끔, 모든 active 원인의 C를 독립 평가 (`04-parser-matching.md §5.11 (4)`). fixture는 `parse --mask`로 파싱한다(멱등).
- `db_regress`는 기대값이 깨지면 원인을 함께 낸다: 음성 fixture면 S=1이 된 유형과 증상 시그니처 전역 키, 양성이면 C=1인 원인 목록과 그 시그니처 전역 키. 실패가 **다른 유형의 원인이 C=1이 된 것** 때문이면 `allow-cause` op 초안(`fixture`, `cause`)을 함께 낸다(`--draft`면 새 원인은 계획의 `temp_id`로 낸다 — 그대로 계획에 붙인다. 사용자가 시그니처를 좁힐지 허용할지 고른다, `07-workflow.md §Step 7`).
- `status`가 `active`가 아닌 원인의 fixture는 회귀에서 제외한다.
- `signatures_pending: true`인 원인의 양성 fixture는 회귀에 **포함**하고, 기본 기대값은 `expect_top: "<유형 ID>:unresolved"`다(유형의 증상 시그니처가 이 로그를 잡고, 다른 원인이 C=1로 잘못 잡지 않는지 확인). 시그니처를 추가하는 `update-signature`로 pending이 지워지면 양성 기본 기대값(`expect_top: <원인 ID>`)으로 바뀌고 R1·R2 입력이 된다.

---

## 브랜치

| 접두어 | 용도 | 만드는 주체 |
|---|---|---|
| `issue/<JIRA-KEY>` | 분석 결과 또는 수동 기록 반영 | analyze, record |
| `fix-submit/<원인 ID>` | 수정 CL 반영 (`fix-submitted`) | `fix-submitted` 커맨드 |
| `verify-fix/<원인 ID>-<build>` | 코드 수정 검증 결과 | `verify-fix` |
| `verify-res/<원인 ID>-<YYYYMMDD>` | 해결책 검증 결과 | `validate --cause` |
| `review/<category>-<YYYY-MM>` | 월간 리뷰 정리 | 카테고리 오너 (직접 편집 또는 `source: review` 계획) |
| `chore/fix-db-<문제 ID>` | 사후 lint 정리 (`06-collaboration.md §6.3`) | 메인테이너 (**직접 편집, 계획 없음**) |
| `migrate/schema-v<N>`, `migrate/ci-<mode>` | 스키마/CI 모드 전환 (`06-collaboration.md §6.4`, `13-actions.md`) | 메인테이너 (**직접 편집, 계획 없음**. `migrate` 커맨드가 이 브랜치의 워킹 트리를 바꾼다) |
| `category/<key>` | 새 카테고리 (`06-collaboration.md §6.10`) | 메인테이너 (**직접 편집, 계획 없음**) |
| `move/<옛 ID>-to-<새 ID>` | 유형 이동/병합 | 카테고리 오너 (`source: move` 계획) |
| `import/<category>-<n>` | 기존 분류 가져오기 (`16-existing-assets.md §16.4`, PR당 유형 10개 이하) | 카테고리 오너 (`source: import` 계획), 카테고리 오너 리뷰 필수 |

- 위 이름은 **원격 브랜치 이름**이다. `db_pr`는 로컬에 도구 브랜치 `tt/<이름>`만 만들고 `HEAD:refs/heads/<이름>`으로 push한다 (§3.2 `db_pr.py` 세부). 사용자가 직접 편집하는 브랜치(`review/...`, `chore/...` 등)는 사용자가 자기 로컬 브랜치로 만든다.
- `<build>`는 `sanitize_build`(§3.2)를 거치고, 브랜치 이름은 `git check-ref-format --branch`로 검사한다.
- 시작 전에 `db_pr.py preflight --branch <br> --search "<원인 ID 또는 JIRA-KEY>"`로 열린 PR을 보여준다.
- 로컬·원격 브랜치가 이미 있을 때의 처리는 `07-workflow.md §Step 8`의 2번을 따른다 (모든 브랜치 공통).
- worktree는 항상 `git worktree add --no-track`으로 만든다 (원격 추적 설정이 push 대상을 바꾸지 않게).
- PR 제목: `[<원인 ID 또는 유형 ID>] <요약>`. PR 하나에는 Jira 하나(또는 리뷰 정리 한 묶음)만 넣는다. 예외: pending 피드백 파일은 analyze PR에 함께 올릴 수 있다.

---

## renumber 참조

ID가 바뀔 때 함께 바꿔야 하는 참조 목록이다. `db_add renumber`(직접 편집한 브랜치의 수동 보조)와 메인테이너의 사후 중복 정리(`06-collaboration.md §6.3`)가 이 목록을 쓴다. 도구가 만든 PR은 계획의 `temp_id`를 적용 시점에 할당하므로(`sync-pr` 재적용 포함) renumber가 필요 없다.

유형 ID가 바뀔 때
- type.md `id`, 유형 디렉토리명, 소속 원인 ID 접두어 전체(아래 원인 목록 전부 적용)
- 음성 fixture 파일명 `<유형 ID>.none[.<n2>].log`와 `.expect.yaml`의 `expect_top: "<유형 ID>:unresolved"`
- 다른 유형의 `status: merged-into:<유형 ID>` 대상
- `parser-rules` 이력 필드 `added_for`

원인 ID가 바뀔 때
- type.md 원인 `id`와 본문 `### <ID>` 제목
- 이 원인을 가리키는 모든 `related` (역방향 포함)
- 다른 원인의 `status: merged-into:<원인 ID>` 대상
- Jira 기록 `cause`
- fixture 파일명(모든 종류)과 `.expect.yaml`의 `expect_top`/`expect_not`/`also_allowed`(다른 유형 fixture의 `also_allowed`에 든 것 포함)
- `fix.verification.fixture`, `verification_history[].fixture`, `resolution_verification.evidence`의 fixture 경로
- 피드백 `final`, `suggested[].cause`, `suggested[].signature` 전역 키
- `parser-rules` 이력 필드 `added_for`
- PR 제목과 PR 본문 (`gh pr edit`)

규칙
- `db_add renumber`는 "내 ID"만 바꾼다: 브랜치와 main의 merge-base에 없고 브랜치에서 새로 생긴 ID. main에 이미 있는 ID는 거부한다.
- main에 같은 ID가 두 번 들어온 경우의 사후 정리는 v1에서 도구가 하지 않는다. 메인테이너가 `06-collaboration.md §6.3` 절차로 직접 편집한다 (자동화는 `99-deferred.md`).
- 치환 뒤 `db_lint --residual <옛 ID>=<새 ID>`로 치환한 파일에 옛 ID가 남았는지 검사한다. 남으면 실패다.
- 사후 정리 커밋은 메시지에 `Renumbered: <옛 ID> -> <새 ID>` 트레일러를 남긴다. `db_search`는 이 트레일러와 `merged-into:` 체인으로 옛 ID → 새 ID를 연결한다. 머지 전 재할당은 main에 옛 ID가 존재한 적이 없으므로 매핑을 남기지 않는다.

---

## 상태 값

| 대상 | 허용 값 | 비고 |
|---|---|---|
| 유형 `status` | `active \| deprecated \| merged-into:<유형 ID>` | 매처는 `active`만 후보로 쓴다 |
| 원인 `status` | `active \| deprecated \| merged-into:<원인 ID>` | 같음 |
| 원인 `signatures_pending` | `true` 또는 생략 | **원인에만** 둔다(유형은 증상 시그니처 필수). `true`면 원인 판별 시그니처(`signatures`)가 비어 있어도 된다. `db_lint` 경고, 월간 리뷰 "시그니처 없는 원인", 매처는 매칭할 수 없음. `resolution_verification: unverified` 고정. 만드는 것은 `record`뿐이고, `sync-pr`는 record 계획을 그대로 재적용하므로 유지된다 (op 표 `new-cause`) |
| `resolution_type` | `user-setting \| carrier-config \| framework-bug \| vendor-ril \| modem \| network \| hw` | 코드·설정 수정 유형 = `framework-bug`, `vendor-ril`, `modem`, `carrier-config` |
| `fix.status` | `open \| fix-submitted \| fixed \| wont-fix \| not-a-bug` | 필수 필드는 `03-issue-db.md §5.9` |
| `fix.ref` | `fix_ref_regex`(`02-config.md §5.3`)에 맞는 문자열 또는 `null` | `db_lint`와 `update-fix` 적용이 검사한다 |
| `fix.fixed_in[]` | `{branch: <필수>, build: <선택>}` | `build`가 없으면 `03-issue-db.md §5.9` 판정은 "판단 불가", verify-fix 통과 불가 |
| `resolution_verification.status` | `unverified \| verified` | `verified`는 `evidence` 필수. 근거가 사용자 진술뿐이면 `unverified`로 두고 "근거: 사용자 진술"을 남긴다(새 원인은 `method`, 기존 원인은 Jira 기록 `note`. 월간 리뷰 "사용자 진술만 있는 해결책", `06-collaboration.md §6.6`) |
| `fix.verification.result` | `passed` | `fixed`일 때만 존재 |
| `verification_history[].result` | `passed \| failed \| partial \| reverted` | `passed`: 회귀로 되돌려진 이전 검증. `reverted`: 검증 없이 `open`으로 되돌림(회귀 의심 확인 등). 최신이 위 |
| `db_verify fix` 판정 | `passed \| partial \| failed \| unknown` | `05-verification.md §5.12 (2)` |
| `db_verify resolution` 판정 | `passed \| failed \| unknown` | `05-verification.md §5.12 (1)` |
| R1~R6 항목 상태 | `pass \| fail \| needs-approval \| skipped \| not-implemented` | `needs-approval` → 종료 코드 `3`. `skipped`는 `reason` 필수(`해당 없음`, `fixture 없음`, `음성 fixture 없음`, `시그니처 없음(pending)`). `fixture 없음`·`음성 fixture 없음`은 `review_required: true`이고 **통과로 표시하지 않는다**. `not-implemented`는 Phase 7~9 뼈대에서만 썼다(Phase 10부터 내지 않는다) |
| 피드백 `decision` | `accepted \| chose-other \| new-cause \| new-type \| unresolved \| manual` | `manual`은 `record`(수동 기록). `suggested: []`이고 수락률·1위 정확도 통계에서 제외 |
| 계획 `source` | `analyze \| record \| import \| fix-submitted \| verify-fix \| validate-cause \| review \| move` (9개) | §작업 계획. 마이그레이션·새 카테고리·사후 정리는 계획이 아니라 직접 편집 브랜치다(§브랜치) |
| 계획 `jira.origin` | `mcp \| file` | §작업 계획 |
| `ci_mode` | `local \| actions \| actions-build` | `13-actions.md` |

`verification_history[]` 항목 형식

```yaml
- result: failed                  # passed | failed | partial | reverted
  build: <검증 빌드>               # reverted면 생략 가능
  date: 2026-10-05
  by: <GHE 아이디>
  jira: ABC-13000                 # 선택
  fixture: fixtures/CALL-001-01.recurrence.BUILD_Y.log   # 선택
  ref: <되돌릴 때의 fix.ref>        # open으로 되돌린 경우에만
  fixed_in: [{branch: <브랜치>, build: <빌드>}]           # open으로 되돌린 경우에만
  note: 재현 시나리오 수행, 원인 시그니처 충족
```

---

## 기존 자산 연결 계약

`16-existing-assets.md`의 계약이다. 아래는 §작업 계획·§상태 값·§브랜치의 `import` 항목과 함께 읽는다.

- 계획 `source: import`: `record` 규칙을 따르되 새 유형·원인 모두 시그니처 필수(pending 불가), 한 PR에 유형 10개 이하, 피드백 기록 없음, 해결책은 `unverified`로 시작(근거 Jira가 있으면 같은 계획의 `verify-resolution`으로 verified). 브랜치 `import/<category>-<n>`, 카테고리 오너 리뷰 필수.
- 사용자 config/`site-defaults.yaml`의 `jira.tools`(논리 동작 `get_issue` 필수, `search_issues`·`get_comments` 선택 → 실제 도구 전체 이름). 스킬은 도구 이름을 직접 쓰지 않고 `jira.tools`로 부른다. `read_tools`는 `jira.tools` 값을 포함해야 한다.
- **파서 백엔드** `plugin/scripts/parser_backends/base.py`: `parse(paths, tz, year, window) -> events[]`, `builtin_events() -> [이름]`, `version() -> str`(선택: `configure(profile) -> 백엔드`, `platforms.PlatformProfile`을 반영한 복사본, 기본은 자기 자신 — `_line_record`를 직접 구현한 site 백엔드는 무시해도 된다). 선택은 `site-defaults.yaml`의 `parser.backend: site | reference`. 백엔드 내장 판별 이벤트 이름은 `builtin.<category>.<이름>`, 이벤트 `source: backend:<name>`. 마스킹·extractor·태그 매핑은 백엔드가 아니라 `parse_logcat.py`가 한다. reference 백엔드 구현은 `platforms/android/backend.py`이고 `parser_backends/{reference,logcat,ril}`는 같은 모듈을 가리키는 호환 shim이다(사내 site 백엔드의 `from ..reference import ReferenceBackend` 유지). 골든 테스트 `tests/golden/*.orig.json`(사내 전용) + `tests/test_golden.py`. 이벤트의 `line_ref`(`{file_index, line_no}`, 줄 위치를 줄 수 없으면 `null`)는 백엔드가 내는 선택 키이고, builtin 레코드는 그 줄 레코드의 값을 그대로 가진다. 골든 비교에서는 `test_golden.py`의 `VOLATILE_FIELDS`로 뺀다(골든 파일은 그대로, 키 유무는 `test_backend_emits_line_ref`가 본다). 이벤트 형식 검사 `common/events.py::validate_event`(사내 포팅 백엔드 확인용, 테스트에서만 쓴다).
- 이슈 DB 쪽 백엔드 고정: `issue-db.config.yaml`의 `parser_backend: {name, min_version}`. 불일치면 `config.py check`가 쓰기 불가(종료 코드 2 사유 `parser-backend-mismatch`), `db_regress`는 종료 코드 2, 분석은 경고 후 진행. `db_lint`는 `must_event: builtin.*`이 `builtin_events()`에 없으면 오류. 캐시 해시에 백엔드 이름·버전 포함.
- **외부 파서(어댑터, 대안)**: `site-defaults.yaml`의 `external_parsers.<category>`(`command`, `output`, `adapter`, `version`, `mode: merge|replace`, `timeout_sec`). `command` 안의 `${CLAUDE_PLUGIN_ROOT}`는 `parse_logcat.py`가 자기 설치 위치로 치환한다. 외부 파서 이벤트 이름은 `ext.<category>.<이름>`, 이벤트 `source: external:<adapter>`.
  - 이슈 DB 쪽 고정: `issue-db.config.yaml`의 `external_parsers: {<category>: {adapter, min_version}}`. 여기에 있는 카테고리의 어댑터가 없거나 버전이 낮으면 파서 백엔드 불일치와 같이 처리한다(쓰기 불가 사유 `external-parser-mismatch`, `db_regress` 종료 코드 2, 분석은 경고 후 진행). 캐시 해시에 어댑터 이름·버전 포함.
  - `db_lint`: `must_event: ext.<category>.*`은 그 카테고리가 이슈 DB `external_parsers`에 있을 때만 허용한다(없으면 오류).
  - `--no-external`은 분석 모드 디버그용이다. 리포트에 "외부 파서 끔"을 표시하고, `db_regress`·`db_verify`는 이 옵션을 받지 않는다(종료 코드 2).
- 이벤트 이름 공간: parser-rules extractor 이벤트는 접두어 없음(예: `data_evaluation_rejected`), 백엔드 내장 판별은 `builtin.<category>.<이름>`, 어댑터(외부 파서)는 `ext.<category>.<이름>`. extractor는 `builtin.`/`ext.` 접두어 이벤트를 만들 수 없다.
- **분석 스킬** `analyzers.<category>`(`site-defaults.yaml` 또는 사용자 config): `skill`, `when: ask | after_match | always_for_category`(기본 `ask`), `inputs`. `ask`는 1위 후보가 그 카테고리일 때 호출 여부를 묻는다. analyze 옵션 `--analyzer`는 묻지 않고 호출하고, `--no-analyzer`는 호출하지 않는다.
- 마스킹 토큰: `<종류#n>` 번호 토큰(파일 안에서 같은 값 = 같은 번호, 이미 있는 토큰 다음 번호부터, `08-safety.md §8`). 시그니처·extractor는 특정 번호를 고정하지 않는다.
- 설정 우선순위: 사용자 config > `plugin/site-defaults.yaml` > 코드 내장 기본값. `plugin/site-defaults.yaml`이 없으면 setup과 모든 커맨드·스크립트가 종료 코드 2로 멈춘다. `site-defaults.example.yaml`은 **코드가 읽지 않는다**. 사외 테스트·eval은 테스트 헬퍼 `tests/helpers/make_plugin_root.py`가 example을 `site-defaults.yaml`로 복사한 임시 플러그인 루트를 만들어 `${CLAUDE_PLUGIN_ROOT}`로 준다(`15-local-draft.md §15.1`). 런타임 코드에는 "사내/사외 모드" 판별이 없다.
- 사내 전용 경로: 레포 루트 `SITE_PATHS` 목록 파일, 재반입은 `tools/import_draft.py`와 반입 기준선 `.draft-manifest.json`(`15-local-draft.md §15.6`). 경계 검사는 `tools/check_boundary.py`(종료 코드 0 위반 없음 / 1 위반 / 2 사용 오류), 반입 때 `import_draft.py --check-boundary`(위반이면 종료 코드 1, 대상 변경 없음).
