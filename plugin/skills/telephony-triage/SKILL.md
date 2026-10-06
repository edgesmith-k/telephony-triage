---
name: telephony-triage
description: Android Telephony 이슈(data·call·network·sim·sms·ims)를 Jira와 logcat/bugreport로 분석해 원인을 찾고 팀 이슈 DB(telephony-issue-db)에 유형·원인별로 분류해 PR로 쌓는다. "로그 분석해줘", "데이터 안 붙어", "콜이 왜 끊겼는지", "SIM 인식 안 됨", "SMS 전송 실패", "IMS 등록 실패", "서비스 없음", "비슷한 이슈 있었어?"처럼 telephony 증상의 원인 분석·분류를 요청하면 반드시 쓴다. record·fix-submitted·verify-fix·validate --cause·sync-pr도 이 스킬이다. 개념 설명, 앱 빌드 에러, 일반 git, 코드 리뷰, Jira 요약만은 쓰지 않는다.
---

# telephony-triage

**스크립트 출력으로 판단하고, 사람 확인을 받고, 계획을 최신 main 위에 적용해 PR로
올린다.** 결과를 설명하고 사용자 결정을 계획에 옮길 뿐 이슈 DB 파일을 직접 쓰지 않는다.

| 언제 | `reference/` |
|---|---|
| Step 7·8, 모든 쓰기 흐름 | `write-flow.md` |
| 새 원인·유형·시그니처·파서 규칙·fixture, Step 7 op 필드 | `db-authoring.md` |
| `record` / `verify-fix`·`fix-submitted`·`validate --cause` / `sync-pr` / 증상만 "비슷한 이슈·이슈 번호?"(search, analyze 아님) | `record.md` / `verify.md` / `sync-pr.md` / `search.md` |
| 로그 해석 | `log-tags.md`, `ril-requests.md`, `fail-causes.md` |

## 실행 규칙

스크립트 호출, 종료 코드(2·S-3 중단), lock, 마스킹, 사용자 확인 지점은 **`reference/rules.md`**. analyze도 그 규칙을 따른다: 첫 스크립트 호출 전에 읽는다.

## analyze

`/telephony-triage:analyze <KEY> [logs...] [--code <프로필|경로>] [--dry-run|--analysis-only] [--more-logs <로그…>] [--jira-file <yaml>] [--failed-step <줄>|--steps-file <path|붙인 목록→JOB/steps-pasted.txt>] [--(no-)analyzer] [--(no-)explore]`

### 1. 드라이버 (Step 0~4)

1. `--jira-file`이 없으면 config(`S/config.py show --keys work_dir,jira.tools`)의 `jira.tools.get_issue`(있으면 `get_comments`)를 그 스키마대로 부른다. 비어 있으면 부르지 말고 멈춘다(추측 금지): setup 매핑 안내(`S/config.py doctor --format markdown` 표), 연습은 `--dry-run --jira-file <yaml>`. hook이 원문을
   `JOB/jira_raw.json`에 두고 마스킹 요약만 보여준다(`saved_to` 없으면 응답을 그 경로에). `--jira-file`은
   `--dry-run`·`--analysis-only` 전용.
2. `S/triage.py run <KEY> --logs <…>` + 위 옵션(analyzer·explore 외) — lock·스냅샷부터 Step 5 `code_refs` resolve까지 한다. stdout(=`JOB/analysis.json`, ≤4KB)과 `JOB/report.md`만 읽는다.
3. `status: needs_input` → `question`·`options`를 보이고 **사용자 답**을 `--answer <kind>=<값>`으로 붙여 같은 명령을 재실행한다. 대신 고르지 않는다.
   `jira`는 1번 뒤, `logs`는 `--logs`를 붙여 재실행. `stopped`는 이유만.
4. 종료 코드 1 → 키를 다시 묻는다.

### 2. 결과 읽기

- `mode: analysis-only`("분석만", "기록하지 마") → Step 6(5-1·5-2 포함)까지, 계획·Step 7·8 없음(lock 해제됨). 추가 로그는 `--more-logs`.
- `mode: read-only` → Step 7 계획 저장까지만이라고 알리고 `snapshot.pull_skipped_reason`, `post_lint.errors`("메인테이너 정리"), `warnings`, `plan.pr_number`(→ `sync-pr`)도 알린다.
- `notes`는 항상 알린다. `code.auto`면 "<roots> 자동 선택, `--code`로 변경 가능"도.
- 로그 범위·`C: 0`·후보 없음은 report.md대로("로그 범위 밖"≠"매칭 없음"). `phones`≠`jira.sim_slot`이면 경고.
- Step 5: `code.resolved` 파일에서 근거 문구의 출력 위치·분기 조건을 찾는다. `code.moved`는
  "경로 변경"으로 알리고 Step 7에서 `add-code-ref`를 묻는다.
- Step 5-1 `analyzer`(값이 있으면)·5-2 `explore`(후보 없음·원인 미확인만): `--no-…`·`never`면 생략, `--analyzer`·`--explore`·`always`면
  실행, 아니면 토큰 추가를 알리고 묻는다(답 전 실행 금지). 둘 다 묻게 되면 "심층 분석과 탐색 분석을 할까요?" 한 질문(`explore.md`), 한쪽만이면 그쪽만. 5-1은 `analyzer.skill`을 Skill로 부른다(입력 `files.events`·로그 경로·상위 후보·마스킹 요약).
  결과는 `S/mask_pii.py` 후 report.md `심층 분석 (…)` 줄에, 다른 원인 의견은 Step 7 선택지로. 5-2는 실행이 정해진 뒤에만
  `S/triage.py explore <KEY>`를 부르고 그것이 만든 `JOB/timeline.md`만 `explore.md`대로 읽는다.

### Step 6. 리포트

`JOB/report.md`의 `TODO(LLM)` 칸만 채워 보인다. 결정적 칸은 두고, `analysis.json` `must_show` 줄은 **글자 그대로** 답에 넣는다(요약·생략 금지).
원인은 **로그로 확인/코드로 추정/placeholder 규칙 결과**를 나누고 반대 근거와 다음 확인을 적는다.
`fix_judgement`의 `regression-suspected`·`fix-insufficient`는 Step 7에서 묻고, `undetermined`는 SW·`fixed_in`을 나란히.

### Step 7. 분류 확정 → 계획 (반드시 사용자 확인)

`<Category> > <유형> > <원인>` 분류를 묻는다.

| 사용자 결정 | op | `decision` |
|---|---|---|
| 1위 수락 / 다른 기존 원인 | `append {cause}` | `accepted` / `chose-other` |
| DB에 있는 Jira를 다른 원인으로 | `reclassify {jira, from, to}` | `chose-other` |
| 원인이 새것 | `new-cause`(`temp_id`) + 파서 규칙·fixture + `append` | `new-cause` |
| 증상이 새것 | `S/db_add.py similar` 3개를 먼저 보이고 `new-type` + `append` | `new-type` |
| 원인 미확정 | `unresolved {type}` | `unresolved` |

- 거부하면 다른 기존 원인·새 원인·새 유형·원인 미확정을 다시 보인다. 추정만으로 원인을 만들지 않는다. 후보 없으면 "새 유형 / 원인 미확정 / 기록하지 않음"만.
- 새 원인·유형은 `db-authoring.md`대로 초안을 만들고 모두 승인받는다(fixture는 `parse_logcat.py cut --evidence JOB/match.json`).
- 물어보고 넣는 op: 회귀 의심·수정 미흡의 `update-fix`(실패 이력) 또는 verify-fix, `add-related`, `add-code-ref`, `update-signature`,
  `set-resolution`(검증 상태 초기화 안내), `set-status`.
- 시그니처·파서 규칙·새 원인이 있으면 `S/db_verify.py rules --plan JOB/plan.json --draft JOB/draft` 표를 보인다(`skipped`는 통과
  아님). 다른 유형 fixture에서 새 시그니처가 걸리면 **좁힐지 `allow-cause`할지 사용자가 고를 때까지** 멈춘다.
- `note` 한 줄을 확인받고 `write-flow.md` §계획 형식으로 `JOB/plan.json`에 저장한다. 기록하지 않음·읽기 전용·계획만 저장이면
  `S/triage.py release <KEY>`로 끝낸다.

### Step 8. 적용 → 확인 → 커밋 → PR

`write-flow.md` 그대로: `db_pr stage --then-summary`(출력 = 확인 화면, 생략 불가) → 승인 → `db_pr publish --commit --and-discard`.
직접 `git commit` 없음. 취소·dry-run만 `discard`.
`fixed`는 `verify-fix` 통과로만 기록한다.
