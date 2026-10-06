# record (수동 기록)

```
/telephony-triage:record <JIRA-KEY> [--cause <원인 ID> | --new-cause <유형 ID> | --new-type <category> | --unresolved <유형 ID>]
                         [--fixture <logcat>] [--resolved-fixture <logcat>] [--dry-run] [--jira-file <yaml>]
                         [--failed-step <한 줄>] [--steps-file <파일>]
```

사용자가 이미 스스로 해결한 이슈를 **로그·코드 분석과 매칭 없이** 히스토리에 남긴다. 분류와 내용은 사용자가 정한다.
하지만 **쓰기 경로와 검증은 analyze와 같다** — 지름길이 없다. 수동 기록이 검증을 건너뛰면 근거 없는 원인·해결책이 팀 DB에
쌓이고, 나중에 매처가 그것을 믿게 되기 때문이다. 확인 화면과 PR에 "수동 기록"을 밝히는 것도 리뷰어가 근거 수준을 알게 하려는 것이다.

SKILL.md의 "실행 규칙"(스크립트 호출, `--db` 명시, 종료 코드, 마스킹, lock)을 그대로 따른다.
새 원인·유형·시그니처·fixture를 만들면 `db-authoring.md`를 함께 읽는다. 적용 이후는 `write-flow.md`.

## 1. 사전 점검

- `config.py show`(없으면 setup 안내) → `jira_fields.py check-key <KEY>`(맞지 않으면 다시 묻는다) →
  `db_pr lock acquire <KEY> --command record`(보유 중이면 `write-flow.md` 1번) →
  `db_pr cleanup --dry-run`.
- `WD/<KEY>/plan.json`이 있으면: `source: record`면 이어서/새로 시작을 묻고, 다른 `source`면 "새로 시작(덮어씀)"만.
- `db_pr snapshot --job <KEY>` → `config.py check --db SNAP`(`--dry-run`이면 `--for dry-run`). **쓰기 불가면 사유를 보여주고
  lock을 풀고 멈춘다**(record는 쓰기만 하는 흐름이라 읽기 전용 모드가 없다).
- `--jira-file`은 `--dry-run` 없이도 받는다(`jira.origin: file`). 확인 화면에 "Jira 메타데이터: 오프라인 파일"이 나온다.

## 2. Jira 메타데이터

MCP `jira.tools.get_issue`(매핑이 없으면 추측하지 말고 setup 안내)를 부르면 hook이 원문을 `WD/<KEY>/jira_raw.json`에 두고 마스킹 요약만 보여준다(결과에 `saved_to`가 없으면 응답을 그 경로에 저장). `jira_fields.py extract WD/<KEY>/jira_raw.json --origin mcp --db SNAP --consume --comments last:3`(파일이면 `<yaml> --origin file`)로 읽는다.
`--failed-step <한 줄>`·`--steps-file <파일>`(선택)이 있으면 `extract`에 그대로 넘긴다(우선순위 cli > Jira 자동 > 파일). 실패 스텝은 선택 값이라 없어도 묻지 않고 멈추지 않으며, 파일을 읽지 못하면 `warnings`만 보여주고 진행한다. 값은 보조 정보일 뿐 분류에 쓰지 않는다.
`--steps-file`은 txt/csv·html(`report.html`)·zip(안의 파일 하나)이다. 개발자가 스텝 목록을 대화에 붙이면 `WD/<KEY>/steps-pasted.txt`에 쓰고 그 경로를 `--steps-file`로 준다(도구가 읽을 때 마스킹, 커밋하지 않는다, discard·lock release가 지운다). 시험 장비 시각은 시계가 단말과 다를 수 있어 `record`에서는 실패 스텝 이름만 쓴다(`--clock-offset`은 analyze의 구간 계산용).
`jira` 블록(model, sw, android_version, carrier, occurred_on)을 채우고, `missing`은 사용자에게 묻는다. `date`는 오늘.
`note`는 마스킹된 요약으로 한 줄 초안을 만들어 확인받는다(사람 이름·전화번호·IMEI 금지).

## 3. 중복 확인

`db_pr preflight --branch issue/<KEY> --search <KEY> --jira <KEY>`.
- `jira_in_main` → **중단하고** 기존 분류(`db_search.py <KEY> --db SNAP`)를 보여준 뒤 유지(기록하지 않음, lock 해제) /
  재분류(`reclassify {jira, from, to}`)를 묻는다. 중복 파일을 만들지 않는다.
- 열린 PR → 링크를 보여주고 계속할지 묻는다(계속해도 같은 Jira 파일을 두 PR이 만들게 된다는 점을 알린다).

## 4. 분류 정하기

- 옵션이 있으면 그대로: `--cause` → `append`, `--new-cause <유형>` → `new-cause`, `--new-type <cat>` → `new-type`,
  `--unresolved <유형>` → `unresolved`. ID가 스냅샷에 있고 `active`인지 확인한다(`db_search.py <ID> --db SNAP`).
- **옵션이 없으면 대화형**: 증상과 원인을 한두 문장으로 받아 `db_search.py "<증상 문장 또는 키워드>" --db SNAP`와
  `db_add.py similar "<증상 제목>" --db SNAP`(유사 유형 상위 3개)로 후보를 보여주고 고르게 한다:
  기존 원인 / 기존 유형의 새 원인 / 새 유형 / 원인 미확정.

## 5. 내용 받기

작성 규칙과 초안 형식은 `db-authoring.md`. 모든 초안은 승인받는다.

- **새 원인·유형**: 원인 title·description·resolution·resolution_type·본문(재현 시나리오 포함). 새 유형이면 유형 title·summary·dir_slug.
- **시그니처** — 새 원인·유형은 판별 시그니처가 필수다. 사용자에게 받거나(마스킹된 로그 문구 기준) 초안을 제안한다.
  - **새 유형은 증상 시그니처가 없으면 진행하지 않는다.** "시그니처는 나중에"라고 해도 유형에는 예외가 없다(없으면 analyze가 그
    유형을 영영 찾을 수 없다). 증상 로그 문구를 받거나, 증상이 보이는 로그를 `--fixture`로 받아 초안을 만든다.
  - 새 원인은 사용자가 **명시적으로** "원인 시그니처는 나중에"를 고를 때만 `signatures_pending: true`로 기록한다. 그 결과를 알린다:
    lint 경고, 매처가 판별 못 함, 해결책 unverified 고정, 월간 리뷰 대상. 사용자가 명시하지 않았는데 시그니처가 비어 있으면
    진행하지 않고 시그니처를 요청한다.
  - 시그니처가 있으면 파서 규칙 점검(`db-authoring.md`)으로 `add-parser-rule`/`update-parser-rule` 초안.
- **fixture** (`--fixture <logcat>`) — 마스킹된 최소 구간을 잘라 `add-fixture {for, kind: positive, path}`:
  - 기존 원인(`--cause`): `parse_logcat.py parse <log> --full --rules SNAP/parser-rules --mask ...` → `match_signatures.py --regress`
    결과를 파일로 저장하고 `parse_logcat.py cut <log> --evidence <match.json> --out WD/<KEY>/fixtures/cut-1.log --rules SNAP/parser-rules` (parse와 같은 로그를 같은 순서로).
  - 새 원인·유형: 새 시그니처는 계획에만 있어 스냅샷 매처로 근거를 찾을 수 없다. 발생 시각(없으면 사용자가 지정한 시각)으로
    `parse_logcat.py cut <log> --around <시각> --out ...`. 그 fixture가 새 시그니처를 실제로 충족하는지는 7번 초안 검증(R1·R2)이 확인한다.
  - fixture가 없으면 R1·R2가 `skipped: fixture 없음`(검증 못 함, 리뷰 대상)이 된다고 알린다.
  - 원인이 `signatures_pending`이면 그 fixture는 `"<유형 ID>:unresolved"` 기대값으로 회귀에 들어간다.
- **수정 정보**(선택) — "이미 고쳤다"면 `ref`(fix_ref_regex)와 `fixed_in`(브랜치 필수, 빌드 선택)을 받아 `fix-submitted`로:
  새 원인은 `cause.fix`, 기존 원인은 `update-fix`. 기존 원인이 이미 `fixed`면 `update-fix`를 넣지 않고 "이미 검증된 수정이 있다"고 보여준다.
  **`fixed`는 기록하지 않는다.** "검증까지 끝났다"고 해도 `fixed`는 수정 빌드 로그의 `verify-fix` 통과로만 생긴다고 안내한다.
- **해결책 효과**(선택) — "해결책이 효과 있었다"면 근거를 묻는다. 근거가 될 수 있는 것은 둘뿐이다:
  1. 기록 대상이 **아닌** 다른 Jira 키(그 원인의 Jira 기록으로 존재해야 한다).
  2. `--resolved-fixture <logcat>`의 `db_verify resolution` 판정 **passed**. 기존 원인은
     `db_verify.py resolution --db SNAP --cause <ID> <log>`, 새 원인은
     `db_verify.py resolution --plan WD/<KEY>/plan.json --draft WD/<KEY>/draft --cause NEW-CAUSE-1 <log>`
     (먼저 계획을 저장해야 한다). passed면 결과의 흔적 시각으로 `cut --around <ts> --tz UTC`(`--year` 없이, 판정과 같은 시각 기준 — `verify.md`)해 `add-fixture {kind: resolved}`와
     `verify-resolution {cause, verification: {method, evidence: [<fixture 경로 또는 Jira 키>], by, date}}`를 넣는다(`status` 없음 — `db_verify` `suggested_ops` 그대로).
     **순서: `new-cause`/`set-resolution` 뒤에.** `signatures_pending` 원인은 해결책을 검증할 수 없다.
  - 기록 대상 Jira 자신은 근거가 아니다(그 Jira의 해결 진술은 사용자 진술이다). 근거가 없으면 `unverified`로 둔다.
    사용자가 그래도 주장하면 `unverified`를 유지하고 "근거: 사용자 진술"을 남긴다 — 새 원인은
    `cause.resolution_verification.method`, 기존 원인은 Jira 기록 `note`. 확인 화면·PR에 "사용자 진술 — 카테고리 오너 리뷰 필요"가 나온다.
- **code_refs**(선택) — `<root 키>:<상대 경로>` + `symbol`. 절대 경로는 거부하고 다시 받는다.

## 6. 작업 계획

`WD/<KEY>/plan.json`: `source: record`, `schema_version`, `started_at`, `base_sha`(스냅샷 SHA), `jira`(origin 포함),
`operations`(새 원인·유형이면 `new-cause`/`new-type` 뒤에 이 Jira 기록용 **`append {cause: <temp_id>}`**를 꼭 넣는다 — `new-cause`는 원인만 만든다),
`feedback: {date: <지금>, suggested: [], decision: manual, final: <원인 ID | temp_id | unresolved>}`,
`commit_message: "[<ID>] record <KEY>: <요약>"`, `pr: {number: null, branch: issue/<KEY>, head_sha: null}`, `included_pending: []`.
계획을 만들 때 `~/.telephony-triage/pending-feedback/`의 **같은 Jira** 파일을 지운다.

## 7. 초안 검증

새 원인·유형 또는 시그니처·파서 규칙 변경이 있으면 `db_verify.py rules --plan WD/<KEY>/plan.json --draft WD/<KEY>/draft`(draft는 도구가 만들고 지운다 — 미리 만들지 않는다)로 검증하고
결과표(실행/건너뜀과 사유)를 보여준다. `fail`이면 고친다. 다른 유형의 양성 fixture에서 C=1이면 "시그니처 좁히기 / `allow-cause`"를 묻는다.

어떤 검증이 도는지(`db_pr stage`가 모두 돌린다):

| 조건 | 실행 | 건너뜀 표시 |
|---|---|---|
| 항상 | lint 전체, Jira 중복(main + 열린 PR), check-ids, 마스킹, 생성 파일, **전체 회귀(R4)** | — |
| 새 원인·유형 + 시그니처 있음 | R1~R5 | fixture 없으면 R1·R2 `skipped: fixture 없음` → "검증 못 함" |
| 새 원인 `signatures_pending` | R4, lint 경고 | R1~R3 `skipped: 시그니처 없음(pending)` |
| 새 유형 + 첫 원인 pending | 증상 시그니처 R1·R3·(규칙 변경 시 R5)·R4 | 원인 R1~R3 pending |
| 기존 원인에 Jira만(`append`) | 항상 항목만 | R1~R3·R5 `skipped: 해당 없음` |

## 8. 적용 → 확인 → 커밋 → PR

`write-flow.md` 그대로. 브랜치 `issue/<KEY>`. 확인 화면 머리에 **"구분: 수동 기록 (record)"**, "로그·코드 분석: 하지 않음",
실행한 검증과 건너뛴 검증(사유), 해당하면 "검증 못 함 — 리뷰 대상", "시그니처 없음 — 매칭 불가, 리뷰 대상",
"사용자 진술 — 카테고리 오너 리뷰 필요". PR 본문에도 같다(`db_pr summary`가 만든다). `--dry-run`이면 확인 화면까지 보여주고 `discard`.

- **취소하면 manual 피드백은 보관하지 않고 버린다**(pending 디렉토리에 복사하지 않는다). 수동 기록은 제시된 후보가 없어 통계에
  쓰지 않고, 취소는 분류가 불확실하다는 뜻일 수 있으며, 다른 Jira의 PR에 섞이면 리뷰가 헷갈리기 때문이다. 계획은 남겨서 같은 Jira로 다시
  record하면 이어서 할 수 있다.
