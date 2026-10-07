# CLI 계약 (생성)

> 자동 생성 — 직접 수정 금지(`python3 tools/gen_contracts.py --write`). 원본: 각 스크립트의 `build_parser()`,
> `plugin/schemas/output/analysis.schema.json`(triage 출력), `plugin/schemas/plan.schema.json`(db-authoring 요약).
> 서브커맨드·옵션 구문과 `analysis.json` 키 구조는 이 파일이 기준이다. 출력·동작·공통 규칙과 그 밖의 표·정의는 `contracts.md`(손으로 쓴다)가 기준이다.

표기: `<값>` 위치 인자·옵션 값, `[…]` 선택, `(a | b)` 하나 필수, `[a | b]` 하나까지, `{a,b}` 값 목록, `…` 여러 개.

## `config.py`

공통 옵션(모든 서브커맨드): `--json` — JSON 출력 (항상 JSON); `--plugin-root <PLUGIN_ROOT>` — 플러그인 루트 (기본: ${CLAUDE_PLUGIN_ROOT})

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| `show` | `[--keys <a,b.c>]` | `--keys`: 쉼표로 구분한 키(점 표기)만 보인다 (예: work_dir,jira.tools) |
| `site-defaults` |  |  |
| `init` | `[--answers <ANSWERS>] [--force]` |  |
| `set` | `<key> <value>` |  |
| `sync-scripts-path` |  |  |
| `jira-candidates` | `[--mcp-config <MCP_CONFIG>]... [--tools-json <TOOLS_JSON>]` |  |
| `set-jira` | `--server <SERVER> --get-issue <GET_ISSUE> [--search-issues <SEARCH_ISSUES>] [--get-comments <GET_COMMENTS>] [--read-tools <READ_TOOLS>]` |  |
| `install-hooks` | `[--db <DB>]` |  |
| `check` | `[--db <path>] [--for {write,dry-run}]` | `--for`: 기본 write |
| `gh-status` |  |  |
| `doctor` | `[--format {json,markdown}]` | `--format`: markdown: 표 하나와 마지막 줄 카운트 (기본 json, --json과 함께 못 쓴다), 기본 json |

## `code_roots.py`

공통 옵션(모든 서브커맨드): `--json` — JSON 출력 (항상 JSON); `--plugin-root <PLUGIN_ROOT>`

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| `suggest` | `[--version <v>]` |  |
| `validate` | `<roots> [--version <v>] [--db <DB>]` |  |
| `resolve` | `<ref> --roots <ROOTS>` |  |
| `find-symbol` | `<symbol> --roots <ROOTS>` |  |
| `remember` | `<roots>` |  |

## `parse_logcat.py`

공통 옵션(모든 서브커맨드): `--json` — JSON 출력 (parse·extract-bugreport는 항상 JSON); `--plugin-root <PLUGIN_ROOT>` — 플러그인 루트 (기본: ${CLAUDE_PLUGIN_ROOT})

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| `parse` | `<logcat>... (--around <ISO 시각> \| --between <ISO 시작> <ISO 끝> \| --full) [--minutes <MINUTES>] --rules <db/parser-rules> [--tz <IANA>] [--year <YYYY>] [--mask] [--no-external]` | `--around`: 발생 시각 (타임존 있는 ISO); `--between`: 명시 구간 (타임존 있는 ISO 둘, 시작 ≤ 끝); `--full`: 파일 전체; `--minutes`: 기본 5; `--rules`: <db>/parser-rules; `--tz`: 연도 없는 logcat 시각의 타임존 (IANA); `--year`: 첫 줄의 연도; `--mask`: extractor 전에 줄 단위 마스킹; `--no-external`: 외부 파서 끔 (분석 디버그용) |
| `markers` | `<logcat>... --rules <db/parser-rules> [--tz <IANA>] [--year <YYYY>] [--step-events]` | `--rules`: <db>/parser-rules; `--tz`: 연도 없는 logcat 시각의 타임존 (IANA); `--year`: 첫 줄의 연도; `--step-events`: 이슈 DB step_events 규칙의 로그 흔적(step_events[{rule, ts, seq, label}])을 더한다 |
| `extract-bugreport` | `<zip\|txt> --out <dir>` |  |
| `cut` | `<logcat>... (--evidence <match.json> \| --around <ISO 시각>) [--seconds <SECONDS>] --out <file> [--rules <RULES>] [--context <CONTEXT>] [--max-lines <MAX_LINES>] [--tz <IANA>] [--year <YYYY>]` | `--evidence`: match_signatures.py 출력 (1위 후보의 근거); `--around`: 지정 시각 (타임존 있는 ISO); `--seconds`: --around 앞뒤 초, 기본 30; `--rules`: <db>/parser-rules (mask.allow_patterns를 읽는다); `--context`: 기본 20; `--max-lines`: 기본 100 |

## `mask_pii.py`

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| — | `[<file>...] [--check] [--changed <ref> \| --staged] [--events <json>] [--out <json>] [--in-place] [--db <DB>] [--json] [--plugin-root <PLUGIN_ROOT>]` | `--json`: 요약을 JSON으로 (검사·이벤트 모드는 항상 JSON) |

## `jira_fields.py`

공통 옵션(모든 서브커맨드): `--db <DB>`; `--json` — JSON 출력 (항상 JSON); `--plugin-root <PLUGIN_ROOT>`

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| `check-key` | `<KEY>` |  |
| `extract` | `<raw.json\|yaml> [--origin {mcp,file}] [--meta-out <file>] [--consume] [--comments <all\|last:N>] [--comment-chars <N>] [--failed-step <한 줄>] [--steps-file <파일>]` | `--origin`: 기본 mcp; `--comments`: 코멘트 예산: all \| last:<N> (뒤에서 N개), 기본 all; `--comment-chars`: 코멘트 하나의 최대 글자 수 (0이면 자르지 않음), 기본 0; `--failed-step`: 실패 스텝 한 줄(선택, 마스킹 후 사용); `--steps-file`: 시험 절차 첨부 파일(txt/csv/html/zip, 선택). 읽지 못하면 경고만 내고 진행 |

## `match_signatures.py`

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| — | `[--db <DB>] --events <json> [--jira-meta <json>] [--regress] [--no-feedback-weight] [--top <TOP>] [--json] [--plugin-root <PLUGIN_ROOT>]` | `--top`: 후보 수. types·causes는 충족된 것만, pending은 N개 (0이면 전부), 기본 3; `--json`: JSON 출력 (항상 JSON) |

## `db_search.py`

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| — | `<증상 문장\|keyword\|JIRA-KEY\|ID> [--db <DB>] [--limit <LIMIT>] [--brief] [--format {json,markdown}] [--json] [--plugin-root <PLUGIN_ROOT>]` | `--limit`: 기본 20; `--brief`: 훑어보기용 요약 출력 (path·chain·code_refs·빈 값 등을 뺀다); `--format`: markdown: search.md §3 보여주기 규칙대로 (기본 json, --json·--brief와 함께 못 쓴다/무시), 기본 json; `--json`: JSON 출력 (항상 JSON) |

## `db_add.py`

공통 옵션(모든 서브커맨드): `--db <DB>`; `--json` — JSON 출력 (항상 JSON); `--plugin-root <PLUGIN_ROOT>`

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| `apply` | `<plan.json> [--pending <FILE>]... [--user <USER>]` |  |
| `drift` | `<plan.json> --onto <ref>` |  |
| `renumber` | `<옛 ID> [--base <BASE>]` | `--base`: 기본 origin/main |
| `check-ids` | `[--base <ref>]` |  |
| `similar` | `<title> [--category <CATEGORY>] [--symptom-json <SYMPTOM_JSON>]` |  |

## `db_build.py`

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| — | `[--db <DB>] (--write \| --verify \| --preview <out_dir>) [--staged] [--json] [--plugin-root <PLUGIN_ROOT>]` | `--staged`: --verify와 함께: index 기준; `--json`: JSON 출력 (항상 JSON) |

## `db_lint.py`

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| — | `[--db <DB>] (--all \| --ref <ref> \| --changed <ref> \| --staged) [--residual <옛 ID=새 ID>]... [--json] [--plugin-root <PLUGIN_ROOT>]` | `--json`: JSON 출력 (항상 JSON) |

## `db_regress.py`

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| — | `[--db <DB>] (--all \| --changed <ref> \| --staged \| --events-diff <ref>) [--json] [--plugin-root <PLUGIN_ROOT>]` | `--events-diff`: 규칙 변경 전후 이벤트 변화 (R5); `--json`: JSON 출력 (항상 JSON) |

## `db_verify.py`

공통 옵션(모든 서브커맨드): `--db <DB>`; `--json` — JSON 출력 (항상 JSON); `--plugin-root <PLUGIN_ROOT>`; `--verbose` — 통과한 R1~R6 행의 세부까지 전부 (기본은 접는다); `--draft <dir>`

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| `rules` | `(--plan <plan.json> \| --changed <ref> \| --staged) [--extra [<logcat>...]] [--extra-normal [<logcat>...]]` | `--extra`: R6 같은 증상 표본 (expect: match); `--extra-normal`: R6 정상 표본 (expect: nomatch) |
| `resolution` | `[<logcat>...] [--cause <ID>] [--plan <plan.json>]` |  |
| `fix` | `[<logcat>...] [--cause <ID>] [--plan <plan.json>] [--build <빌드>]` |  |

## `db_pr.py`

공통 옵션(모든 서브커맨드): `--json` — JSON 출력 (항상 JSON); `--plugin-root <PLUGIN_ROOT>`

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| (최상위) | `[--verbose]` | `--verbose`: stage 전체 출력 |
| `lock status` |  |  |
| `lock acquire` | `<작업 키> [--command <이름>] [--take-over]` |  |
| `lock release` | `<작업 키> [--force]` |  |
| `snapshot` | `--job <작업 키>` |  |
| `my-prs` |  |  |
| `cleanup` | `(--dry-run \| --yes) [--older-than [<days>]]` |  |
| `preflight` | `--branch <br> [--search <원인 ID\|JIRA-KEY>] [--jira <KEY>]` |  |
| `stage` | `<plan.json> --wt <dir> --branch <br> [--dry-run] [--verbose] [--then-summary]` | `--verbose`: stdout도 stage.json과 같이 전체 (기본은 통과 항목을 접는다); `--then-summary`: stage 종료 0·3이면 이어서 summary --format markdown을 부르고 그 마크다운만 출력한다 (--json·--verbose와 못 쓴다) |
| `summary` | `<wt> [--format {json,markdown}]` | `--format`: markdown: write-flow §4 확인 화면을 마크다운으로 (기본 json, --json과 함께 못 쓴다), 기본 json |
| `publish` | `<wt> --branch <br> --lease <sha\|new> --approved <hash> [--commit] [--and-discard]` | `--lease`: 원격 브랜치 SHA 또는 new(원격에 없어야 함); `--commit`: 커밋이 없으면 승인 해시·hooksPath·guard 검사를 거쳐 summary의 commit_message로 커밋한 뒤 publish한다 (멱등); `--and-discard`: publish 종료 0일 때만 이어서 discard한다 |
| `discard` | `<wt>` |  |
| `find-plan` | `--branch <BRANCH>` |  |

## `db_precommit.py`

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| — | `--db <toplevel> [--staged] [--json] [--plugin-root <PLUGIN_ROOT>]` | `--db`: 이슈 DB toplevel ("$(git rev-parse --show-toplevel)"); `--staged`: index 기준 (기본값), 기본 True; `--json`: JSON 출력 (항상 JSON) |

## `db_review.py`

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| — | `[<category>] [--db <DB>] [--out <file>] [--as-of <YYYY-MM-DD>] [--json] [--plugin-root <PLUGIN_ROOT>]` | `--out`: Markdown 리포트를 쓸 파일; `--as-of`: 기준일 (기본: 오늘); `--json`: stdout에 JSON |

## `db_migrate.py`

공통 옵션(모든 서브커맨드): `--db <DB>`; `--json` — JSON 출력 (항상 JSON); `--plugin-root <PLUGIN_ROOT>`

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| (최상위) | `[--to <N>] [--dry-run]` | `--to`: 이슈 DB 워킹 트리를 스키마 v<N>으로 올린다; `--dry-run`: --to와 함께: 아무것도 쓰지 않고 바뀔 파일만 보인다 |
| `upgrade-plan` | `<plan.json> [--write]` | `--write`: 올린 계획으로 파일을 덮어쓴다 (원본은 .v<옛 버전>.bak) |

## `guard.py`

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| — | `[--plugin-root <PLUGIN_ROOT>]` |  |

## `jira_bridge.py`

stdin: PostToolUse hook 입력 JSON (argparse 없음)

## `triage.py`

공통 옵션(모든 서브커맨드): `--plugin-root <PLUGIN_ROOT>`; `--json` — JSON 출력 (항상 JSON)

| 서브커맨드 | 사용법 | 옵션 설명 |
|---|---|---|
| `run` | `<KEY> [--logs <logcat\|bugreport>... \| --more-logs <logcat\|bugreport>...] [--jira-raw <json> \| --jira-file <yaml> \| --jira-meta <json>] [--code <프로필\|경로\|skip>] [--dry-run] [--analysis-only] [--answer <kind=값>]... [--tz <TZ>] [--year <YEAR>] [--minutes <MINUTES>] [--refresh] [--offline-db <db>] [--out <dir>] [--failed-step <한 줄>] [--steps-file <파일>] [--clock-offset <±시간>]` | `--more-logs`: 이전 분석의 로그 뒤에 로그를 더해 다시 분석(RF-7). --logs와 함께 못 쓴다; `--analysis-only`: 이슈 DB에 기록하지 않는 분석 전용(cleanup·기존 계획·열린 PR 건너뜀, ok면 lock 해제). --dry-run과 함께 못 쓴다; `--refresh`: 같은 세션에서도 스냅샷을 다시 만들고, 같은 입력의 분석 재사용(analysis-cache.json)도 끈다; `--failed-step`: 실패 스텝 한 줄(선택, 보조 정보). 마스킹해서만 쓴다; `--steps-file`: 시험 절차 첨부 파일(txt/csv/html/zip, 선택). 읽지 못하면 경고만 내고 진행; `--clock-offset`: 시험 장비 시각 → 단말 logcat 시각 시계 차(단말 = 장비 + 값). 예: +3m, -90s, +00:03:00, 180. 없으면 steps-file의 장비 시각은 분석 구간에 쓰지 않는다 |
| `explore` | `<KEY> [--out <dir>]` | `--out`: `run --offline-db --out`의 JOB 디렉토리(없으면 <work_dir>/<KEY>) |
| `release` | `<KEY>` |  |

## `triage.py run` → analysis.json 키

원본 `plugin/schemas/output/analysis.schema.json`. `키?`는 있을 때만, `(…)`는 설명, `[≤N]`은 목록 상한(`[]`는 상한 없는 객체 목록).
`TT_SCHEMA_CHECK=1`(테스트·CI)이면 `triage.py run`이 출력을 이 스키마로 검사한다(위반이면 종료 코드 2).

### `status: ok`

완료. JOB/analysis.json(≤ 4KB, stdout도 같음). 값이 null·빈 목록·빈 객체인 최상위 키는 내지 않는다

- key
- generated_at
- request_hash(입력 해시(부분별 parts {logs, jira, db, config, plugin, args}, 파싱 전에 계산))
- run?(결과(core)를 계산한 실행 번호)
- reuse?({hit: true, run}(재사용) 또는 {hit: false, prev_run, changed[부분] | reason: refresh|cache-missing, added_logs[≤5], prev_top, top_changed}; 첫 실행·--offline-db에는 없음, 4KB 압축 시 added_logs·prev_top 순으로 뺀다)
  - hit
  - run?
  - prev_run?
  - changed?(바뀐 입력 부분)
  - reason?: refresh | cache-missing
  - added_logs?[≤5]
  - prev_top?
  - top_changed?
- mode: write | read-only | analysis-only | offline
- read_only_reasons?(mode: read-only일 때 config.py check 사유(analysis-only면 없음))
- read_only_hint?(mode: read-only일 때만, config.py check 사유 메시지, ≤200바이트, 4KB 압축 시 100)
- snapshot?
- plan?(analysis-only면 {exists, source, pr_number}만)
- jira?(failed_step {text(≤120, 4KB 압축 시 60), source}는 있을 때만, 보조 정보)
- step_anchor?(실패 스텝 앵커·실패 스텝·시계 정렬·스텝 순서 시도가 있을 때만)
  - outside_errors?(앵커가 있고 Jira 발생 시각이 분석 범위 밖·로그 범위 안일 때 그 시각 근처의 범위 밖 오류 이벤트 수, 0이면 키 없음, 근거·점수에 쓰지 않음)
  - source: log_marker | steps_file | step_order | jira | symptom_scan
  - step?(≤80, 4KB 압축 시 40)
  - step_from?(마커의 스텝을 쓴 경우만): "marker"
  - span?([시작|null, 실패])
  - jira_gap_min?
  - focus?[≤3](유형 ID)
  - clock?({mode: manual|none, offset_sec?(manual), reason?(none, "시계 차 모름"; 4KB 압축 시 먼저 뺌)})
  - order?({matched, observable, missed, last{step(≤40), ts}(step_order일 때, 4KB 압축 시 가장 먼저 뺌), reason?(앵커를 못 정해 jira로 돌아갈 때)})
- existing?
- open_prs?
- build?
- logs
  - files?
  - window?
  - range?
  - in_range?
  - clock_anomalies?
  - events?
  - uncollected_tags?[≤3]({tag(≤40), lines, warn}; 후보 없음·1위 C=0일 때만, 파서 규칙에 없는 태그 힌트)
- candidates?[≤3]
  - type
  - cause
  - title?
  - category?
  - score
  - confidence
  - S
  - C
  - phones?
  - evidence[≤10]
    - ts
    - tag
    - msg(마스킹)
    - event
  - fix_judgement?
  - fix_message?
  - related?
  - resolution?
  - resolution_verification?
  - fix_status?
  - jira_count?
  - jira_recent?
- pending_causes?
- no_candidate?
  - search_hits
  - error_events[≤8]({ts, tag, event, phone, request?, error?, code?, reason?, cause?}(각 ≤40자, 있을 때만; 4KB 압축 시 4개·부가 필드 없음))
  - error_event_total
- code
  - skipped
  - roots?
  - tree_version?
  - auto?(`true`: `code.auto_select`로 자동 선택했을 때만): true
  - resolved?
  - moved?
- analyzer?({skill, when})
- explore?({reason: no_candidate|cause_unconfirmed, when: ask|always|never}(run은 타임라인을 만들지 않는다))
- warnings?
- notes?(잔여 worktree·도구 브랜치 안내 등)
- lock_owner?
- lock_released?(analysis-only가 ok로 끝나 lock을 풀었을 때만(lock_owner 없음)): true
- files({report, events, match, jira}(4KB 압축 시 report만))
- must_show?[≤6](리포트 줄 중 꼭 보여야 하는 것, 우선순위 순(4KB 압축 시 줄당 160자·앞 4개))
- truncated(4KB로 줄여도 넘으면 true)

### `status: needs_input`

사용자 결정 지점. 같은 명령에 --answer kind=값을 붙여 재실행

- key
- needs_input
  - kind: lock | plan | jira | year | reanalyze | open_pr | logs | code | code_confirm | time | window
  - question
  - options
  - answer(--answer <kind>=<값>)
- lock_owner?

### `status: stopped`

사용자 중단(lock 해제)

- key
- reason
- lock_released?
