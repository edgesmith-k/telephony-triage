# 검증·수정 상태 흐름: validate --cause, fix-submitted, verify-fix

세 흐름 모두 **판정·입력 확인 → 사용자 확인 → `write-flow.md`의 공통 쓰기 절차 PR**이다. SKILL.md의 "실행 규칙"을 따른다. 아래 "lock"은 `db_pr lock acquire <작업 키> --command <흐름>`이고 보유 중이면 `write-flow.md` 1번.
판정은 `db_verify.py`의 출력으로만 한다(항상 회귀·검증 모드: 파일 전체, 모든 active 원인 독립 평가, bonus 0).
**시각 기준**: 회귀·검증 모드는 로그 시각을 연도 없이 UTC로 읽는다. 그래서 `satisfied_traces`·`trace`의 `ts`는 "파일 시계 그대로(연도 2000)"다.
이 시각으로 fixture를 자를 때는 `parse_logcat.py cut <log> --around <ts> --tz UTC`(**`--year` 없이**)로 같은 기준을 쓴다. 리포트에는 파일 시계 시각(월-일 시:분:초)으로 보여준다.
사용자 말이나 LLM 판단으로 판정을 대신하지 않는다 — `fixed`와 `verified`는 팀 전체가 믿는 상태라 로그 근거가 있어야 한다.

수정 상태 흐름:
```
open ─(fix-submitted)─▶ fix-submitted ─(verify-fix passed)─▶ fixed
  ▲                        │ ▲ partial: 상태 유지 + 이력            │
  └────(verify-fix failed)─┘                                       │
  └─────────(회귀: fixed_in 이후(같은 빌드 포함) 재발, analyze Step 7)─┘
```
코드·설정 수정 유형 = `resolution_type`이 `framework-bug`, `vendor-ril`, `modem`, `carrier-config`.

---

## validate --cause (해결책 검증)

```
/telephony-triage:validate --cause <원인 ID> <적용 후 logcat...>
```

1. 작업 키 `verify-res-<원인 ID>-<YYYYMMDD>`(오늘): `db_pr lock acquire <작업 키> --command validate-cause` →
   `db_pr snapshot --job <작업 키>` → `config.py check --db SNAP`(쓰기 불가면 lock 풀고 멈춤).
   `db_search.py <원인 ID> --db SNAP`로 원인을 찾는다. `resolution_verification.status`가 이미 `verified`면 재검증인지 묻는다.
2. 로그가 bugreport면 `parse_logcat.py extract-bugreport`로 logcat만 꺼낸다. 판정:
   `db_verify.py resolution --db SNAP --cause <ID> <logcat...> --json` → `{judgement, reason, C, S, satisfied_traces[{signature, kind, ts}], suggested_ops[]}`.

   | 판정 | 조건 |
   |---|---|
   | passed | 원인 시그니처 불충족 + (recovery 있으면 충족 / 없으면 증상 불충족이고 scenario 충족) |
   | failed | 원인 시그니처 충족 |
   | unknown | recovery·scenario 시그니처가 없음, 흔적 없음, 증상 남음, 구간 부족 |
3. **unknown** → 이유와 필요한 조건(어떤 시그니처를 추가하거나 어떤 로그를 받아야 하는지)을 안내하고 **기록하지 않는다**.
   `lock release <작업 키>`. **failed** → 해결책이 효과가 없다고 보고하고 `set-resolution`이나 새 분석(analyze)을 제안한다.
   계획을 만들지 않고 `lock release <작업 키>`.
4. **passed** → `parse_logcat.py cut <log> --around <satisfied_traces의 시각> --out WD/<작업 키>/fixtures/resolved-1.log` 후 계획
   `WD/<작업 키>/plan.json`(`source: validate-cause`, `jira: null`):
   `add-fixture {for: <ID>, kind: resolved, path}` → `verify-resolution {cause: <ID>, verification: {method: <요약>, evidence: [<fixture 경로>, (선택) Jira 키], by, date}}`(`status` 없음 — `db_verify` `suggested_ops` 그대로).
   커밋 메시지 `[<ID>] verify-resolution: <요약>`.
5. 공통 쓰기 절차. 브랜치 `verify-res/<원인 ID>-<YYYYMMDD>`, 리뷰어는 원인 카테고리 오너.

---

## fix-submitted (수정 CL 반영)

```
/telephony-triage:fix-submitted <원인 ID> --ref <CL> --fixed-in <branch>[:<build>] [--fixed-in ...]
```

1. 작업 키 `fix-submit-<원인 ID>`: lock → snapshot → `config.py check`. 원인을 찾아 `fix.status`를 본다:
   - `open` / `fix-submitted`(빌드 추가·ref 변경) → 진행.
   - `wont-fix` / `not-a-bug` → "수정 CL을 기록하면 상태가 `fix-submitted`로 바뀐다"고 알리고 확인 후 진행.
   - `fixed` → lock 풀고 중단. 회귀라면 analyze Step 7로 open 되돌림을 안내한다(`fixed` → `fix-submitted`는 op가 거부한다).
2. `--ref`가 `fix_ref_regex`(SNAP `issue-db.config.yaml`)에 맞는지, `--fixed-in` 브랜치가 `build_compare`의 `branch_regex` 중 하나에 맞는지
   확인한다. **빌드가 없으면** "빌드가 없으면 회귀 판정도 verify-fix 통과도 할 수 없다"고 알리고 계속할지 묻는다(나중에 같은 커맨드로 빌드 추가).
3. 코드·설정 수정 유형인데 `scenario_signatures`·`recovery_signatures`가 모두 없으면 "나중에 verify-fix를 하려면 둘 중 하나가 필요하다"고
   알리고 지금 `update-signature`로 함께 추가할지 묻는다(추가하면 `db-authoring.md` 규칙, 초안 검증).
4. 계획 `WD/fix-submit-<원인 ID>/plan.json`(`source: fix-submitted`, `jira: null`):
   `update-fix {cause, fix: {status: fix-submitted, ref, fixed_in: [{branch, build?}]}}` (+선택 `update-signature`).
   빌드는 `sanitize_build`를 거친 값이 적용 때 쓰인다. 커밋 메시지 `[<원인 ID>] fix-submitted: <ref>`.
5. 공통 쓰기 절차. 브랜치 `fix-submit/<원인 ID>`.

---

## verify-fix (코드 수정 검증)

```
/telephony-triage:verify-fix <원인 ID> <수정 빌드 logcat...> [--jira <검증 Jira>]
```

1. **빌드 확인을 먼저** 한다(작업 키에 빌드가 들어가므로): Jira SW(`--jira`면 `jira_fields.py`로), bugreport `build.json`, 또는 logcat
   fingerprint. 로그가 bugreport면 먼저 추출한다. 빌드를 모르면 묻는다.
2. 작업 키 `verify-fix-<원인 ID>-<sanitize된 build>`: lock → snapshot → `config.py check`. 여기서부터 중단하거나 기록하지 않고 끝나는
   **모든** 경로는 `lock release <작업 키>`.
3. 원인 확인(`db_search.py <ID> --db SNAP`):
   - `fix.status`가 `fix-submitted`(재검증이면 `fixed`)가 아니면 중단.
   - `signatures_pending` 원인이면 중단하고 판별 시그니처 추가(`update-signature`)를 안내.
   - 코드·설정 수정 유형인데 scenario·recovery 시그니처가 **둘 다 없으면 판정 전에 중단**하고 시그니처 추가를 안내한다.
     사용자가 원하면 `update-signature`를 이 계획에 넣고 진행할 수 있다 — 그때 판정은 `--plan <p> --draft <draft>`로 시그니처를 적용한
     트리에서 하고, 흔적 시그니처가 R1 흔적 검사를 통과해야 판정이 쓰인다(`withheld: true`면 판정 불가).
   - `fixed_in`에 빌드 있는 항목이 없으면 중단하고 `fix-submitted`로 빌드를 추가하라고 안내.
4. `db_pr preflight --branch verify-fix/<원인 ID>-<build> --search <원인 ID>` → 열린 PR(다른 verify-fix, fix-submit)을 보여준다.
5. 판정: `db_verify.py fix --db SNAP --cause <ID> <logcat...> --build <build> --json`
   → `{judgement, reason, C, S, trace, satisfied_traces, other_candidates, build_check{status}, fix_status, user_confirmation_required, suggested_ops}`.
   - 종료 코드 2(빌드가 fixed_in보다 이전, 상태 부적합 등) → 사유를 보여주고 중단.
   - `build_check.status: undetermined` → 비교 규칙이 없거나 파싱 불가. 두 값을 보여주고 사용자에게 이후 빌드인지 묻는다.
   - **시나리오 흔적**(`trace`)과 원인 본문의 "재현 시나리오"를 함께 보여주고, 사용자가 그 시나리오를 수행한 로그인지 확인받는다.
     흔적 시그니처가 있는데 흔적이 없으면 **판단 불가**다. 사용자가 "시나리오 했어"라고 해도 흔적을 대신하지 않는다.
   - 유일한 예외 `user_confirmation_required`(비코드 유형 `user-setting`·`network`·`hw`이고 scenario·recovery 시그니처가 **둘 다 없음**)
     → 사용자 확인을 받고 그 사실을 `verification.note`에 "사용자 확인(흔적 시그니처 없음)"으로 남긴다. 코드·설정 수정 유형에는 이 예외가 없다(3번에서 중단).
6. 판정별 계획 `WD/<작업 키>/plan.json`(`source: verify-fix`, `jira: null`). `verification`: `{build, date, by, jira?, fixture?, scenario_evidence?, note}`.

   | 판정 | 조건 | 계획 |
   |---|---|---|
   | passed | 흔적 충족, 원인·증상 불충족, recovery 있으면 충족 | `cut --around <흔적 시각>` → `add-fixture {kind: fixed, build}` + `verify-fix {result: passed, verification{..., fixture: fixtures/<ID>.fixed.<build>.log}}` → `fixed` |
   | failed | 원인 시그니처 충족(재발) | `verify-fix {result: failed}` → open, 이전 `ref`·`fixed_in`은 `verification_history`에 보존. 재발 로그를 `recurrence` fixture로 넣을지 묻는다 |
   | partial | 흔적 충족, 원인 불충족, 증상 남음 | `verify-fix {result: partial}` → 상태 유지 + 이력. `other_candidates`를 보여주고 남은 증상은 `analyze`로 새로 분석하라고 안내. **"통과로 기록" 선택지를 제시하지 않는다** |
   | unknown | 흔적 없음, 필수 시그니처 없음, 구간 부족 | 계획을 만들지 않는다. 필요한 로그 조건(시나리오 수행 방법, 필요한 시그니처)을 안내하고 `lock release` |

   `suggested_ops`를 초안으로 쓴다: `<parse_logcat cut 결과 경로>` 자리(`add-fixture.path`, `verification.fixture`/`evidence`)에
   cut한 파일 경로를 **똑같이** 넣으면 적용 때 `fixtures/<ID>.fixed.<build>.log` 같은 이슈 DB 경로로 함께 바뀐다. `by`는 config
   `user.ghe_id`. `optional: true` op는 사용자가 원할 때만 넣고 그 키는 지운다. 커밋 메시지 `[<ID>] verify-fix <result>: <build>`.
   (validate --cause의 `verify-resolution`도 같은 방식이다.)
7. 공통 쓰기 절차. 브랜치 `verify-fix/<원인 ID>-<build>`. 판정 근거는 계획 `pr_notes`에 넣으면 확인 화면과 PR 본문에 나온다:
   `판정: <judgement> — <reason>`, `시나리오 흔적: <전역 키> @ <시각>`, `빌드 비교: <build> ≥ <fixed_in 빌드>`, 필요하면 마스킹된 근거 로그 1~3줄.
