# 설계서: 이슈 시스템 범용화 (jira → tracker)

기준은 main fdf3ced이고, 코드는 바꾸지 않았다. 줄 번호는 fdf3ced 기준이다. 이 설계서는 TRACKER.md 범위 ①~④와 RULES.md를 따른다.

## 0. 먼저 결정할 것: 원칙 (d)와 스키마 버전 올림

**추천은 원칙 (d)다. `schema_version: 1`을 유지하고 v1 정의를 직접 고치며, 마이그레이션은 추가하지 않는다.** TRACKER.md에 적힌 "스키마 버전 올림 + db_migrate"와 다르므로 **메인이 사용자에게 한 줄 확인을 받아야 한다.**

근거:
- 원칙 (d)는 이미 승인된 결정이다(`DRAFT_NOTES.md:56`, `docs/design/06-collaboration.md:142` "첫 배포(반입) 전에는 v1 정의를 직접 고치고").
- 배포된 이슈 DB가 없다.
  - 반입 묶음 Z가 아직 미완이다(`DRAFT_NOTES.md` 남은 일).
  - `plugin/scripts/migrations/`가 비어 있다. 실제 마이그레이션이 0개이고, `tests/fixtures/migrations/0001_example_jira_tags.py`는 예시 fixture일 뿐이다.
- 버전을 올리면 영구 호환 코드가 생긴다. §6.4 표(`06-collaboration.md:145-151`)에 따르면 min보다 옛 DB도 "분석은 가능"해야 한다. 그러면 `jira/`·`issues/`, `jira_key_regex`·`tracker.key_regex`를 둘 다 읽는 코드가 `issuedb.py:169`, `compiled.py:43`, `db_search`, `db_build`, `bridge`에 영구히 남는다. 쓰기만 막는 `SUPPORTED_SCHEMA=(2,2)`로 가도 분석 경로에는 이중 읽기가 필요하다.
- 사용자 요구 "하위 호환 마이그레이션은 최소"에도 (d)가 더 맞다.
- `GENERATOR_VERSION`도 1로 유지한다. README 링크 경로가 바뀌지만 배포된 DB가 없다. 샘플 DB는 `db_build --write`로 다시 만든다.

사용자가 버전 올림을 고르면 대안 B로 간다(이 경우 묶음 1이 L에서 XL이 된다).
- `migrations/0001_tracker_rename.py`(v1→v2): 폴더 이동, 필드 개명, config 블록 변환을 한다.
- `upgrade_plan()`: 계획 최상위 `jira`→`issue`, `reclassify.jira`→`issue`, `android_version(s)` 개명.
- `SCHEMA_VERSION=2`, `SUPPORTED_SCHEMA=(1,2)`, v1 읽기 경로 이중화.

## 1. 이름 변경 표(전수)

규칙:
- **바꾸는 것**:
  - 저장되는 형식: DB 파일·폴더·필드·키, 사용자·site 설정 키와 값, JOB 작업 파일과 그 안의 키.
  - 스크립트 CLI 옵션과 서브커맨드.
  - 기계가 읽는 출력 키·값·코드: analysis.json, 스크립트 JSON 출력, lint·reject 코드, doctor 행 이름.
- **바꾸지 않는 것**:
  - 사람에게 보이는 한국어 문구의 "Jira"(예외 1건: §3-6 게시 본문 머리).
  - 내부 함수·클래스·속성·모듈·스크립트 파일 이름(`jira_bridge.py`, `jira_fields.py`, `dbadd/ops/jira.py`, `JiraOps`, `IssueDb.jira`, `jira_counts`).
  - 모의 Jira 내부(`tests/mocks/jira/`, `MOCK_JIRA_*` 환경변수, `mock-jira` 서버, `customfield_*`).
  - 설계 문서 본문의 역사적 서술.
  - 이유: TRACKER ①이 이것들을 범위 밖으로 허용했고, 변경량과 검증 diff를 줄이기 위해서다.

### 1-A. 이슈 DB 형식 (샘플 `tests/fixtures/issue-db-sample/`, 변형 DB 생성기, 스키마)

| 옛 이름 | 새 이름 | 종류 | 영향 파일 |
|---|---|---|---|
| `<유형>/jira/<KEY>.yaml` | `<유형>/issues/<KEY>.yaml` | DB 폴더 | 샘플 7개 유형 폴더, `common/issuedb.py:5,169`, `common/compiled.py:4,43`, `dbadd/core.py:170,197-199`, `dbadd/ops/jira.py:43,91`, `db_lint.py:640,754`, `db_build.py:173`(`{base_rel}jira/` 링크), `db_summary.py:38,238,240`, `dbpr/publish.py:190`(정규식 `[^/]+/[^/]+/jira/`), `tools/make_bundle.py:257-258`, `tools/make_db_skeleton.py:4,14`, `tests/helpers/make_variant_dbs.py:519`, `tests/fixtures/migrations/0001_example_jira_tags.py`(`_SCHEMA`, glob), `skill_evals/grade.py:446,515,606,791,886,982,1293,1310` |
| `schema/jira.schema.json` | `schema/issue.schema.json` | 스키마 파일 | `plugin/schemas/`(원본), 샘플 사본(`tools/sync_schemas.py`로만), `db_lint.py:458`(`("type","jira",…)`→`"issue"`), title `jira/<JIRA-KEY>.yaml`→`issues/<KEY>.yaml` |
| `templates/jira.yaml` | `templates/issue.yaml` | 템플릿 | 샘플, CONTRIBUTING·docs, `make_db_skeleton` |
| config `jira_base_url` | `tracker.base_url` | DB 설정 키 | `db_build.py:92`, 샘플 config, `14-site.md` S17 |
| config `jira_key_regex` | `tracker.key_regex` | DB 설정 키 | `jira_fields.py:77`, `jira_bridge.py:102-103`, `issue_post.py:94`, `db_lint.py:217`, `db_search.py:204`, `dbadd/applier.py:45`, `common/issuepost.py:41` 주석 |
| (없음) | `tracker.kind`(없으면 `jira`) | DB 설정 키(신규) | §3-3. 샘플 jira DB에는 `kind: jira`를 명시한다 |
| config `readme.jira_inline_max` | `readme.issue_inline_max` | DB 설정 키 | `db_build.py:93` |
| config `android_versions_supported` | 샘플을 `platform_versions_supported`로 변환 | DB 설정 키 | 샘플 config만 바꾼다. 코드의 옛 키 대체 읽기(`issuedb.py:120` `SUPPORTED_VERSION_KEYS`, `db_lint.py:431-446`)는 **그대로 둔다**(이미 들어간 코드이고 필요한 만큼만 고친다) |
| 이슈 기록 `android_version` | `platform_version` | 스키마 필드(필수) | `issue.schema.json` required·properties, `dbadd/ops/jira.py:27,33`, `db_build.py:412`, `templates/issue.yaml` |
| type.md `android_versions`(원인·`code_refs[]`), `$defs/androidVersions` | `platform_versions`, `$defs/platformVersions` | 스키마 필드 | `type.schema.json:80,83,203,222`, `dbadd/core.py:25`(FRONTMATTER 순서), `dbadd/ops/entities.py:48`, `db_build.py:8,247-248,342`, `common/quality.py:152-154`, `db_review.py:205-210`, `db_search.py:27,68`, `match_signatures.py:26,478,524`, `triagelib/driver.py:634,775`, `common/yamldoc.py:64` 주석 |
| feedback `jira:` | `issue:` | 스키마 필드 | `feedback.schema.json:3,7,9`, `dbadd/applier.py:234,237`, 샘플 feedback 3개 |
| `fix.verification.jira`, `verification_history[].jira` | `.issue` | 스키마 필드 | `type.schema.json:137,153`, `dbadd/ops/fix.py:21-22,87` |
| 키 패턴 `^[A-Za-z][A-Za-z0-9]*-[0-9]+$` | 경로 안전 합집합 `^(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9_.-]{0,140}-[0-9]{1,10}$` | 스키마 패턴 | `issue.schema.json` key, `feedback.schema.json:9`, `plan.schema.json:24,123` |

### 1-B. 작업 계획(plan, JOB/plan.json, 스키마 `plan.schema.json`)

| 옛 이름 | 새 이름 | 영향 |
|---|---|---|
| 최상위 `jira {key, origin, model, sw, android_version, carrier, date, occurred_on, failed_step, note}` | `issue {…, platform_version, …}` | `plan.schema.json:16-31`, `dbadd/ops/jira.py:15-42`, `dbadd/core.py:120`, `dbadd/applier.py:226-237`, `dbadd/ops/resolution.py:29`, `db_summary.py:225,244-330`, `dbpr/publish.py:109`, `issue_post.py:124,300`, `triagelib/driver.py:247`, `tests/helpers/workspace.py:132`, `tests/fixtures/plans/*.plan.json`(11개), `tests/skill_evals/plans/e011,e016,e028` |
| `$defs/jiraKey` | `$defs/issueKey` | `plan.schema.json:123,229,306,339` |
| op `reclassify.jira`, verify 내용 `.jira` | `.issue` | `plan.schema.json:303-306,339`, `dbadd/ops/jira.py:58`, `dbadd/drift.py:101-103` |
| new-cause·new-type body `android_versions` | `platform_versions` | `plan.schema.json:198,209` |

### 1-C. 사용자 config·site-defaults

| 옛 이름 | 새 이름 | 영향 |
|---|---|---|
| `jira:` 블록 전체(`mcp_server, exclude_servers, tools, read_tools, write_tools.add_comment, timezone, field_map, failed_step_patterns`) | `tracker:` 블록(같은 하위 키 + `kind`) | `site-defaults.example.yaml:23-72`, `common/userconfig.py:50,64-66`, `config.py`(22곳), `common/issuepost.py:30,193-266`, `guard.py:14,18,43-44,368-394`, `jira_bridge.py:4,12,117`, `jira_fields.py:184-186`, `triagelib/driver.py:104`, `triagelib/anchor.py:41,256`, `common/failedstep.py:1,8`, `common/mcptools.py:6,10` |
| `field_map.android_version` | `field_map.platform_version` | `jira_fields.py:51`(`STRUCTURED`), site-defaults:61 |
| `logcat.year_source: jira` | `tracker` | `userconfig.py:51`, `config.py:64,76`(`YEAR_SOURCES`), `jira_fields.py:246,262`, site-defaults:81 |
| `analyzers.*.inputs: jira_summary` | `issue_summary` | site-defaults:134, `tests/mocks/skills/data-analyzer/{SKILL.md,run.py}`, `16-existing-assets.md` |
| `code_profiles[].android_version` | `platform_version` | `code_roots.py:131-141`(출력 키도 함께), `triagelib/driver.py:507`, `config.py` init·set 경로, `test_code_roots`, `test_config_setup` |

### 1-D. JOB 작업 파일(`<work_dir>/<KEY>/`)

| 옛 이름 | 새 이름 | 영향 |
|---|---|---|
| `jira_raw.json` | `issue_raw.json` | `jira_bridge.py:8,187`, `triagelib/driver.py:333,344`, `guard.py:27,102,1108`(`RAW_NAMES`), `skill_evals/grade.py:234-245,292,555,758` |
| `jira.json`(+내부 `jira` 블록 → `issue`, `android_version` → `platform_version`) | `issue.json` | `triagelib/driver.py:334-367`, `triagelib/anchor.py:50-64`, `triagelib/cache.py:81,101`, `triagelib/report.py:298`, `issue_post.py:9,298-299` |
| `jira_meta.json`(+`android_version`) | `issue_meta.json` | `driver.py:314,720`, `jira_fields.py:26,330-333` |
| `triage-state.json` `jira_done` | `issue_done` | `driver.py:334,355` |
| 입력 해시 부분 `jira` | `issue` | `triagelib/core.py:28`(`PART_KEYS`), `cache.py:101`, `analysis.schema.json:28` |
| `match.json`의 `jira` 블록 | `issue` | `match_signatures.py:447`, `dbpr/publish.py:110-112` |
| offline_eval `jira_input.json` | `issue_input.json` | `tools/offline_eval.py:124` |
| `post.*.json` | 그대로. 승인 기록의 `key_arg` 필드도 jira는 그대로(§3-6) | — |

### 1-E. CLI 옵션·서브커맨드 (`contracts-cli.md`는 `tools/gen_contracts.py --write`로만 갱신)

| 옛 이름 | 새 이름 | 영향 |
|---|---|---|
| `triage.py --jira-raw / --jira-file / --jira-meta` | `--issue-raw / --issue-file / --issue-meta` | `triage.py:4,9,33,113-115`, `driver.py:123-134,315-338,606`, `match_signatures.py:5,25,535`(`--jira-meta`), `tools/offline_eval.py:126`, `tools/bench_scale.py:207`, SKILL.md·reference·commands |
| `db_pr.py preflight --jira <KEY>` | `--issue <KEY>` | `db_pr.py:10,141,211`, `dbpr/publish.py:169-201`, `driver.py:402` |
| `config.py jira-candidates`, `set-jira` | `tracker-candidates`, `set-tracker` | `config.py:18-21,262-320,774-840`, `commands/setup.md`, `common/mcptools.py:10` |
| `issue_post.py render --format jira-wiki\|markdown` | 그대로(형식 이름은 트래커 본문 형식이다) | — |

### 1-F. 출력 키·값·코드

| 옛 이름 | 새 이름 | 영향 |
|---|---|---|
| analysis.json `jira`(+`android_version`) | `issue`(+`platform_version`) | `analysis.schema.json:50`, `driver.py:330,366-367`, `report.py:119,282,371,407`, `anchor.py:76` |
| analysis `step_anchor.jira_gap_min`, `source: "jira"` | `issue_gap_min`, `"issue"` | `analysis.schema.json:57,61,64`, `anchor.py:93,174,320,322` |
| analysis `files.jira`, 후보 `jira_count`, `jira_recent` | `files.issue`, `issue_count`, `issue_recent` | `analysis.schema.json:117,144-145`, `driver.py:625-626`, `report.py:483` |
| needs_input `kind: "jira"`, 인자 `jira_origin` | `"issue"`, `issue_origin` | `analysis.schema.json:172`, `driver.py:247,344` |
| 후보 `android_versions`, `_version_mismatch` | `platform_versions` | `match_signatures.py:524`, `driver.py:775` |
| db_search `kind: jira`, `jira`, `jira_count`, `jira_latest` | `issue`, `issues`, `issue_count`, `issue_latest` | `db_search.py:24-27,66,124-150,159,226,259,418-421`, `driver.py:385` |
| db_summary `jira {key, origin, label}` | `issue {…}` | `db_summary.py:306,489-492` |
| db_review `stale_unresolved[].jira`, 항목 id `open-with-jira`, 행 `.jira` | `.issue`, `open-with-issues`, `.issues` | `db_review.py:157,215-217` |
| quality 출처 문자열 `jira:<KEY>` | `issue:<KEY>` | `common/quality.py:147` |
| preflight `jira_in_main` | `issue_in_main` | `dbpr/publish.py:187-201` |
| lint 코드 `duplicate-jira`, `jira-key`, `jira-cause` | `duplicate-issue`, `issue-key`, `issue-cause` | `db_lint.py:10-11,764-772` |
| reject 코드 `jira-missing`, `jira-key`, `jira-exists`, `jira-fields` | `issue-missing`, `issue-key`, `issue-exists`, `issue-fields` | `dbadd/ops/jira.py:17-29` |
| jira_fields extract 출력 `jira` 블록 | `issue` 블록 | `jira_fields.py:15,248-259,330` |
| doctor 행 `jira`, `jira_post` | `tracker`, `tracker_post` | `config.py:598-635`, `grade.py:646`(eval 39 정규식) |

### 1-G. 바꾸지 않는 것(이유)

- 스크립트·모듈 파일 이름(`jira_bridge.py`, `jira_fields.py`, `ops/jira.py`)과 `hooks.json`. RULES가 "hooks.json은 바꾸지 않는다"고 하고, TRACKER ①이 허용했다.
- `gen_contracts.py:42-46`의 SCRIPTS 목록(파일 이름 불변).
- 본문 형식 이름 `jira-wiki`(`issuepost.py:34`). Jira 본문 형식의 이름이다.
- report.md·doctor 메시지의 "Jira" 문구. jira 설치에서 바이트가 같아야 한다. GitHub 설치의 라벨 일반화는 미룬다(§8 T7).
- `mcptools.NAME_WORDS`(`:35`). 동사 판정용이고 그대로 맞다.
- 모의 Jira 데이터·서버·환경변수.

## 2. 호환 전략

### 2-1. 이슈 DB
§0대로 v1을 직접 고친다. 옛 `jira/` 폴더는 읽지 않는다. 샘플 변환은 일회성 스크립트(W에 두고 커밋하지 않음)로 한다.
1. `git mv */*/jira */*/issues`, 스키마·템플릿 이름 변경.
2. YAML 키 치환은 줄 단위로, 키 위치만 바꾼다. 대상: 기록의 `android_version:`, type.md의 `android_versions:`, feedback의 `jira:`, fix 검증의 `jira:`.
3. config 블록 변환.
4. `tools/sync_schemas.py`, 이어서 `db_build.py --write`.

변형 DB는 `tests/helpers/make_variant_dbs.py`가 샘플에서 만들므로 생성기만 고친다.

### 2-2. 사용자 config·site-defaults: 감지만 하고 자동 변환은 하지 않는다

사용자는 사외 개발자뿐이고, site-defaults는 S-3에서 example을 보고 새로 만든다. 그래서 변환 계층은 필요 없다. 다만 **보안상 감지는 필수다.** 옛 `jira:`가 남아 있는데 그냥 무시하면 guard 입장에서 `tracker.mcp_server`가 비게 된다(`guard.py:387-388`). 그러면 규칙 2가 경고만 하고, 이름 휴리스틱 밖의 사내 Jira 서버 쓰기가 열린다. 보안이 약해지므로 막아야 한다.

- 새 함수 `userconfig.legacy_problems(defaults, user) -> list[str]`. 감지 항목:
  - (i) site-defaults나 사용자 config의 최상위 `jira` 키: "`jira:` → `tracker:` (+ `kind: jira`)".
  - (ii) `logcat.year_source: jira`: "→ `tracker`".
  - (iii) 프로필마다 `code_profiles[].android_version`: "→ `platform_version`".
- 처리:
  - guard: `Config.__init__`(`guard.py:194`)에서 계산한다. 비어 있지 않으면 `check_mcp` 맨 앞에서 **모든 `mcp__` 호출을 거부**한다. 메시지는 "옛 설정 키 … — tracker:로 바꾼다 (규칙 2)". 설정을 못 읽을 때와 같은 범위다.
  - bridge: `main`의 설정 오류 경로(`jira_bridge.py:305-312`)와 똑같이 모든 `mcp__` 결과를 오류 문구로 바꾼다.
  - 그 밖 스크립트: `path_problems`와 같은 관문(`platforms/session.resolve`)에서 종료 코드 2로 끝낸다.
  - `config.py show/set/doctor`는 계속 동작한다. doctor는 `tracker` 행을 fail로, 고칠 방법을 hint로 보인다.
- `tracker.kind`가 모르는 값이거나 형식이 틀리면(`trackers.TrackerConfigError`) 위와 같이 처리한다. guard는 mcp 전부 거부, bridge는 전부 대체, 스크립트는 종료 2.

## 3. 트래커 어댑터 계약 (`plugin/scripts/trackers/`)

### 3-1. 구조 (플랫폼 K1과 같은 패턴, 규모가 작아 패키지 대신 모듈)

```
trackers/
  __init__.py   # 레지스트리: NAME_RE·DEFAULT_KIND="jira"·known()·get(kind)·kind_of(cfg)·of(cfg)·
                #   db_kind(db_cfg)·all_server_words()·TrackerConfigError 재수출. 트래커 이름을 모른다
  base.py       # TrackerSpec(frozen dataclass, Callable 필드)·TrackerConfigError
  jira.py       # SPEC
  github.py     # SPEC
```
- 이름 규칙은 `^[a-z][a-z0-9_]*$`이고 `base`와 `_`로 시작하는 이름은 뺀다.
- `get`은 `importlib.import_module(f"trackers.{kind}")`로 불러오고, `SPEC` 타입과 `SPEC.name == kind`를 확인한 뒤 프로세스 안에 캐시한다(`17-platforms.md §1-1`과 같다).
- **계층 규칙(테스트로 강제)**: `trackers/*`는 표준 라이브러리만 import한다. guard가 `issuepost`를 거쳐 불러오기 때문이다(`issuepost.py:5` "표준 라이브러리와 mcptools만"). `common`·`platforms`·핵심 스크립트를 import하지 않고, 서로도 import하지 않는다.
- `kind_of(cfg)`: `cfg.tracker.kind`, 없으면 `"jira"`. 형식이 틀리거나 설치되지 않은 이름이면 `TrackerConfigError`.
- `db_kind(db_cfg)`: `db_cfg.tracker.kind`, 없으면 `"jira"`.
- `all_server_words()`: 설치된 **모든** 트래커 `server_words`의 합집합이다(설정과 무관하고, 하나가 깨져도 나머지는 쓴다). 레지스트리가 실패하면 내장 `("jira","atlassian")`을 쓴다. 이전보다 약해지지 않는다(`guard.raw_sniffers` `guard.py:241-269`와 같은 방식).

### 3-2. TrackerSpec 필드

| 필드 | 뜻 | jira | github |
|---|---|---|---|
| `name`, `label` | 이름, 게시 본문 머리 라벨 | `jira`, `Jira` | `github`, `GitHub` |
| `safe_key_re` | 작업 키 경로 안전 형식(작업 디렉토리·브랜치·피드백 파일 이름·DB 파일 이름) | `^[A-Za-z][A-Za-z0-9_]*-\d+$` (현 `issuepost.KEY_SAFE_RE` `:41` 그대로) | `^(?!.*\.\.)[a-z0-9][a-z0-9-]{0,38}\.[a-z0-9_][a-z0-9_.-]{0,99}-[1-9][0-9]{0,9}$` |
| `default_key_regex` | DB `tracker.key_regex`가 없을 때 | `[A-Z][A-Z0-9]+-\d+` (현 `jira_fields.py:50` 등 4곳 중복 → 여기 하나) | `safe_key_re` 본문 |
| `server_words` | 규칙 2 이름 휴리스틱 | `("jira","atlassian")` | `()` (§4-3) |
| `formats`, `default_format` | issuepost `RENDERERS` 키 | `("jira-wiki","markdown")`, `jira-wiki` | `("markdown",)`, `markdown` |
| `text_defaults` | summary·description·comments 기본 경로 | 현 `jira_fields.py:52-56` | `{summary:["title"], description:["body"], comments:["comments[].body"]}` |
| `components_default` | | `fields.components[].name` (`jira_fields.py:236`) | `labels[].name` |
| `parse_key(text) -> str\|None` | 사용자 입력 → 작업 키 | `safe_key_re`에 맞으면 그대로 반환 | 작업 키, `owner/repo#N`, `https://<host>/owner/repo/issues/N`을 받아 소문자 작업 키로 |
| `display(key)` | 본문·메시지 표시 | `key` | `owner/repo#N` |
| `link(base_url, key)` | README 링크 | `base_url + key` (`db_build.py:116`과 같다) | `base_url + "owner/repo/issues/N"` |
| `spec_problems(raw)` | add_comment 설정 중 어댑터별 검사 | `key_arg` 필수(현 검사 `issuepost.py:253-257`) | `key_arg` 금지, 키 인자는 고정 `owner, repo, issue_number` |
| `key_args(spec, key) -> dict` | 쓰기 도구 키 인자 | `{spec.key_arg: key}` | `{"owner":o, "repo":r, "issue_number":int(N)}` |
| `key_from_args(spec, tool_input) -> str\|None` | 도구 입력 → 작업 키 | `tool_input[key_arg]`가 str이고 `safe_key_re`에 맞으면 | owner·repo·issue_number 검사 + **왕복 검사**(§3-4) |
| `arg_names(spec)`, `key_arg_id(spec)` | 승인 범위 인자 집합, 승인 기록 `key_arg` 값 | `{key_arg}`, `spec.key_arg` | `{"owner","repo","issue_number"}`, `"owner,repo,issue_number"` |
| `read_action(tool_input, mapped: set) -> str\|None\|"unsupported"` | bridge 대상 판별(mapped = 이 도구가 매핑된 논리 동작) | mapped에서 `get_issue` 우선(현 `jira_bridge.py:122-123`) | `method`가 `get`이면 `get_issue`, `get_comments`이면 `get_comments`, 그 밖이면 `"unsupported"` |
| `key_from_read(data, tool_input, kre)` | 읽기 응답에서 키 | 현 `_find_key` (`jira_bridge.py:107-112`) | `key_from_args`(입력) → `kre.fullmatch` |
| `read_args(action, key) -> dict\|None` | needs_input 안내 인자 | `None`(출력 불변) | `{"method":"get"\|"get_comments","owner","repo","issue_number"}` |
| `classify_extra(tool, actions)` | setup 후보 보강 | 그대로 | `issue_read`가 `get_issue`이면 `get_comments`도 추가 |

### 3-3. 이슈 DB 선언과 `tracker-mismatch`
- DB config 블록 `tracker: {kind, base_url, key_regex}`. `kind`가 없으면 jira다.
- db_lint가 `kind`가 설치된 트래커인지(`config` 오류), 기록 키가 `key_regex`와 그 kind의 `safe_key_re`에 맞는지(`issue-key`) 본다.
- 세션 `tracker.kind`와 DB kind가 다르면 **거부한다**(종료 2, 메시지 "tracker-mismatch").
  - 이유: 키 공간·링크·도구 인자가 다른 DB에 기록하는 것은 의미가 없다(플랫폼 K5와 같은 근거).
  - 판정 위치: `jira_fields.py check-key`. 모든 흐름의 첫 관문이다(`driver.py:143`, contracts §3.2 작업 키 검증). `issue_post.Job.__init__`(`issue_post.py:91-97`)에서도 본다.
  - jira·jira 조합에서는 출력이 바뀌지 않는다.
- `check-key`는 입력을 먼저 `parse_key`로 정규화하고, 출력 `key`에 작업 키를 낸다(jira는 입력 그대로). 스킬은 그 `key`로 `triage.py run`을 부른다.

### 3-4. GitHub 작업 키 설계(경로 안전)
- 작업 키는 `<owner>.<repo>-<N>`이고 전부 소문자다.
  - GitHub owner에는 `.`가 올 수 없으므로 분해가 유일하다: 끝의 `-\d+`를 뗀 뒤 첫 `.`에서 나눈다.
  - `/`·`#`·공백이 없으니 디렉토리·파일 이름·git ref로 쓸 수 있다. `(?!.*\.\.)`로 ref 금지 형태(`..`)를 막는다.
  - repo 이름이 `.`로 시작하면(`.github`) 지원하지 않는다고 18장에 적는다.
- jira `safe_key_re`에는 `.`가 없고 github 키에는 늘 `.`가 있으므로 둘은 겹치지 않는다.
- 소문자 정규화 이유: GitHub owner·repo는 대소문자를 구별하지 않는다. Windows 파일시스템에서 중복이 생기는 것을 막는다.
- `key_from_args`:
  - owner는 `^[A-Za-z0-9][A-Za-z0-9-]{0,38}$`, repo는 `^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$`이면서 `..`가 없어야 한다.
  - `issue_number`는 bool이 아닌 int이고 1 이상이어야 한다. 문자열과 실수는 거부한다.
  - 소문자 키를 만든 뒤 `key_args(key)`를 다시 만들어 소문자 비교로 입력과 같을 때만(왕복) 키를 낸다.
- DB `tracker.key_regex`로 팀 레포를 제한한다(예: `mock-org\.mock-issues-\d+`).

### 3-5. 공통 경로 안전 패턴(스키마용)
스키마 패턴은 두 어댑터를 모두 덮는 §1-A 합집합을 쓴다. 정확한 형식은 db_lint가 DB kind의 `safe_key_re`와 `key_regex`로 검사한다. **런타임의 경로 판정(guard·issuepost·bridge)은 항상 어댑터 `safe_key_re`를 쓴다.**

### 3-6. issuepost 일반화 (`common/issuepost.py`)
- `SPEC_PATH`를 `("tracker","write_tools","add_comment")`로 바꾼다(`:30`). `jira_prefixes`는 `tracker_prefixes`로 바꾼다(내부 이름 변경은 선택).
- `spec_check`(`:209`):
  - `trackers.of(cfg)`의 `formats`·`default_format`·`spec_problems`를 쓴다.
  - 공통 검사는 그대로 둔다: 서버 소속, `COMMENT_WORDS`·`FORBIDDEN_WORDS`, read_tools 포함이면 fail, extra_args 겹침 금지(`:236-266`).
  - 반환 spec에 `"kind"`를 넣는다.
- `call_arguments`(`:272`): `{**adapter.key_args(spec,key), body_arg: normalize_body(body), **extra}`.
- `check_call`(`:301`):
  - 허용 인자 = `adapter.arg_names(spec) ∪ {body_arg} ∪ extra`.
  - `key = adapter.key_from_args(spec, tool_input)`이 None이거나 `safe_key_re`에 맞지 않으면 "이슈 키 형식 불일치".
  - `record.key_arg == adapter.key_arg_id(spec)`.
  - 나머지 대조(도구, sha, `post.md` 글자 일치, 30분 만료, 1회용, unknown 거부)는 **그대로 둔다**.
- `KEY_SAFE_RE` 상수는 `trackers.jira.SPEC.safe_key_re`의 별칭으로 남겨도 된다. 호출부는 `safe_key(cfg)`를 쓴다.
- `issue_post.py`:
  - approve 기록(`:627`)의 `"key_arg": adapter.key_arg_id(spec)`. jira는 기존 값과 같다.
  - render의 `PROBLEM` 첫 줄(`:304`) `f"Jira: {job.key}"`는 `f"{adapter.label}: {adapter.display(job.key)}"`로 바꾸고, tail(`:354`)의 "Jira·로그 원문"은 `f"{adapter.label}·로그 원문"`으로 바꾼다. 게시 본문은 그 트래커에 올라가는 글이므로 라벨이 맞아야 한다. jira는 바이트가 같다.

## 4. Jira 전용 가정 제거 지점(전수)

1. **키 정규식 기본값이 4곳에 중복**돼 있다: `jira_fields.py:50`, `issue_post.py:55`, `db_search.py:204`, `dbadd/applier.py:45`. 모두 `trackers.get(db_kind).default_key_regex`로 모은다. `bridge._key_regex`(`:98-104`)도 같다.
2. **경로 안전 키**: `issuepost.py:41,317`, `guard.py:411`(`has_record`), `jira_bridge.py:140,227`, `issue_post.py:96`을 어댑터 `safe_key_re`와 `key_from_args`로 바꾼다.
3. **guard 규칙 2**(`guard.py:367-396`):
   - 순서와 구조는 그대로 둔다: (a) 코멘트 도구 → 승인 대조, (b) 설정 서버 접두사(`tracker.mcp_server` ∪ `tracker.tools` 서버) → read_tools 허용 목록 밖이면 거부, (c) 설정 서버가 비면 경고, (d) 이름 휴리스틱, (e) 규칙 11.
   - (d) `if "jira" in srv.lower() or "atlassian" in srv.lower()`(`:392`)는 `any(w in srv.lower() for w in trackers.all_server_words())`로 바꾼다. kind와 무관한 합집합이므로 jira 설치의 판정은 같고, github 설치에서도 Jira·Atlassian 서버 쓰기는 거부된다(더 엄격).
   - github의 `server_words`를 비우는 이유: "github"를 넣으면 설정되지 않은 모든 GitHub MCP 쓰기가 거부된다. 그러면 규칙 11(이슈 DB 대상 ask)과 충돌하고 범위가 지나치다. 설정된 github 트래커 서버는 (b)가 덮는다.
   - 앞에 legacy·kind 오류 관문을 더한다(§2-2).
   - 메시지 문구 "Jira"는 그대로 둔다(1-G).
   - **강도 확인**: 설정 서버의 비허용 도구 거부, 승인 코멘트 1종 예외, 인자 집합·키·도구·sha·만료·1회용 대조, `post.*.json` 직접 쓰기 거부(`:454-456,1415`)가 모두 그대로다.
   - **알려진 효과(S30)**: GitHub 트래커가 일반 GitHub MCP 서버와 같은 등록이면 그 서버의 read_tools 밖 도구(코드 읽기, PR 생성 포함)가 모두 거부된다. 규칙 2가 (e)보다 먼저 돌기 때문이다. 권장은 트래커 전용 MCP 등록(issues toolset만)이다.
4. **jira_bridge**:
   - `target`(`:115-123`)은 `adapter.read_action`을 쓴다. github에서 `"unsupported"`이면(매핑된 도구인데 method가 다름) 원문을 대체하고 "지원하지 않는 읽기"라고 알린다(fail-closed, 더 엄격).
   - `bridge`(`:180-216`): 키는 `adapter.key_from_read`로 얻는다. get_issue 저장 시 `raw.setdefault("key", key)`를 더한다(jira 응답에는 key가 있으므로 변화 없음). 파일 이름은 `issue_raw.json`.
   - `bridge_post`·`mark_unknown`(`:139,226`)의 키는 `key_from_args`로 얻는다.
   - `COMMENT_ID_KEYS`(`:55`)는 공용으로 유지한다. GitHub 응답의 `id`도 덮는다.
5. **jira_fields**:
   - `STRUCTURED`(`:51`)에서 `android_version`을 `platform_version`으로 바꾼다.
   - `TEXT_DEFAULTS`와 components 기본값은 어댑터 값을 쓴다.
   - `tracker.timezone`은 계속 필수다.
   - **GitHub에 `occurred_at` 기본값(`created_at`)을 두지 않는다**. 생성 시각은 발생 시각이 아니고, 앵커가 조용히 틀어진다. `missing`으로 두면 기존 흐름이 묻는다(T8).
   - `check-key`: `parse_key`로 정규화하고 kind를 대조한다(§3-3).
6. **필드 매핑 기본값**: jira는 `{}`(현재와 같음). github도 `{}`이고 텍스트 기본값만 다르다. 모델·SW·버전은 `missing`이 되어 사용자에게 묻는다(S31).
7. **issue_post**: §3-6.
8. **db_add `jira` op**(`dbadd/ops/jira.py`): 폴더 `issues`, 필드 `platform_version`, reject 코드 개명, 키 검사 `self.key_re`(`applier.py:45`, DB `tracker.key_regex`)에 어댑터 `safe_key_re` 검사를 더한다. 중복 판정은 `p.stem` 기준(`core.py:170,197`)으로 유지한다. 파일 이름이 곧 작업 키다.
9. **db_lint**: `_check_jira`(`:749-778`)는 폴더 `issues`, 코드 개명, `safe_key_re`, `tracker.kind` 검사로 바꾼다. `_check_evidence`(`:636-647`)는 폴더 경로만 바꾼다. 중복 검사(`duplicate-issue`)는 stem 기준 그대로다.
10. **db_build**: `link`(`:116`)는 `adapter(db_kind).link`를 쓴다(jira 바이트 동일). `{base_rel}jira/`는 `issues/`로, `inline_max` 키도 바꾼다. 표 머리 "Jira"는 그대로 둔다.
11. **db_search**: 질의 키 판별 전에 `adapter(db_kind).parse_key(query)`를 거친다(jira는 그대로).
12. **driver**:
    - `jira_tool`(`:103`)은 `tracker.tools`를 쓴다.
    - NeedsInput `"issue"`(`:344`)에 `read_args`가 None이 아닐 때만 `tool_args`·`comments_args`를 더한다(jira 출력 불변).
    - 오류 문구의 `jira.tools.get_issue`(`:133`)는 키 이름이므로 `tracker.tools.get_issue`로 바꾼다.
13. **mcptools**: `classify`(`:93-106`) 뒤에 `adapter.classify_extra`를 적용한다(`config.py tracker-candidates` 경로). `WRITE_WORDS` 등은 그대로 둔다.
14. **lock 키**: lock은 플랫폼 work_dir 단위라 이슈 키와 무관하다(`17-platforms.md §3`). 작업 키가 들어가는 곳(JOB 디렉토리, `tt/<KEY>` 브랜치, 피드백 파일 이름)은 2번의 `safe_key_re`로 보장한다. 바꿀 것이 없다.

## 5. 바이트 동일 검증 방법

W에 `rename_compare.py`를 일회성 도구로 둔다(레포에 넣지 않는다). 기준 트리는 `git worktree add W/base fdf3ced`이고, 새 트리는 작업 트리다. 사례마다 양쪽을 실행한다.
- 옛 쪽은 옛 CLI·옛 샘플 DB·`jira:` config, 새 쪽은 새 CLI·변환된 샘플·`tracker:` config를 쓴다.
- 임시 `TELEPHONY_TRIAGE_HOME`과 `make_plugin_root`류 헬퍼를 양쪽에 따로 쓴다.

**사례**
- C1 `db_regress --all`(23/23)
- C2 `db_lint --all`
- C3 `db_build --write`를 임시 사본에 실행해 README·카테고리 README·STATS·CHANGELOG 비교
- C4 `db_search`: `MOCK-1101`, `DATA-001`, `DATA-001-01`, 키워드 2개, `--format markdown`
- C5 `jira_fields extract`: `tests/mocks/jira/*.yaml` 9건 × `--origin file`, `--meta-out`
- C6 `triage run --dry-run --issue-file`(옛 쪽은 `--jira-file`): `test_triage`가 쓰는 시나리오 3~4개. 비교 대상은 `analysis.json`, `report.md`, `match.json`, `events.json`, `issue.json`, `issue_meta.json`, `plan.json`
- C7 `triage --offline-db --issue-meta`(offline_eval 경로)
- C8 C6 결과로 `issue_post render`: `post.md` 바이트, `post.render.json`
- C9 `match_signatures --issue-meta`
- C10 `config.py show`·`doctor --format json`
- C11 **guard 판정 행렬**. 고정 hook 입력 약 20개를 옛 config와 새 config로 각각 돌려 결정(allow/ask/deny)과 사유 문구를 비교한다.
  - mock-jira 읽기, 비허용 읽기, 쓰기
  - 승인 코멘트: 정상, sha 불일치, 만료, 1회용, 범위 밖 인자
  - `probe-jira`·`x-atlassian` 서버 쓰기
  - github 이슈 DB 대상 쓰기·머지
  - `post.approved.json` Write
  - 설정 없음
- C12 golden(`test_golden.py`)은 변경이 없어야 한다.

**정규화**는 옛 출력에만 적용한다. 허용 차이는 아래 표 하나뿐이고, 표를 출력해 §1과 같음을 사람이 확인한다.
1. JSON 키 재귀 개명:
   - `jira→issue`, `jira_count→issue_count`, `jira_recent→issue_recent`, `jira_latest→issue_latest`, `jira_gap_min→issue_gap_min`, `jira_in_main→issue_in_main`, `jira_done→issue_done`, `jira_origin→issue_origin`, `android_version→platform_version`, `android_versions→platform_versions`.
   - db_search 결과의 `jira` 목록은 `issues`로 바꾼다(사례별 덮어쓰기).
   - config 출력의 최상위 `jira`는 `tracker`로 바꾸고 `kind: jira`를 더한다(C10).
2. 열거 값 개명. 키 경로를 지정해서만 바꾼다:
   - `step_anchor.source`, `needs_input.kind`, `results[].kind`: `"jira"→"issue"`
   - `logcat.year_source`: `"jira"→"tracker"`
   - lint·reject 코드, doctor 행 이름, db_review 항목 id, quality 출처 접두어 `jira:`
3. 경로 문자열: 경로로 보이는 문자열 값(`/` 포함 또는 `.json`·`.yaml`로 끝남)과 Markdown 링크 대상에만 적용한다. `/jira/→/issues/`, `jira_raw.json→issue_raw.json`, `jira.json→issue.json`, `jira_meta.json→issue_meta.json`, `jira.schema.json→issue.schema.json`.
4. 휘발 값 가리기:
   - `request_hash`와 `parts`(plugin·config·issue 해시는 이름 변경으로 반드시 바뀐다), `generated_at`, `run` id, 임시 경로 접두어 → `<TMP>`.
   - 대신 재사용 동작(같은 입력 2회 실행 시 `reuse.hit`)을 C6에서 따로 확인한다.
5. 비교: JSON은 `sort_keys` 정규 덤프 후 바이트 비교, 텍스트는 3만 적용한 뒤 바이트 비교한다.
6. 역검사: 새 출력 안에 `jira`가 든 **키**가 남으면 실패다(허용 목록 없음). 값 안의 사람용 문구 "Jira"는 허용한다.
7. 결과는 사례별 PASS/FAIL과 diff 앞 40줄이다. 한 건이라도 FAIL이면 그 묶음은 끝나지 않은 것이다.

묶음 1 끝(이름 변경), 묶음 2 끝(어댑터 도입, jira 동작 불변)에 각각 실행한다. 묶음 2에서는 기준을 묶음 1 결과로 두고 **정규화 없이** 바이트 동일이어야 한다. 예외는 휘발 값과 C11 사유 문구 중 `trackers` 관련이 없는 것이다.

## 6. 모의 GitHub Issues MCP·eval

### 6-1. 모의 서버 `tests/mocks/github_issues_mcp/{server.py, call.py}`
- 서버 이름은 `mock-github-issues`다. `mock-jira`(`tests/mocks/jira_mcp/server.py`)와 같은 stdio JSON-RPC 구조를 쓰고 SDK는 쓰지 않는다.
- 도구 이름과 인자는 **실제 GitHub MCP와 같은 표준 이름**을 쓴다. 어댑터의 고정 키 인자를 검증하기 위해서다.
  - `issue_read {method: get|get_comments|get_labels, owner, repo, issue_number:number}`
  - `search_issues {query, owner?, repo?}`
  - `add_issue_comment {owner, repo, issue_number, body, reaction?, comment_id?}`: 승인 게시용. 응답은 `{"id": <n>, "html_url": …}`
  - guard 시험용 쓰기 도구 `update_issue`, `create_pull_request {owner, repo, …}`: 쓰기 로그만 남긴다.
- 데이터는 `tests/mocks/github_issues/<owner>.<repo>-<n>.yaml`이다(합성, `mock-org/mock-issues`, 호스트 `ghe.mock.invalid`). `title`, `body`, `labels`, `created_at`, `comments[].body`를 담고 2~3건이다.
- 환경변수 `MOCK_GH_ISSUES_DIR`, `MOCK_GH_ISSUES_WRITE_LOG`.
- `tests/mocks/mcp.json`에 서버를 추가한다.
- `site-defaults.example.yaml`에 github 예시를 주석으로 둔다. 활성 예시는 jira 그대로다.
- 테스트 헬퍼에 github용 site-defaults 덮어쓰기 함수를 둔다: `tracker: {kind: github, mcp_server: mock-github-issues, tools: {get_issue, get_comments: …__issue_read, search_issues}, read_tools, write_tools.add_comment {tool: …__add_issue_comment, body_arg: body, format: markdown}, timezone, field_map: {}}`.
- 변형 DB `issue-db-github`(`make_variant_dbs.py`): 샘플 복사, `tracker {kind: github, base_url: https://ghe.mock.invalid/, key_regex: 'mock-org\.mock-issues-\d+'}`, 기록 2건 `mock-org.mock-issues-101.yaml` 등. feedback 키도 바꾼다.

### 6-2. 새 테스트
- `tests/test_trackers.py`
  - 레지스트리: known, get 오류, 계층(표준 라이브러리만)
  - parse_key·display·link·key_args·key_from_args 왕복
  - 음성 사례: `../x-1`, `a..b-1`, `/`, `#`, 공백, owner에 `.`, issue_number가 `"12"`·`12.0`·`True`·`0`
  - 대소문자 정규화
  - jira·github 키 형식이 겹치지 않음
- `test_hooks.py`(github)
  - 설정 서버의 `update_issue`·`create_pull_request` deny(규칙 2가 11보다 먼저)
  - read_tools의 `issue_read` allow
  - 승인 코멘트 ask
  - issue_number 불일치·문자열, `reaction` 인자 → deny
  - kind=github에서도 `x-jira` 서버 쓰기 deny
  - legacy `jira:` 또는 unknown kind → 모든 mcp deny
- bridge: get·get_comments 합치기, unsupported method 대체, 키가 정규식 밖이면 저장 안 함, legacy면 전부 대체.
- `test_issue_post.py`(github): markdown 렌더, approve `arguments`(`issue_number` int), "GitHub: mock-org/mock-issues#12" 머리.
- `test_db_lint`·`test_db_build`(github 변형): 링크 `…/mock-org/mock-issues/issues/101`, `issue-key`, kind 오류.
- `test_config_setup`: legacy 감지, `set-tracker`, `tracker-candidates`(github `classify_extra`).
- `tracker-mismatch`: 세션 github × jira DB → check-key 종료 2.
- `test_mocks.py`: github 모의 서버 왕복.

### 6-3. 두 번째 트래커 eval (`tests/skill_evals/evals.json` 66·67)
`skill_eval_env.py` setup에 `tracker: github`과 `gh_issues: [키]`를 더하고(`:177-211,306-329` 확장), `MOCK_GH_*`를 export한다.
- **66 GitHub analyze 쓰기**
  - 프롬프트: "https://ghe.mock.invalid/mock-org/mock-issues/issues/12 분석해서 기록해줘"(모델·SW·버전은 프롬프트에 제공).
  - 자동 채점:
    - check-key로 정규화했다.
    - `issue_read` get·get_comments를 호출했다.
    - `issue_raw.json`을 소비했다(남지 않음).
    - transcript에 이슈 body 원문 미노출.
    - 계획 `issue.key == "mock-org.mock-issues-12"`, `issue.origin == "mcp"`.
    - PR 브랜치의 `data/…/issues/mock-org.mock-issues-12.yaml`.
    - GitHub 쓰기 도구 0건, lock 해제.
- **67 GitHub 승인 코멘트 게시**(eval 61의 GitHub판)
  - render(markdown) → 승인 → approve 다음에 `add_issue_comment` 정확히 1건.
  - 인자 `{owner: mock-org, repo: mock-issues, issue_number: 12, body}`, 본문이 `post.md`와 같다.
  - 다른 쓰기 시도 0건, 권한 확인 1회.
- `grade.py` 일반화:
  - `JIRA_POST_EVALS`(`:36`)를 `POST_EVALS = {61: ("jira","MOCK-1001","jira_ticket_add_note"), 67: ("github","mock-org.mock-issues-12","add_issue_comment")}`로 바꾼다.
  - `jira_writes`·`jira_post_ok`(`:359-376`)는 트래커별 쓰기 로그를 고른다.
  - 공통 행 문구 `JIRA_NO_WRITE_TEXT`는 jira eval에 그대로 쓰고, github eval에는 "트래커(GitHub) 쓰기 도구를 부르지 않았다"를 쓴다. 기존 eval 채점 문구는 바꾸지 않는다.
- 기존 eval·grade 갱신(묶음 1):
  - grade.py의 경로(`/jira/`→`/issues/`, §1-A 줄 목록), `plan(...).get("jira")`→`"issue"`(`:551,626,788,813`), `analysis(...).get("jira")`→`"issue"`(`:808,812`), `jira_raw`→`issue_raw`(`:234-245,292,555,758`), doctor 행 정규식 `\|\s*jira\s*\|`→`tracker`(`:646`), `history.jira`(`:1093`)→`history.issue`.
  - `evals.json` 기대 문구 중 파일 경로·키·옵션(`--jira-file` 등)만 바꾼다. 프롬프트의 "Jira"는 그대로 둔다.
  - `tests/test_skill_evals.py`(42곳)를 함께 갱신한다.
- 측정은 결정 (g)대로 한다: 변경 전·후 같은 모델로, 다음 eval을 묶음 3 끝에 메인이 돌린다.
  - 영향이 큰 기존 eval: 8, 14, 39, 47, 61, 63
  - 새 eval: 66, 67
  - 1순위 동작, 2순위 토큰 W0 폭

## 7. 단계 분할

### 묶음 1 — 형식 이름 변경(L)
동작 변경 없이 §1 전부와 §2-2(legacy 감지·관문)를 한다. `tracker.kind`는 받기만 하고 쓰지 않는다(jira 고정).

| 파일 | 수정량 |
|---|---|
| 스키마 `plugin/schemas/{jira→issue,plan,type,feedback}.schema.json`, `output/analysis.schema.json` + `sync_schemas` | M |
| `common/userconfig.py`(builtin·from_site_defaults·legacy_problems) | S |
| `config.py` | M |
| `site-defaults.example.yaml` | S |
| `common/issuedb.py`, `common/compiled.py` | S |
| `common/issuepost.py`(SPEC_PATH 등) | S |
| `common/quality.py`, `common/failedstep.py`, `common/mcptools.py` | S |
| `guard.py`(키 경로, RAW_NAMES, legacy 관문) | S |
| `jira_bridge.py`, `jira_fields.py` | S |
| `triage.py`, `triagelib/{driver,anchor,cache,core,report}.py` | M |
| `match_signatures.py`, `db_search.py` | M |
| `db_summary.py`, `db_review.py`, `db_build.py`, `db_lint.py` | S~M |
| `db_pr.py`, `dbpr/publish.py`, `dbadd/{core,applier,drift}.py`, `dbadd/ops/{jira,fix,resolution,entities}.py` | S~M |
| `code_roots.py`, `issue_post.py`, `platforms/session.py`(관문) | S |
| `tools/{offline_eval,bench_scale,make_bundle,make_db_skeleton}.py` | S |
| 샘플 DB 변환·README 재생성, `make_variant_dbs.py`, `tests/fixtures/plans/*`, `skill_evals/plans/*`, `fixtures/migrations/0001_*`, `tests/helpers/{workspace,skill_eval_env}.py`, `tests/mocks/skills/data-analyzer` | M |
| 테스트: `test_triage`, `test_config_setup`, `test_hooks`, `test_db_search`, `test_step_anchor`, `test_issue_post`, `test_jira_fields`, `test_db_pr`, `test_db_build`, `test_sample_db`, `test_match_signatures`, `test_failed_step`, `test_platform_guard`, `test_step_order`, `test_db_summary`, `test_triage_analysis_only`, `test_db_lint`, `test_db_review`, `test_db_migrate`, `test_triage_reuse`, `test_masking`, `test_platform_select`, `test_android_identity`, `test_db_verify`, `test_ofono_skeleton`, `test_code_roots`, `test_skill_evals`, `test_mocks` | L |
| `skill_evals/{grade.py,evals.json,run.py,README.md}` | M |
| `gen_contracts.py --write`(contracts-cli.md) | 생성 |

검증:
- §5 C1~C12 PASS, db_regress 23/23.
- `related_tests.py`로 고른 테스트.
- 레포 전체에서 `git grep -n -E "jira_(raw|meta|key_regex|base_url|inline_max|done|count|recent|latest)|--jira-|set-jira|jira-candidates|/jira/|\"jira\"|android_versions?\b"`를 돌려 남은 줄이 1-G 허용 범위인지 확인(`docs/history` 제외).
- `check_boundary --mode external`.

### 묶음 2 — 트래커 레지스트리 + Jira 어댑터(M)
§3, §4의 jira 측 일반화와 `tracker-mismatch`를 한다.

| 파일 | 수정량 |
|---|---|
| 신규 `trackers/{__init__,base,jira}.py` | M |
| `common/issuepost.py`(spec_check·call_arguments·check_call 위임) | M |
| `guard.py`(규칙 2 휴리스틱 합집합, kind 오류 관문) | S |
| `jira_bridge.py`(read_action·key_from_read·key_from_args) | S~M |
| `jira_fields.py`(text_defaults·check-key 정규화·mismatch) | S |
| `issue_post.py`(라벨·display·key_arg_id·mismatch) | S |
| `db_build.py`(link), `db_lint.py`(kind·safe_key), `db_search.py`(parse_key), `dbadd/applier.py`·`ops/jira.py`(safe_key·기본 정규식) | S |
| `triagelib/driver.py`(read_args 조건부) | S |
| `common/mcptools.py`·`config.py`(classify_extra) | S |
| 테스트 `test_trackers.py`(jira 부분), 계층 테스트 | M |

검증:
- 묶음 1 결과를 기준으로 C1~C12가 **정규화 없이** 바이트 동일(§5 끝).
- guard 행렬 동일, `test_hooks`·`test_issue_post` 통과.

### 묶음 3 — GitHub 어댑터·모의 MCP·eval·문서(L)

| 파일 | 수정량 |
|---|---|
| `trackers/github.py` | M |
| `tests/mocks/github_issues_mcp/*`, `tests/mocks/github_issues/*`, `mcp.json` | M |
| `make_variant_dbs.py`(github 변형), 헬퍼 덮어쓰기 함수 | S |
| §6-2 테스트 | M~L |
| `skill_eval_env.py`, `grade.py`, `evals.json` 66·67 | M |
| `tools/make_db_skeleton.py --tracker <kind>` | S |
| 문서 §8 | L |

검증: 새 테스트, eval 66·67(+ §6-3 기존 eval), `list_site_todos`(S30~S32 반영 확인), `check_boundary`.

## 8. 문서 변경 목록

- **새 `docs/design/18-trackers.md`가 필요하다**(17-platforms와 같은 틀). 담을 것:
  - 머리말: jira 설치는 바이트 불변, 예외는 legacy 감지와 휴리스틱 합집합.
  - §1 계약(레지스트리·TrackerSpec 표·계층 규칙)
  - §2 설정 층(site `tracker.*`, 사용자 `tracker.*`, DB `tracker.{kind,base_url,key_regex}`)
  - §3 작업 키·경로 안전·GitHub 키 인코딩
  - §4 `tracker-mismatch`
  - §5 guard 규칙 2 일반화와 전용 MCP 등록 권고
  - §6 새 트래커 추가 체크리스트
  - §7 결정 기록:
    - T1 레지스트리 패턴
    - T2 경로 안전 작업 키·GitHub `<owner>.<repo>-<N>`
    - T3 DB kind 선언·mismatch 거부
    - T4 원칙 (d), 버전 올림 없음
    - T5 legacy 감지만(fail-closed), 자동 변환 없음
    - T6 휴리스틱 합집합, github 단어 없음
    - T7 사람용 문구 "Jira" 유지, 게시 본문 머리만 라벨
    - T8 GitHub `occurred_at` 기본값 없음
    - T9 트래커는 플랫폼끼리 공유(S28·S32)
    - T10 출력 키 전부 개명
  - §8 미룬 것: 리포트 라벨 일반화, 이슈 본문(이슈 폼)에서 구조화 필드 추출, 플랫폼별 트래커, GitHub 검색 결과 bridge 격리(Jira search와 같은 수준)
- `docs/design/README.md`: 18장 행 추가, 14-site 범위 "S1~S32".
- `contracts.md`(44곳): 작업 키 검증, 출력 키, lint·reject 코드, `--issue-*`, 상태 값의 `issue`.
- `contracts-cli.md`: 생성.
- `02-config.md`: `tracker` 블록, DB `tracker`, `year_source`, `code_profiles.platform_version`, legacy.
- `03-issue-db.md`: `issues/`, `issue.schema.json`, 필드 개명.
- `07-workflow.md`: Step 0·2·9 파일·옵션.
- `08-safety.md §9`: 규칙 2·10 문구, RAW_NAMES.
- `01`, `06 §6.3`(issue 중복 정리)·`§6.4`(예시 문구), `09`, `10`(eval 66·67), `11`, `12-principles.md`(`jira.write_tools.add_comment` → `tracker.write_tools.add_comment`, "Jira 한 건은 파일 하나" → "이슈 한 건"), `14-site.md`(S16·S17·S20·S22·S23의 키 이름 + S30~S32 행), `15`, `16 §16.1·16.5`(`issue_summary`), `17-platforms.md`(K9 해소, §8의 "스키마 필드 개명" 항목 삭제), `99-deferred`.
- `CLAUDE.md`: "Jira는 읽기와…" 문장은 유지하고, 필요하면 "트래커(Jira 등)"로 바꾼다. ≤4KB 확인.
- `GUIDE.md`, `README.md`, `DRAFT_NOTES.md`(결정 (n) 한 줄, 진행 상태).
- 플러그인 문서: `SKILL.md`, `reference/{record,post,write-flow,search,verify,db-authoring,explore,rules}.md`(skill-creator 관례), `commands/{setup,help,analyze,record,review,search,sync,verify-fix}.md`.
- 샘플 DB 문서: `CONTRIBUTING.md`, `docs/getting-started.md`, `docs/review-guide.md`.
- `tests/fixtures/README.md`, `tests/skill_evals/README.md`.

**HTML 영향**(직접 고치지 않는다. 각 묶음이 `W/html-impacts.md`에 "묶음 | 바뀐 사실 | 영향 받을 HTML 파일·키워드"로 덧붙인다):

| 묶음 | 바뀐 사실 | 영향 HTML·키워드 |
|---|---|---|
| 1 | 이슈 DB `jira/` → `issues/`, `jira.schema.json` → `issue.schema.json`, `templates/issue.yaml` | 03-manual, 04-design, 06-contributor-guide, 05-admin-runbook, telephony-triage-guide: 디렉토리 구조 그림 |
| 1 | 설정 `jira:` → `tracker:`(+`kind`), `set-jira` → `set-tracker`, `jira-candidates` → `tracker-candidates`, doctor 행 `tracker`·`tracker_post` | 03-manual, 05-admin-runbook, 07-user-guide, 15-quick-ref, guide: setup·doctor 표 |
| 1 | `--jira-file/raw/meta` → `--issue-*`, 작업 파일 `issue*.json` | 03-manual, 15-quick-ref, 12-pilot-eval(offline_eval) |
| 1 | `android_version(s)` → `platform_version(s)` | 04-design, 06-contributor-guide, 17-glossary |
| 1 | lint 코드 `duplicate-issue`·`issue-key`·`issue-cause` | 06-contributor-guide, 18-review-qa |
| 2 | guard 규칙 2: 이름 휴리스틱이 설치된 트래커 단어 합집합, 옛 `jira:` 키나 모르는 kind면 모든 MCP 거부, `tracker-mismatch` | 13-security, 04-design, guide 보안 규칙 표 |
| 3 | GitHub Issues 트래커 지원(모의), 전용 MCP 등록 권고, 게시 본문 markdown | 00-index, 01-training-deck, 02-marketing, 08-limitations, 09-ideas, 11-decisions, 14-exec-summary, 16-roadmap, 19-team-intro |

## 9. 위험·사내 확인 항목

`14-site.md §14.2`에 추가할 행:
- **S30** GitHub Issues를 트래커로 쓸지, 쓴다면 MCP 등록.
  - 확인할 것: 전용 등록인지(issues toolset만), 도구 전체 이름, 인자 이름(`issue_read`의 `method/owner/repo/issue_number`, `add_issue_comment`), 응답 형식(comment id, `isError`), GHE 호스트, repo 이름 규칙(`.`로 시작하는 repo 없음).
  - 영향: `tracker.*`, `trackers/github.py`. 트래커 서버가 일반 GitHub MCP와 같은 등록이면 규칙 2가 그 서버의 비허용 도구를 모두 거부한다.
- **S31** GitHub 이슈의 구조화 필드(모델·SW·플랫폼 버전·발생 시각·슬롯) 위치.
  - 후보: 이슈 폼 본문, 라벨, Projects 필드. `field_map` JSON 경로로 얻을 수 없으면 사용자 질문으로 둔다. 본문 추출은 미룬다.
- **S32** 플랫폼마다 트래커나 프로젝트가 다른지(S28과 함께). 다르면 `platforms.<p>.tracker` 덮어쓰기(`PROFILE_KEYS` 확장)를 다음 작업으로 한다.
- 기존 행 S16·S17·S20·S22·S23의 키 이름 표기를 갱신한다.

위험:
- R1. 묶음 1의 변경량이 크다(테스트 약 30파일). 대응: §5 비교와 grep 잔여 검사를 완료 기준으로 둔다. 기계 치환은 키 위치에만 하고 문구는 사람이 고른다.
- R2. 원칙 (d) 채택은 TRACKER 문구와 다르다. 메인이 사용자 확인을 받는다(§0).
- R3. legacy 감지가 사외 개발자의 기존 config를 즉시 막는다. 의도한 동작(fail-closed)이다. doctor hint와 GUIDE에 바꾸는 법을 적는다.
- R4. 승인 기록 `key_arg` 값이 github에서 `"owner,repo,issue_number"`가 된다. 기록은 30분 1회용 작업 파일이고 `schema: 1`은 유지한다. 옛 승인 기록은 render부터 다시 하면 된다.
- R5. GitHub `search_issues` 결과는 bridge가 격리하지 않는다. Jira `search_issues`와 같은 수준이고 18장 미룬 것에 적는다.
- R6. 우회 금지 확인: 승인·lock·버전 검사·플랫폼 대조는 건드리지 않는다. guard는 규칙 2 판정 순서·대조 항목을 그대로 두고 판정을 더할 뿐이다(legacy, kind 오류, `unsupported` 읽기는 모두 더 엄격한 쪽). 사내 정보는 쓰지 않는다(mock-org, ghe.mock.invalid만).

### Critical Files for Implementation
- /home/user/telephony-triage/plugin/scripts/common/issuepost.py
- /home/user/telephony-triage/plugin/scripts/guard.py
- /home/user/telephony-triage/plugin/scripts/jira_bridge.py
- /home/user/telephony-triage/plugin/scripts/jira_fields.py
- /home/user/telephony-triage/plugin/scripts/triagelib/driver.py
- /home/user/telephony-triage/plugin/schemas/plan.schema.json
- /home/user/telephony-triage/tests/skill_evals/grade.py