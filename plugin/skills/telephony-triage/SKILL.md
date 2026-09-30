---
name: telephony-triage
description: Android Telephony 이슈(data·call·network·sim·sms·ims)를 Jira와 logcat/bugreport로 분석해 원인·해결책을 찾고, 팀 공용 이슈 DB(telephony-issue-db)에 카테고리·유형(증상)·원인별로 분류해 PR로 누적한다. 사용자가 Jira 키와 로그를 주며 "로그 분석해줘", "데이터 안 붙어", "콜이 왜 끊겼는지", "SIM 인식 안 됨", "SMS 전송 실패", "IMS 등록 실패", "서비스 없음", "SETUP_DATA_CALL이 안 나감", "기존에 비슷한 이슈 있었어?"처럼 telephony 증상의 원인 분석·분류를 요청하면 반드시 이 스킬을 쓴다. 이미 해결한 이슈를 분석 없이 이슈 DB 히스토리에만 남기는 수동 기록(record), 수정 CL 머지 반영(fix-submitted), 수정 빌드 로그로 재발 여부 확인(verify-fix), 해결책 효과 검증(validate --cause), 머지 전 PR 재동기화(sync-pr)도 이 스킬이 한다. RIL·IMS 개념 설명, 앱 빌드 에러, 일반 git 작업, 코드 리뷰, Jira 요약만 요청하는 경우에는 쓰지 않는다.
---

# telephony-triage

팀이 오래 함께 쌓는 **이슈 DB**에 Telephony 이슈를 분류해 넣는 스킬이다. 분석 결과가 틀리면 팀 전체의
매칭 품질이 나빠지므로, 이 스킬의 중심은 "결정적인 스크립트 출력으로 판단하고, 사람의 확인을 받고,
최신 main 위에 계획을 적용해 PR로 올린다"이다. 너는 스크립트를 부르고, 결과를 설명하고, 사용자의
결정을 작업 계획에 옮긴다. **이슈 DB 파일을 직접 쓰지 않는다.**

이 파일은 `analyze`(Step 0~8)의 핵심 흐름이다. 다른 흐름은 해당 reference만 읽는다.

| 언제 | 읽을 파일 |
|---|---|
| Step 8, 그리고 모든 쓰기 흐름의 적용·확인·커밋·PR | `reference/write-flow.md` |
| `record` (수동 기록) | `reference/record.md` |
| `verify-fix`, `fix-submitted`, `validate --cause` | `reference/verify.md` |
| `sync-pr`, 또는 Step 8-2에서 원격 브랜치가 이미 있을 때 | `reference/sync-pr.md` |
| 새 원인·유형·시그니처·파서 규칙·fixture를 만들 때 (Step 7) | `reference/db-authoring.md` |
| 로그 해석이 필요할 때 | `reference/log-tags.md`, `reference/ril-requests.md`, `reference/fail-causes.md` |

커맨드(`commands/*.md`)로 들어왔으면 그 커맨드가 가리키는 흐름만 따른다. 다른 흐름의 절차를 이 파일에서 찾지 않는다.

## 실행 규칙

- **스크립트 호출**: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py" ... --json`. 결과 JSON만 읽는다.
  `${CLAUDE_PLUGIN_ROOT}`가 치환되지 않은 환경이면 `~/.telephony-triage/config.yaml`의 `plugin.scripts_path`를 쓴다.
  아래에서 `S/<이름>`은 이 경로다.
- **경로 기호**: `WD` = config의 `work_dir`(`S/config.py show`의 `effective.work_dir`), `SNAP` = `WD/_snapshot`,
  `JOB` = `WD/<작업 키>`, `wt` = `JOB/wt`, `draft` = `JOB/draft`. analyze·record의 작업 키는 Jira 키다.
- **`--db`는 항상 명시한다**: 읽기(파서 규칙, 매처, lint, 검색, `config.py check`)는 `--db SNAP`, 쓰기는 `--db wt`.
  (`db_pr.py`는 `--db`를 받지 않는다.)
- **종료 코드**: 0 성공, 1 검사 실패(drift 포함) → 원인을 보여주고 차단, 2 사용·환경 오류 → 멈추고 메시지를 그대로
  보여준다(특히 "사내 기본값 없음(S-3 미완료)"), 3 승인 필요 → 확인 화면에 "승인 필요"로 표시.
  **예외**: analyze의 `config.py check`가 2와 `writable: false`(버전 불일치 등 쓰기 불가)를 내면 멈추지 않고 Step 1의 "읽기 전용 모드"로 계속한다.
  (record·verify-fix 등 쓰기만 하는 흐름은 멈춘다.)
  git 충돌, 인증 실패, MCP 없음, 버전 불일치는 **우회하지 않고** 보고한다.
- **로그 원문을 통째로 읽지 않는다.** 파서 출력(마스킹된 이벤트)과 매처 결과만 본다. 원문이 필요하면 근거 주변 몇 줄만.
- **사용자 clone(`issue_db.path`)에서 `checkout`·`reset`·`clean`·`commit`을 하지 않는다.** 사용자 clone에는
  `db_pr.py`가 fetch·조건부 `pull --ff-only`·worktree·`tt/*` 도구 브랜치만 다룬다. 사용자의 `issue/<KEY>` 브랜치도 건드리지 않는다.
- **Jira는 읽기 전용이다.** config `jira.tools`의 논리 동작(`get_issue`, 선택 `get_comments`·`search_issues`)에
  매핑된 도구만 부르고, 그 도구가 `jira.read_tools`에 있는지 확인한다. 도구 이름을 추측하지 않는다. 매핑이 비어 있으면
  "`/telephony-triage:setup`에서 Jira 도구 매핑을 확인하라"고 안내하고 멈춘다(`--jira-file` 연습은 가능).
  코멘트 작성·상태 변경·첨부 같은 쓰기 요청은 거절하고, 리포트를 복사해 직접 붙이는 방법을 제안한다.
- **마스킹**: 리포트, 계획, 확인 화면, PR 본문에는 마스킹된 텍스트만 쓴다. Jira 텍스트는 `jira_fields.py`가 읽자마자
  마스킹한다. 사람 이름(테스터·고객)은 마스킹 규칙으로 안 잡히므로 너가 옮기지 않는다.
- **세션 lock**: 작업을 시작할 때 잡고, 끝나는 **모든** 경로에서 푼다. `db_pr discard`는 자동으로 풀고, discard 없이
  끝나면(읽기 전용 모드, 계획만 저장하고 끝냄, 기록하지 않음, 사용자가 그만둠, 오류로 중단) `S/db_pr.py lock release <KEY>`.
- **사실과 추정을 구분한다.** 로그로 확인한 것, 코드로 추정한 것, placeholder 규칙에서 나온 것을 리포트에서 나눠 쓴다.
- 분류 확정, 새 유형·원인 생성, 시그니처·파서 규칙 추가, 수정 상태 변경은 **항상 사용자 확인 후**다. 추천은 하되 대신 정하지 않는다.

## analyze

```
/telephony-triage:analyze <JIRA-KEY> [logcat|bugreport...] [--code <프로필|경로>] [--dry-run] [--jira-file <yaml>] [--analyzer | --no-analyzer]
```

`--jira-file`은 `--dry-run`과 함께일 때만 받는다(실제 PR은 Jira MCP 값으로만 만든다). 없이 주면 거절하고 이유를 말한다.

### Step 0. 사전 점검

1. `S/config.py show` — 사용자 config가 없으면(`user_config: null`) `/telephony-triage:setup`으로 안내하고 끝낸다.
   `--jira-file`이 없는데 `effective.jira.tools.get_issue`가 비어 있으면 **여기서** 멈춘다(lock·스냅샷 전): 도구 이름을 추측하지 말고
   setup의 Jira 도구 매핑을 안내하고, 연습은 `--dry-run --jira-file <yaml>`로 할 수 있다고 알린다.
2. **Jira 키 검사를 가장 먼저**: `S/jira_fields.py check-key <KEY> --db SNAP`(스냅샷이 아직 없으면 `--db <issue_db.path>`).
   종료 코드 1이면 키를 다시 묻는다. 검사 전에는 키를 경로·브랜치·작업 키로 쓰지 않는다(경로 조작 방지).
3. `S/db_pr.py lock acquire <KEY> --command analyze`
   - 다른 작업의 lock(종료 코드 2, 보유자 정보) → 작업 키·명령·마지막 갱신 시각을 보여준다. 사용자가 "그 세션은 끝났다"고 하면
     `lock release <그 작업 키> --force` 후 다시 잡고, 아니면 중단한다.
   - 같은 Jira의 lock이 10분 안에 갱신됨 → "다른 세션이 같은 이슈를 진행 중일 수 있다"고 알리고, 확인받으면 `--take-over`.
4. `S/db_pr.py cleanup --dry-run` — 비정상 종료로 남은 worktree·`tt/*` 브랜치가 있으면 목록을 보여주고, 동의하면 `cleanup --yes`.
5. `JOB/plan.json`이 이미 있으면:
   - `source: analyze`면 이어서 할지/새로 시작할지 묻는다. 다른 `source`(예: `record`)면 **"새로 시작(덮어씀)"만** 허용한다.
   - 어느 쪽이든 `~/.telephony-triage/pending-feedback/`의 **이 Jira** 피드백 파일은 지운다(새 계획의 피드백이 대신한다).
   - 계획에 `pr.number`가 있으면 열린 PR이 있다고 알리고 `sync-pr` 또는 Step 8-2의 브랜치 갱신을 안내한다.
   - 이어받은 계획이 `jira.origin: file`이고 이번 실행이 `--dry-run`이 아니면 Step 2에서 MCP로 다시 읽어 `jira`를 덮는다.
6. pending 피드백(다른 Jira)이 남아 있으면 "이번 PR에 함께 올라간다"고 알린다.
7. 사용자 clone이 dirty하거나 다른 브랜치여도 분석은 막지 않는다(분석은 스냅샷, 쓰기는 별도 worktree).

### Step 1. 이슈 DB 최신화 (읽기 스냅샷)

1. `S/db_pr.py snapshot --job <KEY>` → `pulled: false`면 `pull_skipped_reason`을 한 줄로 알린다(사용자 clone은 그대로다).
2. `S/config.py check --db SNAP` (`--dry-run`이면 `--for dry-run`). `writable: false`면 사유와 함께 **"읽기 전용 모드"**:
   Step 7에서 계획 저장까지만 하고 Step 8을 생략한 뒤 lock을 푼다고 미리 말한다. 파서 백엔드 불일치는 경고로 리포트에 남긴다.
3. 사후 lint: `S/db_lint.py --all --db SNAP`. 오류가 있으면 보여주고 "메인테이너 정리 필요"라고 알린 뒤 분석은 계속한다.
4. 캐시: `S/db_build.py --cache-only --db SNAP`.

### Step 2. Jira 읽기

- MCP: `jira.tools.get_issue`에 매핑된 도구로 이슈를 읽는다. 인자 이름은 그 도구의 입력 스키마를 따른다(구현마다 `key`, `ticket`,
  `issue_key` 등으로 다르다 — 추측하지 말고 스키마를 본다). 응답 JSON을 `JOB/jira_raw.json`에 저장하고
  (`get_comments`가 따로 있으면 응답의 `comments`에 합친다), 곧바로
  `S/jira_fields.py extract JOB/jira_raw.json --origin mcp --db SNAP --meta-out JOB/jira_meta.json --consume`.
- `--jira-file <yaml>`: `S/jira_fields.py extract <yaml> --origin file --db SNAP --meta-out JOB/jira_meta.json`.
- 출력의 `text`(요약·설명·코멘트)는 이미 마스킹됐다. 이후 리포트·키워드·`note` 초안에는 이것만 쓴다. 원문 필드를 계획에 넣지 않는다.
- `missing`에 있는 필드(model, sw, android_version)는 필요할 때 사용자에게 묻는다.
- **발생 시각(`occurred_at`)이 없으면 바로 묻지 않는다**: 로그를 먼저 본다 — `parse_logcat.py parse <logs> --full ... --mask`
  → `match_signatures.py --regress`로 증상 시그니처(S=1)가 충족되는 시각을 찾아 **상위 3개 후보**(시각, 유형 ID·제목)를
  보여주고 고르게 한다. 후보가 없을 때만 시각을 묻는다. 고른 시각으로 Step 3을 ±5분으로 다시 자른다(`--full` 결과는 후보 고르기에만).
- 스냅샷에 이 Jira가 이미 있으면(`S/db_search.py <KEY> --db SNAP`) 기존 분류를 보여주고 재분석할지 묻는다(재분류면 Step 7 `reclassify`).
- `S/db_pr.py preflight --branch issue/<KEY> --search <KEY> --jira <KEY>` → 열린 PR이 있으면 링크를 보여주고 계속할지 묻는다.
- 로그 경로가 없으면 config `log_dir`에서 후보를 보여주고 고르게 한다(Jira 첨부 자동 다운로드는 하지 않는다).

### Step 2-1. 코드 경로 선택 (매 분석마다)

1. 대상 Android 버전: Jira `android_version` → bugreport `build.json`/logcat fingerprint → 없으면 묻는다.
2. `--code`가 있으면 그것(프로필 이름이면 그 `roots`, 경로면 `aosp` 루트).
3. 없으면 `S/code_roots.py suggest --version <v>`의 후보를 번호 목록으로 보여준다: 버전 일치 프로필(추천 표시) → 최근 경로 →
   직접 입력 → **코드 분석 건너뛰기**.
4. `S/code_roots.py validate <roots> --version <v> --db SNAP` — 트리 버전이 대상과 다르면 **경고하고 계속할지 묻는다**.
5. 직접 입력한 경로는 `S/code_roots.py remember <roots>`. 건너뛰면 Step 5를 생략하고 리포트에 "코드 미확인".

### Step 3. logcat 파싱 → 마스킹

- **bugreport**(`.zip`, 또는 첫 줄이 `== dumpstate`): 먼저 `S/parse_logcat.py extract-bugreport <파일> --out JOB/logs/`.
  꺼낸 `logcat-*.txt`만 쓰고 **dumpsys 등 다른 섹션은 읽지 않는다**. `build.json`의 빌드는 Jira SW가 비었을 때 후보로 보여준다.
- 파싱:
  ```
  S/parse_logcat.py parse <logs...> --around <occurred_at> --minutes 5 --rules SNAP/parser-rules \
      --tz <logcat.tz> --year <logcat.year> --mask --json > JOB/events.json
  ```
  `--tz`·`--year`는 `jira_fields.py` 출력의 `logcat`에서 가져온다(`year`가 null이면 `year_source`에 따라 묻거나 파일 시각).
- 머리의 `coverage`를 먼저 본다:
  - `window_in_range: false` → **"로그 범위 밖"**(파일 A~B, 발생 T)으로 보고하고 `--full` 재파싱을 제안한다. "매칭 없음"과 구분한다.
  - `partial` → ±5분 창의 일부만 로그에 있다(짧은 로그·radio 버퍼에서 흔하다). 그대로 진행하고 리포트에 "로그 일부(A~B, 발생 T)"로 적는다.
    발생 시각이 A~B 밖이고 Step 4 후보가 없으면 `--full` 재파싱을 제안한다.
  - `clock_anomalies`가 있으면(재부팅·NITZ 전) 경고하고 Step 2의 증상 스캔 경로를 제안한다.
  - 리포트에 로그 범위와 시계 이상 여부를 적는다.
- 이벤트는 `masked: true`여야 한다. 이후 모든 단계는 이 마스킹된 이벤트만 쓴다.

### Step 4. 시그니처 매칭

```
S/match_signatures.py --db SNAP --events JOB/events.json --jira-meta JOB/jira_meta.json --top 3 --json > JOB/match.json
```

- 후보 `[{type, cause, score, confidence, S, C, evidence[], fix_judgement, related[]}]`와 `pending_causes[]`.
- 분석 모드는 **증상(S=1)이 확인된 유형 안에서만** 원인을 본다. 그래서 슬롯 0에 증상, 슬롯 1에 원인 로그가 있으면 원인은 후보에
  오르지 않는다(`same_phone` 기본 true). 이때 "유형 일치, 원인 미확인"과 판별된 슬롯(phone N)을 보여준다. Jira의 슬롯과 다르면 경고한다.
- S=1, C=0 후보는 "유형 일치, 원인 미확인"으로 표시한다. `pending_causes`는 "참고: 시그니처 없는 기존 원인"으로 보여준다
  (Step 7에서 고르면 `append` + `update-signature` 제안).
- **후보 없음**(S=1인 유형이 하나도 없음): "후보 없음" 절을 만든다 — 도구가 아무것도 안 주면 안 된다(초기 DB에서 가장 흔한 경우).
  (a) 마스킹된 Jira 요약 키워드로 `S/db_search.py "<키워드>" --db SNAP` 상위 3개("설명 기반 유사 후보"),
  (b) 이벤트에서 카테고리별 오류·거부·타임아웃 이벤트 요약(ril_error, ril_timeout, *_rejected 등, 원문 아님),
  (c) Step 3의 범위·시계 판정. 이것들은 점수나 검증에 쓰지 않고 계획 op도 만들지 않는다.

### Step 5. 코드 분석 (Step 2-1에서 건너뛰지 않았을 때)

- 후보의 `code_refs`를 `S/code_roots.py resolve <ref> --roots <roots>`로 연다. `android_versions`가 대상 버전에 맞는 것만.
- 파일이 없으면 `S/code_roots.py find-symbol <symbol> --roots <roots>` → 찾으면 "Android <v>에서 경로 변경: <새 경로>"로
  보고하고 Step 7에서 `add-code-ref`를 제안한다(기존 항목은 고치지 않는다 — 다른 버전에서 유효).
- 근거 로그 문구로 코드를 역검색해 출력 위치·분기 조건·호출 경로를 추적한다. 필요한 부분만 읽는다.
- 새 원인·유형의 `code_refs` 초안은 `<root 키>:<루트 기준 상대 경로>` + `symbol`. **절대 경로를 넣지 않는다.**
- 리포트에 분석한 코드 트리(프로필 또는 경로, 버전)를 적는다.

### Step 5-1. 심층 분석 (카테고리 분석 스킬, 선택)

- config `analyzers.<1위 후보 카테고리>`(`config.py show`의 `effective.analyzers`)가 있을 때만. `--no-analyzer`면 호출하지 않는다.
  `--analyzer`면 묻지 않고 호출한다. 그 밖에는 `when`을 따른다: 기본 `ask` → "심층 분석(<스킬 이름>)을 실행할까요? (토큰 추가 사용)"를 묻고,
  **답을 받기 전에는 어떤 형태로도(입력 형식 확인용 시험 호출 포함) 실행하지 않는다** — 토큰을 쓰는 결정은 사용자 몫이다.
- 입력: 마스킹된 이벤트 JSON 경로(`JOB/events.json`), 로그 경로, 상위 후보(type, cause, score, confidence), 마스킹된 Jira 요약 한두 줄.
  원문 로그를 넘기지 않는다.
- 결과는 `S/mask_pii.py`로 마스킹한 뒤 리포트의 **"심층 분석 (<스킬 이름>)"** 절에 넣는다.
  **분류 후보·점수·순서·검증에는 쓰지 않는다**(기준은 결정적인 스크립트 출력이다). 스킬이 다른 원인을 말하면
  "분석 스킬 의견: …"으로 보여주고 Step 7 선택지에 추가한다.
- 스킬이 없거나, 실패하거나, 사용자가 "아니오"면 "심층 분석 생략: <사유>"를 적고 계속한다.

### Step 6. 분석 리포트

```
## <KEY> 분석
- 분류 후보: <Category> > <유형 ID> <유형 제목> > <원인 ID> <원인 제목> (신뢰도: 높음, 0.92)
- 근거 로그 (마스킹, 3~10줄): <시각> <태그> <메시지>   슬롯: phone <n>
- 로그 범위: <first~last> (발생 시각 포함 여부), 시계 이상 <있음/없음>
- 원인: … (로그로 확인 / 코드로 추정 구분)
- 코드 위치: 파일:라인 + 분기 조건 (분석 트리: <프로필>, Android <v>) | 코드 미확인
- 해결책: <resolution>   해결책 검증: 검증됨 | ⚠ 미검증
- 수정 상태: <fix.status> — <fix_judgement 문구>
- 기존 사례: Jira N건 (최근 키)
- 관련 원인: <related> | 없음
- 기타 후보: <원인 ID> (신뢰도, 이유)
- 참고: 시그니처 없는 기존 원인: … (있을 때)
- 심층 분석 (<스킬>): … | 심층 분석 생략: <사유>
- 열린 PR: <링크> | 없음
- 경고: 백엔드 불일치 / 외부 파서 끔 / placeholder 규칙 기반 결과 (해당할 때)
```

해결책·해결책 검증·수정 상태·기존 Jira 건수·`related`는 후보 원인마다 `S/db_search.py <원인 ID> --db SNAP`에서 가져온다(type.md를 직접 파싱하지 않는다).
수정 상태 판단(`fix_judgement`)은 매처 결과를 그대로 옮긴다. 빌드 비교에서 **"이후"는 같은 빌드를 포함한다(≥)**:
- `fixed`이고 Jira SW ≥ `fixed_in` → **회귀 의심**. Step 7에서 `update-fix`로 open 되돌림을 묻는다.
- `fix-submitted`이고 SW ≥ `fixed_in` → **수정 미흡 의심**. Step 7 참고.
- `fixed_in`에 빌드가 없거나 비교 규칙이 없으면 "판단 불가"로 두 값을 나란히 보여준다.

### Step 7. 분류 확정 → 작업 계획 (반드시 사용자 확인)

"이 이슈를 `<Category> > <유형> > <원인>`으로 분류할까요?" 로 묻고, 답에 따라 op를 고른다.
op 필드·순서 규칙은 `reference/db-authoring.md`의 op 표를 따른다.

| 사용자 결정 | op | 피드백 `decision` |
|---|---|---|
| 1위 수락 | `append {cause}` | `accepted` |
| 다른 기존 원인 (분석 스킬 의견 포함) | `append {cause}` | `chose-other` |
| 이미 이슈 DB에 있는 Jira를 다른 원인으로 | `reclassify {jira, from, to}` | `chose-other` |
| 유형은 맞고 원인이 새것 | `new-cause`(`temp_id: NEW-CAUSE-1`) + fixture·파서 규칙 + **`append {cause: NEW-CAUSE-1}`** | `new-cause` |
| 증상 자체가 새것 | `S/db_add.py similar "<제목>" --db SNAP`로 유사 유형 3개를 먼저 보여준 뒤 `new-type` + `append {cause: <첫 원인 temp_id>}` | `new-type` |
| 원인 미확정 | `unresolved {type}` | `unresolved` |
| 기존 카테고리에 안 맞음 | 가장 가까운 카테고리에 넣는 안 + 새 카테고리 제안 초안(메인테이너 승인 PR로만 생김) | — |

- **사용자가 제안을 거부하면** 다른 후보, 새 원인·새 유형, 원인 미확정 선택지를 다시 보여준다. 임의로 확정하지 않는다.
- **후보 없음**이었으면 선택지는 "새 유형 / 원인 미확정(사용자가 고른 가장 가까운 유형) / 기록하지 않음"뿐이다.
  기록하지 않으면 계획을 만들지 않고 `lock release <KEY>`로 끝낸다.
- 추정만으로 원인을 만들지 않는다. 확정되지 않았으면 `unresolved`를 권한다.
- **새 원인·새 유형**을 고르면 `reference/db-authoring.md`를 읽고 그대로 한다: 작성 규칙에 맞는 초안(제목, 설명, 해결책,
  `resolution_type`, 수정 상태, 시그니처, 본문과 재현 시나리오, 코드·설정 수정 유형이면 recovery/scenario 시그니처 초안),
  파서 규칙 점검(`add-parser-rule`/`update-parser-rule`), `parse_logcat.py cut`으로 만든 마스킹 fixture(`add-fixture kind: positive`).
  모든 초안은 승인받는다.
- 그 밖에 상황에 따라 **물어보고** 넣는 op:
  - 회귀 의심(fixed, SW ≥ fixed_in) → `update-fix {cause, fix: {status: open}, history: {result: reverted, build: <Jira SW>, jira: <KEY>}}`
  - 수정 미흡 의심(fix-submitted, SW ≥ fixed_in): C=1이면 "update-fix → open + 실패 이력(`history.result: failed`)" /
    "이 로그로 verify-fix" 중 고르게 하고, 앞의 것이면 이 로그를 `recurrence` fixture로 넣을지 묻는다. C=0이면 verify-fix로 이어갈지 묻는다
    (verify-fix는 `reference/verify.md`).
  - `related` 후보 → `add-related`. 경로 변경 → `add-code-ref`. 시그니처 수정 → `update-signature`.
  - 해결책을 바꾸자 → `set-resolution` (해결책 검증 상태가 unverified로 초기화된다고 알린다). 폐기·병합 → `set-status`.
- **초안 검증**: 새 원인·유형, 시그니처·파서 규칙 변경이 계획에 있으면
  `S/db_verify.py rules --plan JOB/plan.json --draft JOB/draft --json`. R1~R6 결과표를 보여준다(`skipped`는 통과가 아니다).
  같은 증상의 다른 로그나 정상 로그가 있는지 물어 R6 표본(`extra_samples`)으로 받는다.
  - R3·R4가 **다른 유형의 양성 fixture에서 새 시그니처가 C=1**이 됐다고 하면(결과에 `allow-cause` 초안이 딸려 온다) 사용자에게
    묻는다: (a) 시그니처를 좁힌다 / (b) 그 로그에 실제로 두 현상이 있으므로 `allow-cause {fixture, cause}`를 넣는다.
    (b)면 그 fixture 카테고리의 오너가 리뷰어에 추가된다고 알린다. **몰래 좁히거나 몰래 허용하지 않는다.** 고르기 전에는 진행하지 않는다.
  - `fail`이면 초안을 고치고 다시 검증한다. 통과 전에는 Step 8로 가지 않는다.
- **`note`**: 마스킹된 Jira 요약으로 한 줄 초안을 만들어 확인받는다. 사람 이름·고객명은 넣지 않는다.
- **계획 저장** `JOB/plan.json`:
  ```json
  {"source": "analyze", "schema_version": <SNAP issue-db.config.yaml>, "started_at": "<lock 획득 시각>",
   "base_sha": "<snapshot_sha>",
   "jira": {<jira_fields 출력의 jira 블록>, "date": "<오늘>", "note": "<확인받은 한 줄>"},
   "operations": [...], "extra_samples": [...],
   "feedback": {"date": "<지금, 타임존 포함>", "suggested": [<match.json 후보: {cause, signature, score}>],
                "decision": "<위 표>", "final": "<원인 ID | temp_id | unresolved>"},
   "commit_message": "[<원인 또는 유형 ID>] add <KEY>: <요약>",
   "pr_notes": ["<리뷰어가 알아야 할 결정 한 줄씩: allow-cause 사유, 분석 스킬 의견을 고른 이유 등 (선택). summary가 자동으로 붙이는 것(수동 기록, 사용자 진술, 시그니처 없음, 검증 못 함)은 다시 넣지 않는다>"],
   "pr": {"number": null, "branch": "issue/<KEY>", "head_sha": null}, "included_pending": []}
  ```
  `jira`에는 요약·설명·코멘트 원문 필드를 두지 않는다. 새 원인·유형은 커밋 메시지에 `temp_id`를 쓴다(적용 때 치환된다).
- 읽기 전용 모드이거나 사용자가 "계획만 저장"을 고르면 여기서 `lock release <KEY>`로 끝낸다.

### Step 8. 최신 main 위 적용 → 확인 → 커밋 → PR

**`reference/write-flow.md`를 읽고 그대로 한다.** 요점만:
1. `preflight` → 브랜치 검사(원격 `issue/<KEY>`가 있으면 `reference/sync-pr.md`의 판단도 본다).
2. `db_pr stage JOB/plan.json --wt JOB/wt --branch issue/<KEY>` (`--dry-run`이면 함께). drift(종료 코드 1)는 항목마다
   **계획 값 유지 / main 값 유지(op 삭제) / 직접 입력**을 묻고 계획에 반영한 뒤 `base_sha`를 바꿔 다시 `stage`.
3. `db_pr summary JOB/wt` → **push 전 확인 화면(생략 불가)**: 승인 / 수정 요청(계획 수정 → 다시 stage → 화면 다시) / 전체 diff / 취소.
4. 승인 → `git -C JOB/wt add -A`와 `git -C JOB/wt commit -m "<확인받은 메시지>"`를 **별도 Bash 호출**로.
5. `db_pr publish … --approved <approved_hash>` → PR 링크 → `db_pr discard JOB/wt`(lock 해제).
- `--dry-run`: 확인 화면까지 보여주고 `discard`로 정리한다. pending 피드백을 만들지 않는다. 사용자 clone의 브랜치·워킹 트리·브랜치 목록은 실행 전과 같아야 한다.

## 자주 틀리는 것

- 증상만 맞았는데 원인을 확정한 것처럼 쓰기 → "유형 일치, 원인 미확인"으로 둔다.
- 분석 스킬(LLM) 의견을 점수나 1위 후보에 반영하기 → 의견은 선택지일 뿐이다.
- Jira 설명의 전화번호·IMEI·사람 이름을 리포트나 `note`에 옮기기 → 마스킹된 `text`만, 이름은 빼고.
- 확인 화면 승인 뒤 계획이나 파일을 바꾸고 그대로 push → 바뀌면 다시 stage하고 다시 승인받는다(`publish`가 해시로 막는다).
- `fixed`를 직접 기록하기 → `fixed`는 `verify-fix` 통과로만 생긴다.
- 끝낼 때 lock을 안 풀기 → 다음 작업이 막힌다. 모든 종료 경로에서 푼다.
