# 02. 설정: 사용자 config, setup, `issue-db.config.yaml`

> 원본 4장, 5.3.

---

## 4. 사용자 설정 (`/telephony-triage:setup`)

설정 파일 위치: `~/.telephony-triage/config.yaml`. 사용자별 파일이며 레포에 커밋하지 않는다.

```yaml
user:
  ghe_id: <GHE 아이디>                     # Jira 기록/피드백의 analyzed_by
plugin:
  scripts_path: <플러그인 scripts 경로>     # git pre-commit hook이 사용. setup과 SessionStart hook(config.py sync-scripts-path)이 ${CLAUDE_PLUGIN_ROOT}/scripts로 자동 갱신
issue_db:
  path: ~/work/telephony-issue-db           # 로컬 clone 경로
  remote: <사내 GHE URL>/<org>/telephony-issue-db.git
  base_branch: main
  ghe_host: <사내 GHE 호스트>               # gh CLI의 GH_HOST로 사용
jira:
  mcp_server: <사내 Jira MCP 서버 이름>
  tools: {}                                 # 논리 동작 → 실제 도구 전체 이름 (get_issue 필수, search_issues·get_comments 선택). 16-existing-assets.md §16.1
  read_tools: []                            # 허용할 읽기 도구의 전체 이름 목록 (mcp__<server>__<tool>). setup이 채우고 사용자가 확인 (08-safety.md §9)
  timezone: <Jira 시각 타임존>               # 예: Asia/Seoul (14-site.md S4)
  field_map:                                # Jira 필드 → 분석 항목 매핑 (커스텀 필드 포함, 14-site.md S4)
    occurred_at: <필드>
    model: <필드>
    sw: <필드>
    android_version: <필드>
    carrier: <필드>
    # 선택(14-site.md S22): 시험 절차·실패 스텝 필드. 없으면 쓰지 않는다
    test_steps: <필드>
    failed_step: <필드>
  failed_step_patterns: []                  # 선택. 설명·시험 절차 텍스트에서 실패 스텝 한 줄을 찾는 줄 단위 정규식 (아래 설명)
logcat:
  timezone: <logcat 시각 타임존>             # 연도 없는 threadtime의 해석 기준 (14-site.md S7). 스킬이 parse_logcat --tz로 넘김
  year_source: jira                         # jira(발생 시각의 연도) | file-mtime | ask. 스킬이 연도를 정해 parse_logcat --year로 넘김
code_profiles:                              # 선택. 자주 쓰는 소스 트리 프리셋
  - name: android16-main
    android_version: "16"
    roots:
      aosp: /path/to/android16              # AOSP 소스 루트
      vendor_ril: /path/to/android16/vendor/<ril 경로>
  - name: android17-dev
    android_version: "17"
    roots:
      aosp: /path/to/android17
      vendor_ril: /path/to/android17/vendor/<ril 경로>
recent_code_roots: []                       # 직접 입력한 경로를 최근 5개까지 자동 기록
log_dir: ~/logs                             # logcat 기본 탐색 경로 (선택)
work_dir: ~/.telephony-triage/work          # 작업 계획·상태 파일, 읽기 스냅샷(_snapshot), 임시 worktree, 세션 lock 위치 (contracts.md §3.2)
```

**코드 경로는 analyze할 때마다 정한다.** Android 버전(16, 17 …)과 브랜치마다 소스 트리 위치가 다르고, 같은 파일도 버전에 따라 경로가 바뀌기 때문이다. `code_profiles`는 고르기 편하게 하는 프리셋일 뿐이고 없어도 된다. 절차는 `07-workflow.md §Step 2-1`이다.

- `roots`의 키는 이슈 DB `issue-db.config.yaml`의 `code_root_keys`에 있는 이름만 쓴다 (기본 `aosp`, `vendor_ril`).
- `code.auto_select`(선택, 불리언, 기본 `true`): `--code`도 답도 없을 때 대상 버전이 일치하는 `code_profiles` 프로필이 정확히 1개면 묻지 않고 그 프로필을 쓴다(`07-workflow.md §Step 2-1`, 알림 의무). 우선순위는 사용자 config > `site-defaults.yaml` > 내장 기본값 `true`이다(실행할 때 사용자 config·site-defaults에서 직접 읽는다). `setup`이 만드는 config에는 쓰지 않는다. `false`면 항상 묻는다. 값은 불리언(`true`/`false`)만, 따옴표 없이 쓴다. 문자열·0/1·null은 잘못된 값이라 `explore.when`처럼 warnings에 경고(`code.auto_select 값이 잘못됐다(<값>). 묻기로 본다`)하고 묻는 쪽(`false`)으로 본다(묻는 질문에도 표시한다).
- 이슈 DB의 `code_refs`는 `<root 키>:<루트 기준 상대 경로>` 형식이다 (`03-issue-db.md §5.4`). 그래서 같은 이슈 DB를 어떤 버전 트리에 대해서도 쓸 수 있다.
- 시각 정렬: Jira 발생 시각(`jira.timezone`)과 logcat 시각(`logcat.timezone`, 연도는 `logcat.year_source`)을 같은 기준(UTC)으로 바꿔서 비교한다. 파서(`parse_logcat.py`)는 **사용자 config를 읽지 않고** 시각을 `--tz/--year` 인자로만 받는다 (Phase 2에서 인자로 구현, Phase 6에서 config 연결). 파서가 읽는 설정은 플러그인 `site-defaults.yaml`의 파서 백엔드·외부 파서 설정뿐이다 (`contracts.md §3.2` 설정 읽기). 형식과 기본값은 Phase 0에서 확인한다(S4, S7).
- Jira 키 형식은 DB 공통 값이므로 사용자 config가 아니라 `issue-db.config.yaml`의 `jira_key_regex`에 둔다 (5.3).

setup 커맨드가 순서대로 하는 일:
1. config가 없으면 항목별로 묻고 생성한다. **답한 값만 저장한다**: 필수 항목과, 선택 항목 중 팀 기본값(`site-defaults.yaml`·내장 기본값)과 다른 답만 쓰고(그리고 `plugin.scripts_path`), 나머지는 저장하지 않아 이후 팀 기본값 변경을 그대로 상속한다. 경로는 존재 여부를 검증한다. `code_profiles`는 건너뛸 수 있다. `~/.telephony-triage/`와 `work_dir`는 권한 `700`으로 만든다(작업 계획에 Jira 요약이 들어가므로). 제약: `issue_db.base_branch`·`work_dir`는 `site-defaults.yaml`에서 상속되지 않는다(이슈 DB `.githooks/pre-push`가 사용자 config에서 이 두 값을 직접 읽고 site-defaults를 보지 않으므로, 팀 기본값으로 지원하려면 pre-push도 같이 바꾼다). `init`으로 이미 만든 개발·연습 config는 자동으로 상속형이 되지 않는다. 팀 기본값을 따르게 하려면 `config.py init --force`로 다시 만들거나 해당 키를 config.yaml에서 지운다.
2. `plugin.scripts_path`를 `${CLAUDE_PLUGIN_ROOT}/scripts`로 기록한다 (`config.py sync-scripts-path`).
3. 이슈 DB 경로에 clone이 없으면 `git clone`을 제안한다.
4. 이미 등록된 Jira MCP를 찾는다(사용자 범위 등록 필요, 못 찾으면 등록 범위를 안내. `site-defaults.yaml`의 `jira.exclude_servers`(기본 `['mock-*']`, 테스트 헬퍼 복사본은 `[]`)에 맞는 서버는 후보에서 제외). 도구 목록에서 `jira.tools` 후보(get/issue, search, comment 계열)를 골라 사용자 확인을 받고(`site-defaults.yaml`의 팀 기본값이 있으면 그것을 먼저 제안), 이어서 서버의 도구 목록을 읽어서 이름으로 읽기 도구 후보(get/search/list/read/fetch 계열)를 고르고, **사용자에게 확인받아** `jira.read_tools`에 **전체 도구 이름**(`mcp__<server>__<tool>`)으로 저장한다. 서버가 없으면 사내 MCP 등록 방법을 안내하고 중단한다. 도구 이름 형식은 S1·S3에서 확인한다.
5. 이슈 DB 레포에 git pre-commit hook을 설치한다: `git -C <issue_db.path> config core.hooksPath .githooks`. 설정 후 값이 **정확히 `.githooks`** 인지 확인한다 (다른 값이면 guard가 이슈 DB 커밋을 모두 막는다, `08-safety.md §9`).
6. `db_pr.py lock acquire setup` → `db_pr.py snapshot --job setup`으로 읽기 스냅샷 `<work_dir>/_snapshot`을 만든다. 사용자 clone의 워킹 트리와 브랜치는 바꾸지 않는다. 다른 작업의 lock이 있으면 보유자를 보여주고, 그 세션이 끝났는지 확인받은 뒤 진행한다(`contracts.md §3.2` 세션 lock).
7. **스냅샷 기준으로** 이슈 DB의 `schema_version`, `generator_version`, `parser_backend`, `external_parsers`가 플러그인과 호환되는지 확인한다: `config.py check --db <work_dir>/_snapshot --for dry-run` (`06-collaboration.md §6.4`). 오래된 사용자 clone이 아니라 origin/<base> 기준 버전을 본다. 쓰기가 막히는 조건이면 "읽기 전용"이라고 알리고 계속한다.
8. `db_pr.py lock release setup`.
9. `gh auth status --hostname <ghe_host>`를 확인한다. **실패하면 로그인 방법을 안내하고 "쓰기 불가(gh 인증 없음)"로 setup을 끝낸다(종료 코드 2).** 1~8의 읽기 설정은 이미 끝났으므로 읽기 전용 분석과 `--dry-run` 연습은 가능하다. gh 인증이 없는 동안은 모든 이슈 DB 쓰기 작업(analyze Step 8의 push, `record`, `sync-pr`, `verify-fix`, `validate --cause`, `fix-submitted`, import/review/move 계획 PR)이 `config.py check`에서 막힌다.
10. `config.py doctor --format markdown`(읽기 전용 점검 한 장: config·스크립트 경로·clone·hook·Jira 매핑·gh·스냅샷 나이·호환성·lock)의 표를 그대로 보이고, `fail`·`warn` 행의 안내만 전한다(자동 수리 없음). 9번에서 gh 인증이 실패해 setup을 끝내는 경우에도 이 표를 함께 보인다. 이어서 이슈 DB의 `docs/getting-started.md` 위치를 알려준다.

`analyze` 등 다른 커맨드는 config가 없으면 setup으로 유도한다. 플러그인은 SessionStart hook으로 매 세션 `plugin.scripts_path`를 현재 `${CLAUDE_PLUGIN_ROOT}/scripts`로 갱신한다 (플러그인 업데이트 후 경로가 바뀌므로).

---

> **실패 스텝(선택)**: 이슈의 시험 절차·실패한 스텝은 있을 수도 없을 수도 있다. `jira.field_map.failed_step`(필드 값을 그대로), 없으면 `jira.failed_step_patterns`로 마스킹된 설명, 그다음 `field_map.test_steps` 텍스트에서 찾는다. 패턴은 **줄 단위** 정규식이고, 줄 순서대로·패턴 순서대로 처음 맞는 것이 이기며 `(?P<step>…)` 그룹이 있으면 그 값, 없으면 줄 전체다. 정규식 오류는 경고만 내고 건너뛴다. 기본값은 `[]`(자동 추출 없음). 값이 없거나 읽지 못해도 동작은 없을 때와 같다(질문·중단 없음). 첨부 파일은 사용자가 `--steps-file`로 줄 때만 읽는다. **MCP로 첨부를 가져오는 것은 향후 과제**다(`jira.read_tools`로 허용된 도구만, `99-deferred.md`).
>
> **실패 스텝 앵커(선택, `site-defaults.yaml`의 `failed_step`)**: 시험 자동화가 logcat에 남기는 스텝 마커로 실패 스텝의 시간 구간을 정한다(`07-workflow.md §Step 3`). 키: `marker_patterns`(`TAG: msg` 줄에 맞추는 정규식 목록, 이름 그룹 `step`·`status` 필수, **기본 `[]` = 마커 스캔 안 함** — 실제 logcat에는 시험 스텝의 START/FAIL 마커가 없다. 마커를 남기는 시험 자동화가 있을 때만 켠다. **`parse_logcat.py`가 이 파일에서만 읽으므로 사용자 config로 바꿀 수 없다**), `marker_status`(`start`·`pass`·`fail`별 상태 문구 목록, casefold 비교), `anchor_without_step`(실패 스텝을 모를 때 FAIL 마커 자체를 앵커로 쓸지, 기본 `true`), `window`(`pre_sec` 60·`post_sec` 30·`fail_only_pre_sec` 120·`max_span_sec` 900), `disagree_minutes`(Jira 발생 시각과 스텝 실패 시각이 이보다 많이 다르면 경고, 기본 10), `steps_file_tz`(steps-file 시각의 타임존, 기본 `null` = logcat 타임존), `clock_offset`(시험 장비 시각 → 단말 logcat 시각 시계 차, `단말 = 장비 + 값`, 예 `'+3m'`·`'-00:00:45'`·`180`, 기본 `null` = 모름 → 장비 시각은 구간에 쓰지 않는다. `--clock-offset`이 우선, 형식이 틀리면 경고하고 `null`), `steps_status`(`pass`·`fail` 상태 낱말, casefold), `steps_columns`(표 머리 열 이름 `number`·`name`·`status`·`start`·`end`, casefold, **YAML에서 `no`·`yes`·`on`·`off`는 따옴표로 감싼다** — 안 그러면 불리언이 된다), `order`(스텝 순서 정렬: `min_matched` 1·`max_missing` 1·`pre_sec` 10·`fail_post_sec` 120; 최대 구간은 `window.max_span_sec`을 쓴다). 시험 장비 시계는 단말과 다를 수 있으므로 steps-file의 시각 열은 시계 차를 **수동으로** 줄 때만 쓴다. 사내 표기를 확인하기 전까지는 placeholder다(14-site.md S22).
>
> **플랫폼 상수(선택, `site-defaults.yaml`의 `platform`, RF-4)**: 경로·태그·섹션 헤더처럼 사내 환경에 맞춰야 하는 상수를 코드 대신 설정으로 둔다. 키: `name`(지금은 `android`만, 다른 값이면 종료 코드 2 "지원 플랫폼: android"), `source_tree.required_dirs`(aosp 루트에 모두 있어야 하는 상대 경로 목록, 기본 `[frameworks/opt/telephony]`, 비면 오류), `source_tree.version_sources`(트리 버전 추정 `[{file, regex}]`, 순서대로 시도, 그룹 1 = 버전, `re.M`, 기본은 release config → `build/make/core/version_defaults.mk` → `build/core/version_defaults.mk`), `log.phone_id.{tag, msg_prefix, msg_suffix}`(슬롯 표기 정규식 목록, 그룹 1 = 슬롯 번호, 위치마다 순서대로 첫 일치, `[]`이면 그 위치는 슬롯을 뽑지 않는다), `ril.tags`(RIL 줄로 해석할 태그 목록, 기본 `[RILJ]`, `[]`이면 RIL 해석 없음), `ril.vendor`(선택, 벤더 RIL 층 연결 — 없으면 출력이 이전과 같다: `layers`(필수 `[{tag, patterns}]`, 정확한 태그 이름, 패턴마다 이름 그룹 `serial`·`token` 중 정확히 하나(값은 10진 숫자만 쓰고 그 밖 값의 줄은 무시), 그 밖 이름 그룹은 무시, 첫 일치만, 태그가 `ril.tags`와 겹치면 오류), `link_ms`(요청 뒤 HAL 줄을 찾는 시간, 기본 2000), `coverage_tags`(정규식 없이 "수집 살아 있음"만 표시하는 정확한 태그, 기본 없음, `ril.tags`와 겹치면 오류), 결과 `hal`은 `04-parser-matching.md §5.8 (2)`, 초안은 `tools/s0_suggest.py`), `bugreport.{wanted_buffers, section_regex, boundary_regex}`(기본 `[system, radio, main]`와 dumpstate 섹션 헤더, `section_regex`는 `(?P<cmd>)` 필수). 생략한 키는 코드 기본값이고 그때 출력은 이전과 같다. 키를 쓰면 그 목록으로 **통째로 바뀐다**(기본에 합쳐지지 않는다). **`parse_logcat.py`·`code_roots.py`가 이 파일에서만 읽으므로 사용자 config로 바꿀 수 없다.** 잘못된 값(모르는 키·정규식 오류·그룹 없음·절대 경로·`..`)은 키 경로를 담아 종료 코드 2로 멈춘다. 값을 바꾸면 파서 출력이 달라질 수 있으므로 이슈 DB에서 `db_regress --all`·`db_verify rules`를 다시 돌린다(분석 재사용용 이슈 DB 소스 해시·`parser_backend` 버전은 그대로다). 이슈 DB 층의 대응 설정(`parser-rules`의 `phone_id_patterns`·`ril.yaml` `tags`)은 아직 없다.
>
> 설정 우선순위: 사용자 config > `plugin/site-defaults.yaml` > 코드 내장 기본값. `plugin/site-defaults.yaml`이 없으면 setup과 모든 커맨드(`help` 제외)가 멈춘다. `site-defaults.example.yaml`은 코드가 읽지 않고, 사외 테스트 헬퍼가 복사해서 쓴다 (`15-local-draft.md §15.1`). `site-defaults.yaml`에는 `jira.tools`·`jira.field_map`(선택 키 `test_steps`·`failed_step`)·`jira.failed_step_patterns`·`jira.exclude_servers`·`parser.backend`·`external_parsers`·`analyzers`·`explore`(탐색 분석 `when`·`timeline_max_lines`, `07-workflow.md §Step 5-2`)·`code`(선택, `auto_select`, 위)·`failed_step`(실패 스텝 앵커, 위)·`platform`(플랫폼 상수, 위)·`guard.raw_read`(선택, `{names: [원문 파일 이름], exempt_dirs: [제외 디렉토리 이름]}`, guard 규칙 10 내장 목록에 더해짐, `08-safety.md §9`)·`synthetic_allowed`가 들어간다.

## 5.3 `issue-db.config.yaml`

```yaml
schema_version: 1                    # 정수. 구조가 바뀔 때만 올린다 (06-collaboration.md §6.4)
generator_version: 1                 # 생성 파일 형식 버전. 플러그인 GENERATOR_VERSION과 같아야 쓰기 가능
ci_mode: local                       # local (현재, 06-collaboration.md §6.3) | actions | actions-build (13-actions.md)
jira_base_url: <사내 Jira URL>/browse/   # 형식은 14-site.md S17
jira_key_regex: '<Jira 키 정규식>'   # 예: '[A-Z][A-Z0-9]+-\d+' (14-site.md S16). db_lint가 Jira 파일명·key 검사, 스킬이 입력 검사
categories:                          # README 표시 순서, 이름, ID 접두어
  - {key: data,    name: Data,    id_prefix: DATA}
  - {key: call,    name: Call,    id_prefix: CALL}
  - {key: network, name: Network, id_prefix: NETWORK}
  - {key: sim,     name: SIM,     id_prefix: SIM}
  - {key: sms,     name: SMS,     id_prefix: SMS}
  - {key: ims,     name: IMS,     id_prefix: IMS}
android_versions_supported: ["16", "17"]   # 지원 중인 Android 버전 (06-collaboration.md §6.6 지원 종료 판단)
parser_backend:                      # 이 이슈 DB의 시그니처가 전제하는 파서 백엔드 (16-existing-assets.md §16.3)
  name: site                         # site | reference (사외 초안은 reference)
  min_version: <버전>                # 이보다 낮은 백엔드면 쓰기 차단, 분석은 경고 후 진행
external_parsers: {}                 # 어댑터(외부 파서)를 쓰는 카테고리 고정. 예: {data: {adapter: site_data_existing, min_version: <버전>}}
                                     # 여기 있는 카테고리의 어댑터가 없거나 낮으면 백엔드 불일치와 같이 처리 (contracts.md §기존 자산 연결 계약)
code_root_keys: [aosp, vendor_ril]   # code_refs에 쓸 수 있는 소스 루트 키
fix_ref_regex: '<Gerrit CL 또는 커밋 형식 정규식>'   # fix.ref 형식 검사 (14-site.md S18)
build_compare:                       # fixed_in과 Jira SW를 비교하는 규칙 (03-issue-db.md §5.9)
  - branch_regex: '<브랜치 식별 정규식>'
    version_regex: '<비교 가능한 부분을 캡처하는 정규식>'
scoring:                             # 매칭 점수 (04-parser-matching.md §5.11)
  symptom_weight: 0.4
  cause_weight: 0.6
  proximity_bonus_max: 0.1
  keyword_bonus_max: 0.05
  step_focus_bonus_max: 0.05         # 스텝 기준 우선 유형의 순위 가산(0~0.1). score는 바꾸지 않는다
  feedback_weight: true
  confidence: {high: 0.9, medium: 0.6}
step_focus:                          # 실패 스텝 → 우선 유형(순위 참고만, 04-parser-matching.md §5.11 (2))
  min_records: 2                     # 같은 스텝의 기존 Jira 기록이 이 건수 이상인 유형을 우선 유형으로 본다(≥ 1)
  map: []                            # [{pattern: '<마스킹된 스텝에 맞출 정규식>', types: [DATA-001], categories: [data]}]
step_events: []                      # 스텝 → 로그 흔적 규칙(스텝 순서 정렬, 04-parser-matching.md §5.8 (5)). 아래 설명
quality:                             # 06-collaboration.md §6.5, §6.6
  min_samples: 5
  low_acceptance_rate: 0.7
  stale_months: 12
  unresolved_max_days: 30
  unverified_max_days: 60          # 해결책 미검증 허용 기간
  fix_submitted_max_days: 30       # fix-submitted 후 verify-fix까지 허용 기간
  surge_ratio: 2.0
mask:                                # 08-safety.md §8
  allow_patterns: []                 # 마스킹 오탐 예외 정규식 (빌드 번호 등). lint가 PII 표본 전체 일치를 거부
matcher:
  pattern_timeout_ms: 2000           # 시그니처·extractor 정규식 패턴당 실행 시간 상한 (04-parser-matching.md §5.8 (4))
readme:
  jira_inline_max: 3                 # 표에 보이는 Jira 수, 나머지는 건수와 링크
reviewers:                           # gh pr create --reviewer에 넘길 형식 (14-site.md S19)
  format: '{org}/{team}'             # CODEOWNERS 항목 @<org>/<team>에서 {org}, {team}을 치환
```

- **`step_events`**(메인테이너가 관리하는 **순서 있는 목록**): 시험 스텝(마스킹된 `번호 | 이름`)이 AP 로그에 남기는 흔적을 규칙으로 적는다. 스텝에 `pattern`이 처음 맞는 규칙 하나가 적용된다. 대상은 **정확히 하나**: `event`(extractor 이벤트 이름, 예약 `ril_*`, `builtin.*`; 선택 `fields{필드: 정규식}`), `ril`(`ril.yaml`의 요청·unsol 이름; 선택 `dir: req|resp|unsol`, 기본 `req`, `UNSOL_*`는 `unsol`), `match`(마스킹된 `TAG: msg`에 맞출 정규식). CP(모뎀) 동작처럼 AP 로그에 흔적이 없는 스텝은 `observable: false`(대상 없음)로 적는다. **어느 규칙에도 맞지 않는 스텝은 관측 불가**(건너뜀, 놓친 것으로 세지 않음). 기본 `[]`(스텝 순서 정렬 안 함). 예: `{pattern: '(?i)(비행기|airplane).*(켜|\bon\b)', match: '^ConnectivityService: setAirplaneMode enabled=true'}`, `{pattern: '(?i)데이터\s*연결', ril: SETUP_DATA_CALL}`, `{pattern: '(?i)(CP|모뎀)', observable: false}` (placeholder — `14-site.md` S22). `db_lint`가 검사한다(오류 코드 `step-event`, `contracts.md §3.2`). 규칙 번호는 목록 위치이므로 순서를 바꾸면 달라진다.
- 리뷰어 계산: `db_pr summary`가 변경 파일 경로와 유형의 `secondary_categories`로 `.github/CODEOWNERS`의 해당 항목(`/<category>/`, `/parser-rules/` 등)을 찾고, 그 `@<org>/<team>`을 `reviewers.format`으로 바꿔 `gh pr create --reviewer`에 넘긴다. 계획에 `allow-cause`가 있으면 대상 fixture 경로의 카테고리 오너도 더한다(다른 카테고리 fixture의 `also_allowed`를 바꾸므로, `contracts.md §fixture`).
- 카테고리 목록 검증(`category`가 `categories`에 있는지, ID 접두어가 `id_prefix`와 맞는지)은 JSON Schema가 아니라 `db_lint.py`가 한다.
- `generator_version`이 플러그인 `GENERATOR_VERSION`과 다르면 `ci_mode: local`/`actions`에서는 **이슈 DB 쓰기 전체**(Step 8, `record`, `sync-pr`, `verify-fix`, `validate --cause`, `fix-submitted`, 리뷰 PR)를 막고 읽기 전용 분석만 한다. 예외는 메인테이너가 버전을 올리는 `migrate/schema-v<N>` 브랜치의 직접 편집뿐이다(그 브랜치에서는 `config.py check`·pre-commit·`validate`가 버전 불일치를 차단하지 않는다, `06-collaboration.md §6.4`). `actions-build`에서는 생성 파일을 PR에 넣지 않으므로 영향이 없다.
- 원인의 `android_versions: []`는 **전 버전**을 뜻한다 (`03-issue-db.md §5.4`).
