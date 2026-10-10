# 이슈 DB 작성 지침 (새 원인·유형·시그니처·파서 규칙·fixture)

새 원인·유형·시그니처·파서 규칙·해결책을 바꿀 때 읽는다. 규칙은 이슈 DB `CONTRIBUTING.md`와 같고 스크립트가 검사한다. 여기엔 **쓰는 판단**만 둔다. 나머지는 스크립트가 알려 준다:

- op별 필드·형식: `SNAP/schema/plan.schema.json`(원인은 `causeBody`)과 stage의 `계획 형식 오류 (operations/<n>, op=<이름>): 빠진 필드 […]; 허용 밖 필드 […]` 메시지. 적용 규칙 위반(Reject)·drift는 stage 출력(설계 문서: `contracts.md §작업 계획`).
- 원인 기본값 `SNAP/templates/cause.yaml`. R1~R6 결과·`skipped` 사유·`allow_cause_drafts`·`suggested_ops`: `db_verify` 출력. fixture 이름·번호·기대값은 적용 때 정해지고 틀리면 `db_lint`·`db_regress`가 말한다.

## 1. 무엇을 추가할지

고르는 기준: 증상·원인 모두 기존과 같으면 `append`, 증상은 같고 원인이 다르면 `new-cause`, 증상 자체가 없으면 `new-type`(+ 첫 원인), 증상은 맞지만 원인 미확정이면 `unresolved`, 이미 있는 Jira를 다른 원인으로 옮기면 `reclassify`.

op 필수 키 (`op` 외, plan.schema.json 기준):
- `append`: cause
- `unresolved`: type
- `new-cause`: temp_id, type, cause, body — cause: title·description·signatures·resolution·resolution_type
- `new-type`: temp_id, category, type, first_cause, body, dir_slug — type: title·summary·symptom_signatures
- `add-fixture`: for, kind, path — kind: positive·negative·fixed·resolved·recurrence·extra; fixed·recurrence면 build 필수; 선택 build·expect·occurred_at
- `update-signature`: owner, kind, signature
- `add-parser-rule`: file, rule
- `update-parser-rule`: file, key, rule
- `set-resolution`: cause, resolution
- `verify-resolution`: cause, verification — verification: evidence·by·date
- `allow-cause`: fixture, cause
- `reclassify`: jira, from, to
- `update-fix`: cause, fix
- `add-code-ref`: cause, code_ref
- `set-status`: id, status
- `signature`: id·window_sec 필수, 선택 must_match·must_event·must_not_match·same_phone·sequence
여기 없는 op·세부 제약은 `SNAP/schema/plan.schema.json`

- 새 유형 전에 **전체 카테고리**에서 유사 유형 상위 3개를 보인다(`db_add.py similar "<제목>" --db SNAP`). 비슷하면 새 원인 쪽을 권한다.
- 원인이 확정되지 않았으면 원인을 만들지 않고 `unresolved`. **추정만으로 원인을 만들지 않는다.**
- 어느 카테고리에도 안 맞으면 가장 가까운 카테고리 + `tags` 안과 새 카테고리 제안 초안을 함께 보인다. 새 카테고리는 메인테이너의 직접 편집 PR로만 생긴다.
- 새 원인·유형·시그니처·파서 규칙·해결책은 초안을 모두 사용자에게 보이고 **승인받은 뒤에만** 계획에 넣는다.

## 2. 작성 규칙

- 유형 `title`은 **증상**("~하지 않음 / ~됨", 30자 이내, `GLOSSARY.md` 표준어), `summary`는 한 문장. 원인 `title`은 **원인** 명사구(20자 이내), `description`은 왜 그 증상이 나는지 한 문장.
- `resolution`은 **행동 지시 1~2문장**, "~한다"로 끝. 워크어라운드면 앞에 `[WA]`. `resolution_type`은 스키마 enum.
- `fix.status`는 `open | fix-submitted | wont-fix | not-a-bug`로만 시작한다. `fix-submitted`면 `ref`+`fixed_in`(브랜치 필수). **`fixed`로 시작할 수 없다.**
- `resolution_verification`은 새 원인·`resolution`이 바뀐 원인 모두 `unverified`. `verified`는 같은 계획의 `verify-resolution`(근거 Jira 또는 `resolved` fixture)뿐이다. 기록 대상 Jira 자신을 근거로 쓰지 않는다. **사용자 진술만 있으면 unverified + method `근거: 사용자 진술`.** 미검증 해결책은 리포트·README에 "⚠ 미검증".
- **시그니처**: 증상용·원인용 분리. 새 유형·원인은 판별 시그니처 필수(예외: record에서 사용자가 명시한 원인 `signatures_pending`). **새 유형의 증상 시그니처는 예외 없음.** 마스킹된 로그에서 실제 확인한 문구로만 쓴다(`.*error.*`·마스킹될 값·`<CELL#1>` 토큰 번호 고정 금지). 반복되는 복잡한 패턴은 extractor + `must_event`. 매처는 마스킹 뒤 텍스트에 돈다.
  `must_*`는 AND·시그니처끼리는 OR, `fields` 값은 정규식 fullmatch(부분 일치는 `.*X.*`), `same_phone`(기본 true)은 DDS처럼 슬롯을 가로지르는 원인만 false, `sequence`는 항목 `id` 순서.
- `recovery_signatures`는 이 원인에 특정한 정상 흐름(계기가 풀리는 이벤트 + 정상 동작을 `sequence`로, 정상 로그 어디에나 맞는 동작만은 금지), `scenario_signatures`는 재현 시나리오 흔적(원인 시그니처 복사·부정 금지). 코드·설정 수정 유형은 `fixed` 전환 전 둘 중 하나 필수.
- 본문 로그 예시는 마스킹 후 5~15줄, 원인별 상세에만. 재현 시나리오는 verify-fix가 보인다.
- `code_refs`는 `<root 키>:<상대 경로>` + `symbol`(절대 경로 금지), 버전별 경로는 항목을 나눠 `android_versions`.
- Jira `note`는 사용자가 확인한 한 줄. 사람 이름·고객명·원본 식별자 금지. Jira 요약·설명·코멘트 원문은 어디에도 저장하지 않는다.
- 로그·fixture는 마스킹된 것만.

## 3. 계획에 넣는 흐름

- 새 원인·유형은 **임시 ID**(`NEW-CAUSE-<n>`, `NEW-TYPE-<n>`)로 쓴다. 적용 때 최신 main 기준 번호로 치환된다.
- op는 **순서대로** 적용된다. `new-cause`·`new-type`은 원인·유형만 만든다. 이 Jira의 기록은 **`append {cause: NEW-CAUSE-1}`**을 함께 넣어야 생긴다.
  전형적인 순서: `add-parser-rule`(필요하면) → `new-cause` → `add-fixture {for: NEW-CAUSE-1}` → (`verify-resolution`) → `append` → (`allow-cause`).
- `body`에는 `### <ID> <title>` 제목 줄을 넣지 않는다(`db_add`가 붙인다). `new-cause.body` 항목: `- **로그 예시**:`(마스킹 5~15줄)·`확인 방법`·`재현 시나리오`·`해결책`·`코드 위치`·`비고`(`SNAP/templates/type.md`). `new-type.body`는 `## 증상`·`## 증상 판별 방법`까지.
- record 피드백은 `suggested: []`, `decision: manual`.
- **`계획 형식 오류`가 나면** 결정 내용(op·값)은 바꾸지 않고 메시지가 말한 키만 고쳐 다시 stage한다.
- drift는 항목마다 계획 값 유지 / main 값 유지(op 삭제) / 직접 입력을 사용자가 고른다(`write-flow.md` 3번).

## 4. 파서 규칙과 fixture

파서 규칙(`parser-rules/`)은 이슈 DB에 있고 새 유형은 **PR 하나에 유형 + 파서 규칙 + fixture가 함께** 들어간다. extractor `id`는 시그니처가 참조하므로 바꾸지 않는다. 이벤트 이름은 접두어 없이 쓴다.

**새 원인·유형을 계획할 때 점검** (부족하면 op 초안을 만들어 승인받는다): 시그니처가 참조하는 태그가 `tags.yaml`에 있나(없으면 파서가 그 줄을 버려 매칭이 안 된다), RIL 요청/unsol이 `ril.yaml`에 있나, cause 코드·reason·state 값이 필요한가(extractor 추가·`update-parser-rule`), 원인 fixture가 있나(`cut` 뒤 `add-fixture kind: positive`). 부족한 것은 `add-parser-rule` 등 op로 만든다.

`chose-other`는 C=1일 때만 `extra` fixture를 제안(C=0 양성은 회귀 실패 → `update-signature` 검토).

- 규칙만으로 표현이 안 되면 원인은 추가하되 **엔진 개선 요청 초안**(필요 기능, 마스킹 예시, 원인 ID)을 보인다.
- 기존 extractor를 바꾸면 그것을 쓰는 모든 원인의 fixture 회귀가 통과해야 하고 R5가 "승인 필요"가 될 수 있다. `parser-rules/` 변경은 메인테이너 리뷰 필수다.
- fixture 자르기: 근거 기반(기존 원인) `parse_logcat.py cut <log> --evidence <match.json> --out WD/<KEY>/fixtures/cut-<n>.log --rules SNAP/parser-rules [--tz --year]`(parse와 같은 로그·순서). 시각 기반(새 원인·유형, resolved/fixed) `cut <log> --around <ISO 시각> --seconds 30 --out …`. 원인마다 양성 1개 이상, 판별에 필요한 최소 구간(20~100줄).
- `also_allowed`는 **같은 로그에 실제로 두 현상이 있을 때만** 쓴다.

## 5. 검증 결과를 읽을 때

`db_verify.py rules --plan <plan> --draft <draft>`(초안)와 stage가 R1~R6 표를 낸다. 판정은 스크립트 출력이다.

- `skipped`는 통과가 아니다. 사유와 함께 "검증 못 함 — 리뷰 대상"으로 표시한다. 해결책만 바뀌면 R1~R5는 `skipped: 해당 없음`이고 검증 상태만 unverified.
- **R3·R4에서 다른 유형 양성 fixture에 새 시그니처가 C=1이 되면** 사용자가 고를 때까지 push하지 않는다. 몰래 좁히지도 허용하지도 않는다. 결과의 `allow_cause_drafts`(op 그대로)를 선택지와 함께 보인다.
  - (a) **시그니처 좁히기**: fixture와 걸린 시그니처 전역 키를 보이고 대상 원인 fixture에만 있는 조건(`must_not_match`·구체적인 `fields`·`sequence`)을 더한 안을 제시, 다시 초안 검증.
  - (b) **허용**: 그 로그에 실제로 두 현상이 다 있으면 `allow-cause {fixture, cause}`. fixture `.expect.yaml` 변경이 확인 화면에 나오고 그 오너가 리뷰어가 된다. 계획 `pr_notes`에 `allow-cause: <fixture>에 <현상>이 실제로 함께 있음 (<근거 로그 한 줄, 마스킹>)`을 넣는다.
- R6 `fail`은 막지 않는다(`blocking: false`). 결과를 보이고 진행 여부는 사용자가 고른다.
- 음성 fixture에 걸린 경우(R3)는 허용 선택지가 없다 — 시그니처를 좁힌다.

## 6. 수정 상태와 해결책 검증

- `fixed`는 수정이 **검증까지** 끝난 상태다: `verify-fix` passed로만 기록한다(빌드 있는 `fixed_in` 필요). `fix-submitted`는 검증 대기, `wont-fix`는 본문 비고에 사유.
- 매처의 수정 판단은 `analysis.json`의 `fix_judgement`를 따른다(**"이후"는 같은 빌드 포함 ≥**).
- 해결책 검증 근거는 (1) 적용 뒤 재현 안 된 **다른** Jira, (2) `db_verify resolution` passed 로그.

## 7. 카테고리 경계, 상태, 브랜치

- 주 카테고리는 **사용자가 겪는 증상** 기준이다(이슈 DB `GLOSSARY.md` §카테고리 경계). 원인이 다른 카테고리면 원인 `related`, 유형 `secondary_categories`로 잇는다.
- ID는 main에 들어간 뒤 바꾸지 않는다. 병합·폐기는 `status`(`deprecated | merged-into:<ID>`)로, 삭제 금지.
- `signatures_pending: true`는 record에서 사용자가 명시할 때만(매칭 불가, 해결책 unverified 고정).
- 브랜치 이름은 흐름 문서(`record.md`·`verify.md`·`write-flow.md`)가 알려 준다(설계 문서: `contracts.md §브랜치`). PR 하나에 Jira 하나.
- **기존 분류 가져오기**(`source: import`): record 규칙과 같되 새 유형·원인 모두 시그니처 필수(pending 불가), 해결책 unverified로 시작. 브랜치 `import/<category>-<n>`, PR당 새 유형 10개 이하.
- **분석 스킬** 결과는 리포트 보조일 뿐 분류·점수·검증에 쓰지 않는다. 스킬이 DB에 없는 원인을 말해도 그것만으로 원인을 만들지 않는다 — 사용자가 고르면 `new-cause` 흐름(시그니처 초안·검증 포함).
