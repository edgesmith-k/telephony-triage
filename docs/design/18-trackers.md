# 18. 트래커 범용화 (Jira 기본 / GitHub Issues / 이후 추가)

> 10/11 사용자 요청. Jira 밖의 이슈 시스템(GitHub Issues 등)도 **설정으로** 쓸 수 있게 한다. 트래커는 계속 더할 수 있어야 한다(이름을 하드코딩하지 않는다). 표·정의가 다르면 `contracts.md`가 맞다(`§공통 규칙` 작업 키 검증·`tracker-mismatch`, `§기존 자산 연결 계약` 트래커 어댑터). 사내 고유 값은 쓰지 않는다(모의 값 `mock-org`·`ghe.mock.invalid`, `14-site.md` S30~S32).

**jira 설치는 이전과 바이트 단위로 같다**: 경로·작업 키·`analysis.json`·`report.md`·게시 본문(`post.md`)·`db_regress`·골든·guard 판정 문구. 예외는 셋이다.
- **옛 설정 키 감지**: 개명 전 키(`jira:` 등, §2)가 남아 있으면 자동 변환하지 않고 막는다(fail-closed). guard는 모든 MCP 호출을 거부한다.
- **guard 규칙 2 이름 휴리스틱**은 설치된 모든 트래커의 서버 단어 합집합이다(§5). 지금 단어는 jira·atlassian뿐이라 jira 설치의 판정은 같다.
- **승인 기록 `post.approved.json`에 트래커 `kind`가 더해진다.** guard가 지금 설정 트래커와 대조한다(§5). 30분 1회용 작업 파일이고 `schema: 1`은 그대로다.

driver(`triage.py run`)가 `check-key`의 정규화된 작업 키로 작업 디렉토리를 만드는 것(§3)도 jira에서는 입력 그대로라 출력이 같다. 형식 이름 변경(`jira/` → `issues/`, `jira.schema.json` → `issue.schema.json`, `android_version(s)` → `platform_version(s)`, 설정 `jira:` → `tracker:`, `--jira-*` → `--issue-*` 등)은 스키마 v1을 직접 고쳤다(T4, T10).

## 1. 계약 (`plugin/scripts/trackers/`)

```
trackers/
  __init__.py   # 레지스트리: known·get·kind_of·of·db_kind·of_db·mismatch·known_server_words·all_server_words. 트래커 이름을 모른다
  base.py       # 계약 타입: TrackerSpec(frozen dataclass, Callable 필드)·TrackerConfigError
  jira.py       # SPEC (이전 동작 그대로 옮김)
  github.py     # SPEC (GitHub Issues)
```

- 트래커 하나 = `trackers/<name>.py`의 `SPEC: TrackerSpec`. 플랫폼(`17-platforms.md §1`)과 같은 패턴이고, 규모가 작아 패키지가 아니라 모듈이다.
- 이름 `^[a-z][a-z0-9_]*$`, `base`·`_`로 시작하는 것 제외. `get(kind)`는 `importlib.import_module("trackers.<kind>")` → `SPEC` 타입과 `SPEC.name == kind` 확인 → 프로세스 안 캐시. 트래커 모듈의 SyntaxError·하위 의존성 누락·최상위 예외도 모두 `TrackerConfigError`로 감싼다(호출자는 한 길로 처리: 종료 2·MCP 거부).
- `kind_of(cfg)`·`of(cfg)`: 세션 설정(site-defaults + 사용자 config)의 `tracker.kind`, 없으면 `DEFAULT_KIND = "jira"`. `db_kind(db_cfg)`·`of_db(db_cfg)`: 이슈 DB `issue-db.config.yaml`의 `tracker.kind`, 없으면 jira. `mismatch(cfg, db_cfg)`: §4. `all_server_words()`: §5.

### 1-1. `TrackerSpec`

| 필드 | 뜻 | jira | github |
|---|---|---|---|
| `name`, `label` | 이름(`tracker.kind` 값), 게시 본문 머리 라벨 | `jira`, `Jira` | `github`, `GitHub` |
| `safe_key_re` | 작업 키 경로 안전 형식(작업 디렉토리·브랜치·피드백 파일·DB 기록 파일 이름) | `^[A-Za-z][A-Za-z0-9_]*-[0-9]+$` | `^(?!.*\.\.)[a-z0-9][a-z0-9-]{0,38}\.[a-z0-9_][a-z0-9_.-]{0,99}-[1-9][0-9]{0,9}$` |
| `default_key_regex` | DB `tracker.key_regex`가 없을 때 | `[A-Z][A-Z0-9]+-[0-9]+` | `safe_key_re` 본문 |
| `server_words` | guard 규칙 2 이름 휴리스틱 | `jira`, `atlassian` | 없음(§5) |
| `formats`, `default_format` | `common/issuepost.RENDERERS` 키 | `jira-wiki`·`markdown`, `jira-wiki` | `markdown`, `markdown` |
| `text_defaults`, `components_default` | `field_map`에 없을 때의 요약·설명·코멘트·컴포넌트 경로 | `fields.summary` 등, `fields.components[].name` | `title`·`body`·`comments[].body`, `labels[].name` |
| `parse_key(text)` | 사용자 입력 → 작업 키, 아니면 None | 경로 안전이면 그대로 | 작업 키·`owner/repo#N`·이슈 URL → 소문자 작업 키(§3) |
| `display(key)` | 본문·메시지 표시 | 그대로 | `owner/repo#N` |
| `link(base_url, key)` | README 링크 | `base_url + key` | `base_url + owner/repo/issues/N` |
| `spec_problems(raw)` | 코멘트 도구 설정의 트래커 전용 검사 | `key_arg` 필수 | `key_arg` 금지, `body_arg`가 키 인자와 겹치지 않음 |
| `key_args(spec, key)` | 쓰기 도구의 키 인자 | `{<key_arg>: key}` | `{owner, repo, issue_number: int}` |
| `key_from_args(spec, 입력)` | 도구 입력 → 작업 키 | `입력[key_arg]`가 경로 안전이면 | owner·repo·issue_number 검사 + 왕복 검사(§3) |
| `arg_names(spec)`, `key_arg_id(spec)` | 승인 범위 키 인자 집합, 승인 기록 `key_arg` 값 | `{key_arg}`, 설정 `key_arg` | `{owner, repo, issue_number}`, `owner,repo,issue_number` |
| `read_action(입력, mapped)` | jira_bridge 대상 판별 | mapped 안의 `get_issue` 우선 | `issue_read`의 `method` get → `get_issue`, get_comments → `get_comments`, 그 밖 `unsupported` |
| `key_from_read(응답, 입력, kre)` | 읽기 결과의 작업 키 | 응답 `key`·`issue.key`, 다음 입력 값 중 `kre`·`safe_key_re`에 맞는 첫 값 | 응답이 아니라 입력에서 `key_from_args({}, 입력)` → `kre` 검사 |
| `read_args(action, key)` | needs_input `issue`의 `tool_args`·`comments_args` | `None`(출력 불변) | `{method, owner, repo, issue_number}` |
| `classify_extra(tool, actions)` | `config.py tracker-candidates` 후보 보강 | 그대로 | `issue_read`가 `get_issue` 후보면 `get_comments`도 |
| `selftest_key` | doctor guard 자체 시험의 가짜 작업 키 | `SELFTEST-0` | `selftest.selftest-1` |

함수 필드의 `spec`은 `common/issuepost.spec_check`가 검증한 코멘트 도구 spec(`kind`·`key_arg`·`body_arg`·`extra_args`·`format`)이다. spec을 보지 않는 트래커(github)는 `{}`를 받아도 된다. 공통 검사(서버 소속, 코멘트·금지 단어, `read_tools` 포함 금지, `extra_args` 겹침)와 승인 대조(도구·sha·`post.md` 글자 일치·30분 만료·1회용·unknown 거부)는 issuepost에 그대로 있고, 키 인자 모양만 어댑터에 위임한다.

### 1-2. 계층 규칙 (테스트로 강제, `tests/test_trackers.py`)

- `trackers/*`는 표준 라이브러리와 `trackers.base`만 import한다. guard가 `common/issuepost`를 거쳐 불러오므로 가벼워야 한다. `common`·`platforms`·핵심 스크립트를 import하지 않고 트래커끼리도 import하지 않는다.
- 트래커 모듈(레지스트리 밖)은 동적 import·`exec`·`eval`을 쓰지 않는다.
- 핵심(guard·issuepost·jira_bridge·jira_fields·issue_post·db_*·config)은 레지스트리 경유로만 트래커를 쓴다(`trackers.jira` 직접 import 없음). 경로 판정은 늘 어댑터 `safe_key_re`다.

## 2. 설정 층

| 층 | 키 | 의미 |
|---|---|---|
| site-defaults | `tracker.kind`, `tracker.{mcp_server, exclude_servers, tools, read_tools, write_tools.add_comment, timezone, field_map, failed_step_patterns}` | 팀 트래커와 매핑(`02-config.md`). 하위 키는 트래커와 무관하게 같다. github 예시는 `site-defaults.example.yaml` 주석 블록 |
| 사용자 config | `tracker.*` | 개인 덮어쓰기(서버 이름·`read_tools` 등, setup의 `tracker-candidates`·`set-tracker`). 우선순위는 사용자 > site > 내장 |
| 이슈 DB | `issue-db.config.yaml` `tracker.{kind, base_url, key_regex}` | 그 DB의 트래커 선언, README 링크 기준, 기록 키 형식. `kind`가 없으면 jira(샘플 jira DB는 `kind: jira`를 적는다). 뼈대는 `tools/make_db_skeleton.py <out> --tracker <kind>` |

- github는 `write_tools.add_comment`에 `key_arg`를 두지 않는다(키 인자 고정). 본문 형식은 `markdown`만이다. `field_map`은 기본 `{}`라 모델·SW·플랫폼 버전·발생 시각은 `missing`이 되어 사용자에게 묻는다(T8, S31).
- **옛 설정 키**(`userconfig.legacy_problems`): site-defaults나 사용자 config의 최상위 `jira:`, `logcat.year_source: jira`, 프로필마다 `code_profiles[].android_version`, `field_map.android_version`. 감지하면 guard는 모든 `mcp__` 호출 거부, jira_bridge는 모든 `mcp__` 결과 대체, 스크립트는 종료 2, `config.py doctor`는 `tracker` 행 fail. 사용자 config는 `config.py rename-legacy [--apply]`로 바꾸고 site-defaults는 관리자가 고친다. `tracker.kind`가 잘못됐을 때(`TrackerConfigError`)도 처리가 같다.
- 옛 이슈 DB 키(`jira_key_regex`·`jira_base_url`·`readme.jira_inline_max`·`android_versions_supported`)와 `jira/` 폴더는 읽지 않는다. `db_lint`가 `config`·`legacy-dir` 오류를 낸다(원칙 (d), T4).
- 트래커 설정은 플랫폼끼리 공유한다(T9).

## 3. 작업 키·경로 안전·GitHub 키 인코딩

- **작업 키**는 그 트래커 `safe_key_re`에 맞는 문자열이다. 작업 디렉토리 `<work_dir>/<KEY>/`, PR 브랜치 `issue/<KEY>`(로컬 도구 브랜치 `tt/issue/<KEY>`), 피드백 파일 이름, DB 기록 `issues/<KEY>.yaml`이 된다. jira는 이슈 키 그대로다.
- **GitHub 인코딩 `<owner>.<repo>-<N>`**, 전부 소문자(예 `mock-org.mock-issues-12`).
  - GitHub owner에는 `.`가 올 수 없으므로 분해가 유일하다: 끝의 `-<N>`을 떼고 첫 `.`에서 나눈다.
  - `/`·`#`·공백이 없고 `(?!.*\.\.)`로 `..`를 막아 디렉토리·파일 이름·git ref로 쓸 수 있다. `.`로 시작하는 repo(`.github`)는 지원하지 않는다.
  - owner·repo는 대소문자를 구별하지 않으므로 소문자로 정규화한다(대소문자만 다른 디렉토리 중복 방지).
  - jira 작업 키에는 `.`가 없으므로 두 형식은 겹치지 않는다.
- **입력 정규화**: `jira_fields.py check-key <입력>`이 어댑터 `parse_key`로 작업 키를 만들어 출력 `key`로 낸다(못 하면 입력 그대로 내고 `valid: false`, 종료 1). github는 작업 키(대소문자 무관), `owner/repo#N`, `http(s)://<host>/owner/repo/issues/N`(끝 `/`·`?…`·`#…` 허용)을 받는다. 스킬은 출력 `key`로 이후 스크립트를 부른다. `triage.py run`(driver)은 입력 키를 직접 쓰지 않고 내부 `check-key`가 낸 작업 키로 작업 디렉토리·lock·브랜치·피드백 파일·출력 `key`를 만든다. `issue_post.py`도 `<KEY>`를 `parse_key`로 정규화한 뒤 검사한다.
- **도구 인자 → 작업 키**(`key_from_args`, github): owner `^[A-Za-z0-9][A-Za-z0-9-]{0,38}$`, repo `^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$`(`..` 없음), `issue_number`는 bool·문자열·실수가 아닌 1 이상 정수. 소문자 작업 키를 만든 뒤 `key_args`로 되돌려 입력과 소문자 비교로 같을 때만(왕복) 키를 낸다. guard·issuepost·jira_bridge는 이 키를 다시 `safe_key_re`로 본다.
- **DB 키 형식**: 기록 키는 DB `tracker.key_regex`와 DB 트래커의 `safe_key_re`를 모두 만족해야 한다(`db_lint` `issue-key`, `db_add` reject `issue-key`). 팀 DB는 `key_regex`로 레포를 좁힌다(예 `mock-org\.mock-issues-\d+`).
- **스키마 패턴**(`issue.schema.json` key, `feedback.schema.json` issue, `plan.schema.json` `$defs/issueKey`)은 두 어댑터를 덮는 합집합 `^(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9_.-]{0,140}-[0-9]{1,10}$`다. 정확한 형식은 위 검사가 본다.
- lock은 플랫폼 `work_dir` 단위라 이슈 키와 무관하다(`17-platforms.md §3`).

## 4. 이슈 DB 선언과 `tracker-mismatch`

- 세션 `tracker.kind`와 이슈 DB `tracker.kind`가 다르면 **거부**한다. 메시지 "tracker-mismatch — 이슈 DB 트래커는 <a>, 설정 tracker.kind는 <b>. …", 종료 코드 2. 키 공간·링크·도구 인자가 다른 DB에 기록하는 것은 의미가 없다(`platform-mismatch`와 같은 근거, T3).
- 대조 위치: `jira_fields.py check-key`·`extract`(DB를 찾았을 때 — 모든 흐름의 첫 관문), `issue_post.py`(스냅샷 선언, 없으면 사용자 clone, 둘 다 없으면 대조 불가로 종료 2). 세부는 `contracts.md §공통 규칙`.
- DB 선언이 설치된 트래커가 아니면 `db_lint` `config` 오류, `db_build`·`db_search`·`db_add`는 종료 2.
- DB에 고정된 도구(`db_lint`·`db_build`·`db_search`의 링크·질의 키 판별)는 DB 선언 트래커 어댑터(`of_db`)를 쓴다.

## 5. guard 규칙 2 일반화 (`08-safety.md §9`)

판정 순서(바꾸지 않고 앞에 관문만 더했다):
1. 옛 설정 키가 있으면 모든 `mcp__` 거부. 2. `tracker.kind` 오류면 모든 `mcp__` 거부.
3. 코멘트 도구(`tracker.write_tools.add_comment.tool`)면 승인 대조 → 맞으면 `ask`, 아니면 거부. 대조 항목: 인자 집합(어댑터 `arg_names` ∪ 본문 ∪ `extra_args`), 작업 키(`key_from_args` → `safe_key_re`), 도구, 승인 기록 `key_arg`(어댑터 `key_arg_id`)와 **`kind`(승인 기록의 트래커 = 지금 설정 트래커)**, 정규화 본문 sha256, `post.md` 글자 일치, 30분 만료, 1회용, 게시 이력·unknown.
4. 설정 서버(`tracker.mcp_server` ∪ `tracker.tools` 서버 접두사)의 도구는 `tracker.read_tools`에 없으면 거부.
5. 설정 서버가 비면 경고. 6. 이름 휴리스틱: 서버 이름에 `all_server_words()`의 단어가 들면 쓰기형 도구 거부. 7. 규칙 11(이슈 DB 대상 GitHub 쓰기 ask).

- `all_server_words()`는 설정 kind와 무관하게 **설치된 모든** 트래커 `server_words`의 합집합에 내장 `jira`·`atlassian`을 늘 더한다(트래커 하나가 깨져도 나머지는 쓰고, 레지스트리 실패에도 이전보다 약해지지 않는다). github 설치에서도 Jira·Atlassian 서버 쓰기는 거부된다(T6).
- github에 단어를 두지 않는 이유: "github"를 넣으면 설정되지 않은 모든 GitHub MCP 쓰기가 거부되어 규칙 11(이슈 DB 대상 ask)과 충돌하고 범위가 지나치다. 설정된 github 트래커 서버는 4번이 덮는다.
- jira_bridge(규칙 9): 읽기 판별은 `read_action`, 키는 `key_from_read`, 게시 결과의 키는 `key_from_args`. 매핑된 도구인데 지원하지 않는 읽기(github `method: get_labels` 등)·판별 예외는 `unsupported`로 원문을 대체한다(fail-closed). get_issue 원문은 `issue_raw.json`에 `key`를 채워 저장한다.
- 강도 확인: 설정 서버의 비허용 도구 거부, 승인 코멘트 1종 예외, 인자·키·도구·sha·만료·1회용 대조, `post.*.json` 직접 쓰기 거부는 그대로다. 더해진 판정(legacy, kind 오류, 승인 `kind` 대조, `unsupported` 읽기)은 모두 더 엄격한 쪽이다.

**전용 MCP 등록 권고 (S30)**: 4번이 규칙 11보다 먼저 돌기 때문에, GitHub 트래커 서버가 일반 GitHub MCP와 **같은 등록**이면 그 서버의 `read_tools` 밖 도구(코드 읽기·PR 생성 포함)가 모두 거부된다. 트래커용으로 issues toolset만 켠 **전용 등록**(별도 서버 이름)을 둔다. 이슈 DB PR은 `gh` CLI로 하므로 영향이 없다.

## 6. 새 트래커 추가 절차 (체크리스트)

1. `plugin/scripts/trackers/<kind>.py`에 `SPEC = TrackerSpec(...)`. 이름은 `^[a-z][a-z0-9_]*$`. import는 §1-2. 모르는 값은 `TODO(SITE:S<n>)`(`14-site.md §14.2`에 행 추가)와 placeholder로 둔다.
2. 작업 키: 경로 안전한 `safe_key_re`(`/`·`#`·공백·`..` 없음, ASCII만), 기존 트래커 형식과 겹치지 않음, `parse_key`·`display`·`link`. 스키마 합집합 패턴(§3)에 들어가지 않으면 스키마도 고친다(원칙 (d) 또는 마이그레이션).
3. 쓰기 도구 키 인자: `key_args`·`key_from_args`(왕복 검사)·`arg_names`·`key_arg_id`·`spec_problems`. 본문 형식이 새것이면 `common/issuepost.RENDERERS`에 함수를 더한다.
4. 읽기: `read_action`(모르는 입력은 `unsupported`)·`key_from_read`·`read_args`·`classify_extra`, `text_defaults`·`components_default`. 발생 시각 같은 구조화 필드에 추측 기본값을 두지 않는다(T8).
5. `server_words`: 그 트래커 전용 서버 이름에만 쓰이는 단어. 범용 이름(예: github)은 넣지 않는다(§5).
6. site-defaults: `site-defaults.example.yaml`에 주석 예시(`tracker.kind`·도구 매핑·`write_tools.add_comment`·`field_map`).
7. 이슈 DB: `issue-db.config.yaml` `tracker.{kind, base_url, key_regex}`. 뼈대는 `tools/make_db_skeleton.py <out> --tracker <kind>`.
8. 테스트: 모의 MCP 서버(`tests/mocks/<name>_mcp/`, 실제 도구 이름·인자, 합성 데이터), `tests/mocks/mcp.json` 등록, 변형 DB(`tests/helpers/make_variant_dbs.py`), `test_trackers`(parse·왕복·음성 사례·계층)·`test_hooks`(규칙 2)·`test_issue_post`·`test_db_lint`·`test_db_build`·`tracker-mismatch`, 스킬 eval(본보기 66·67), `tools/check_boundary.py --mode external`. jira 바이트 동일성(골든·`db_regress`·fixture)이 그대로인지 본다.
9. 문서: 이 문서 §7에 결정, `14-site.md`에 TODO(SITE) 행, `contracts.md §기존 자산 연결 계약`의 어댑터 값.

## 7. 결정 기록

| # | 결정 | 이유 |
|---|---|---|
| T1 | 레지스트리 = `trackers/<kind>.py`의 `SPEC` 하나, 이름으로 동적 import, 오류는 모두 `TrackerConfigError`. 표준 라이브러리만 | 플랫폼 K1과 같은 방식. guard가 불러오므로 가볍고 실패가 한 길이어야 한다 |
| T2 | 경로 안전 작업 키. GitHub는 `<owner>.<repo>-<N>` 소문자, `check-key`가 정규화하고 이후 모두 그 키 | `/`·`#` 없이 디렉토리·ref로 쓸 수 있고 분해가 유일하다. jira 키와 겹치지 않는다 |
| T3 | 이슈 DB `tracker.kind` 선언, 세션과 다르면 거부(`tracker-mismatch`) | 키 공간·링크·도구 인자가 다른 DB에 기록하는 것은 의미가 없다(K5와 같은 근거) |
| T4 | **원칙 (d)**: `schema_version: 1`·`GENERATOR_VERSION` 유지, v1 정의를 직접 고침, 마이그레이션·옛 형식 읽기 코드 없음(사용자 결정 10/11) | 배포된 이슈 DB가 없다(main 밖으로 나간 적 없음). 버전을 올리면 `jira/`·`issues/` 이중 읽기가 영구히 남는다 |
| T5 | 옛 설정 키는 감지만(fail-closed), 자동 변환 없음. 사용자 config는 `config.py rename-legacy` | 옛 `jira:`를 무시하면 설정 서버가 비어 규칙 2가 경고만 하게 된다(보안 약화). 사용자는 사외 개발자뿐이라 변환 계층이 필요 없다 |
| T6 | 규칙 2 휴리스틱은 설치된 트래커 단어 합집합 + 내장 jira·atlassian. github 단어 없음 | jira 판정 불변, 어떤 설치에서도 약해지지 않는다. "github"는 규칙 11과 충돌한다 |
| T7 | 사람용 문구 "Jira"(리포트·doctor·guard 메시지)와 스크립트 파일 이름(`jira_bridge.py` 등)·모의 Jira는 유지. 게시 본문 머리만 트래커 `label`·`display` | jira 바이트 동일. 게시 본문은 그 트래커에 올라가는 글이라 라벨이 맞아야 한다 |
| T8 | GitHub `occurred_at` 기본값(`created_at`) 없음, `field_map` 기본 `{}` | 생성 시각은 발생 시각이 아니고 앵커가 조용히 틀어진다. `missing`이면 기존 흐름이 묻는다 |
| T9 | 트래커 설정은 플랫폼끼리 공유(S28·S32) | 지금 요구는 트래커 하나. 플랫폼별 덮어쓰기는 필요할 때 `PROFILE_KEYS` 확장 |
| T10 | 기계가 읽는 형식은 전부 개명(DB 폴더·필드, 설정 키, JOB 파일, CLI 옵션, 출력 키·lint·reject 코드, doctor 행 `tracker`·`tracker_post`). `jira-wiki` 형식 이름은 유지 | 나중에 바꾸면 DB·설정 변환이 필요하다. 형식 이름은 Jira 본문 형식 자체다 |

그 밖: 승인 기록 `key_arg`는 github에서 `"owner,repo,issue_number"`다. 옛 승인 기록(`kind` 없음)은 대조에서 거부되므로 render부터 다시 한다. `jira` 어댑터의 숫자는 ASCII `[0-9]`로 좁혔다(`\d`는 유니코드 숫자를 받아 디렉토리 이름이 비ASCII가 될 수 있다). 샘플 DB `key_regex`는 `\d` 그대로다.

## 8. 미룬 것

- **리포트·doctor·guard 메시지의 라벨 일반화**: "Jira" 문구는 그대로다(T7). GitHub 설치에서 어색하면 `label`로 바꾼다.
- **이슈 본문(이슈 폼)에서 구조화 필드 추출**: GitHub의 모델·SW·버전·발생 시각 위치는 사내 확인 뒤(S31). 지금은 사용자에게 묻는다.
- **플랫폼별 트래커**: `platforms.<p>.tracker` 덮어쓰기(S32, `17-platforms.md §8`).
- **GitHub 검색 결과 격리**: `search_issues` 결과는 jira_bridge가 격리하지 않는다(Jira `search_issues`와 같은 수준).
- **`.`로 시작하는 repo**(`.github`)는 작업 키 형식 밖이다. 필요하면 인코딩을 바꾼다(스키마 패턴과 함께).
