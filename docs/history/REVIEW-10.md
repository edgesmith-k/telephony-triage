# 10차 변경안 — 9차 문서 세트 검토(Q1~Q10) 반영

기준: 9차 문서 세트(`telephony-triage-docs-v9.zip`). 검토 항목 Q1~Q10 (🔴2, 🟡8, 🟢9).
사용자 결정: **Q2 (b) 직접 편집 브랜치로 내림**, **Q4 엄격 유지 + `also_allowed`**, **Q7 대상 OS = Ubuntu**, **Q1 런타임 모드 판별 삭제(사내 전용, `site-defaults.yaml` 필수)**.

적용 방법: 아래 항목을 순서대로 반영하고, 끝나면 `CHANGES.md`에 "10차 변경" 절로 이 파일 내용을 옮긴다. `REVIEW-OPEN.md`는 그대로(0건).
개수 변화: 계획 `source` 값 12 → 9 (`migrate`, `category`, `cleanup` 삭제). 커맨드 12, hook 7, 검증 단계 5, eval 41, 트리거 12/7은 그대로.

---

## 🔴

### Q1. 런타임에서 모드 판별 삭제 — `plugin/site-defaults.yaml` 필수

문제: 설치된 플러그인(마켓플레이스 캐시 경로)에는 `SITE_PROFILE.md`·`.local-draft`가 없어서, "`SITE_PROFILE.md`가 있으면 사내" 규칙을 코드에 넣으면 팀원 PC가 전부 사외로 판별되고 `site-defaults.example.yaml`이 조용히 읽힌다.

결정: 런타임 코드는 **모드를 판별하지 않는다.** `plugin/site-defaults.yaml`이 없으면 setup과 모든 커맨드가 "사내 기본값 없음(S-3 미완료)"으로 멈춘다(종료 코드 2). `site-defaults.example.yaml`은 코드가 절대 읽지 않는다. 사외 테스트·eval은 **테스트 헬퍼가 example을 `site-defaults.yaml`로 복사한 임시 플러그인 루트**를 만들어 쓴다(`tests/helpers/make_plugin_root.py`, `${CLAUDE_PLUGIN_ROOT}`를 그 경로로 준다). "사내 모드/사외 초안 모드"라는 용어는 **개발 세션(CLAUDE.md 모드 판별)에만** 남긴다.

반영 위치:
- `15-local-draft.md §15.1`: 설정 우선순위 문단을 "사용자 config > `plugin/site-defaults.yaml` > 코드 내장 기본값. `site-defaults.yaml`이 없으면 setup·모든 커맨드가 멈춘다. `site-defaults.example.yaml`은 코드가 읽지 않고, 사외 테스트 헬퍼가 복사해서 쓴다"로 교체. "사내 모드(`SITE_PROFILE.md` 있음)에서 …" 문구 삭제.
- `15-local-draft.md §15.2`: 표 아래에 "사외 테스트는 `tests/helpers/make_plugin_root.py`가 만든 임시 플러그인 루트(example 복사본 포함)로 돈다. 개발 레포의 `plugin/`에는 `site-defaults.yaml`을 만들지 않는다" 추가. `db_lint`의 `origin: synthetic` 경고 조건은 "`site-defaults.yaml`이 있고 그 안에 `synthetic_allowed: false`(기본)"로 바꾼다(example 복사본은 `synthetic_allowed: true`).
- `15-local-draft.md §15.4` 체크리스트: "`plugin/site-defaults.yaml`이 없고 example만 있음" 유지.
- `contracts.md §3.2` 설정 읽기: "(사외 초안 모드는 `site-defaults.example.yaml`)" 삭제 → "`site-defaults.yaml`에서만 읽는다. 없으면 종료 코드 2".
- `contracts.md §기존 자산 연결 계약` 설정 우선순위 줄: "`site-defaults.example.yaml`은 사외 초안 모드에서만 읽는다" → "코드는 읽지 않는다(테스트 헬퍼 전용)".
- `02-config.md` §5.3 앞 인용문: 같은 문구로 교체. setup 4번 "사내 모드에서는 이름이 `mock-`로 시작하는 서버 제외" → "`site-defaults.yaml`의 `jira.exclude_servers`(기본 `[mock-*]`, 테스트 복사본은 `[]`)에 맞는 서버 제외".
- `01-architecture.md §3` 트리: `site-defaults.example.yaml` 주석을 "테스트 헬퍼가 복사해서 쓰는 모의 기본값. 코드는 읽지 않음"으로. `tests/helpers/make_plugin_root.py` 추가.
- `11-phases.md` Phase 6 완료 기준: "사내 모드 흉내(`SITE_PROFILE.md` 있음)에서 `site-defaults.yaml`이 없으면 멈추고 `mock-` 서버를 후보에서 제외" → "`site-defaults.yaml`이 없는 플러그인 루트에서는 setup과 `config.py check`가 종료 코드 2로 멈춘다. 테스트 헬퍼 루트(example 복사본)에서는 `mock-jira`가 후보에 포함되고, `exclude_servers: [mock-*]`인 복사본에서는 제외된다".
- `11-phases.md` Phase D0 할 일에 `tests/helpers/make_plugin_root.py` 추가. Phase 2·13(모의 백엔드·eval)은 "테스트 헬퍼 루트에서" 문구 추가.
- `14-site.md` S1: 변경 없음. `GUIDE.md §3`: "사외 테스트는 example을 복사한 임시 플러그인 루트로 돈다" 한 줄.

### Q2. `migrate`·`category`·`cleanup` 계획 삭제 — 직접 편집 브랜치로 통일 (결정 (b))

문제: 9차에서 replay 전용 op를 뺐지만 `source: migrate | category | cleanup`과 "migrate PR이 `db_pr` 경유" 문구가 남아 있다. 스키마 마이그레이션(`schema/`·`templates/`·모든 type.md)과 새 카테고리(config·CODEOWNERS·GLOSSARY·디렉토리)는 남은 op로 표현할 수 없다.

결정: 마이그레이션·새 카테고리·사후 정리는 **메인테이너의 직접 편집 브랜치**다(`06 §6.3` "계획이 없는 브랜치"와 같은 절차). `migrate` 커맨드는 로컬 브랜치에서 `db_migrate --to <N>`을 실행하고 `validate`·push 절차를 안내하는 데까지만 한다. `review`·`move`·`import`는 기존 op로 표현되므로 계획 방식을 유지한다.

반영 위치:
- `contracts.md §상태 값` 계획 `source`: `analyze | record | import | fix-submitted | verify-fix | validate-cause | review | move` (9개). `migrate`, `category`, `cleanup` 삭제.
- `contracts.md §3.2`:
  - `config.py check --for write|migrate|dry-run` → `--for write|dry-run`. `migrate` 설명 삭제. 대신 "`validate`와 pre-commit은 `migrate/schema-v<N>` 브랜치(브랜치 이름으로 판별)에서 스키마·생성기 버전 불일치를 차단하지 않는다(마이그레이션이 버전을 올리는 커밋이므로). gh 인증만 확인한다" 추가.
  - `db_pr stage` 5번: "계획 `source: migrate`면 `--for migrate`" 삭제.
  - `db_migrate.py`: `--to <N> [--dry-run]`은 **현재 브랜치 워킹 트리(`--db`)** 를 바꾼다고 명시. `migrate` 커맨드는 cwd가 이슈 DB clone이고 현재 브랜치가 `migrate/schema-v<N>`이며 깨끗할 때만 실행한다(아니면 종료 코드 2). 이것이 "사용자 clone은 바꾸지 않는다" 원칙의 **명시적 예외**(메인테이너가 자기 브랜치에서 직접 실행)임을 12장에 적는다.
  - 세션 lock 흐름 목록에서 "리뷰/마이그레이션 PR" → "review/move 계획 PR".
  - `db_pr.py 세부` `snapshot`/`stage` 호출자 목록에서 migrate 삭제.
- `contracts.md §브랜치`: `chore/fix-db-*`, `migrate/*`, `category/*` 행의 "만드는 주체"에 "(직접 편집, 계획 없음)" 표시. `import/` 행 "만드는 주체" 칸을 "카테고리 오너(계획), 리뷰 필수"로 고침(🟢 Q-g).
- `06-collaboration.md §6.4`: "결과는 `migrate/schema-v<N>` PR 하나로 올린다 (`db_pr` 경유)" → "메인테이너가 `migrate/schema-v<N>` 브랜치를 만들고 `/telephony-triage:migrate --to <N>`을 실행한 뒤 `validate` → 커밋 → push한다(직접 편집 브랜치 절차, 6.3)". "`migrate` 커맨드는 … `config.py check --for migrate`" 문장 삭제. "op 형식이 바뀌는 마이그레이션은 `upgrade_plan()` 제공" 유지.
- `06-collaboration.md §6.3` ①행 "적용 시" 대상에서 migrate 삭제. `§6.10` 새 카테고리 PR: "메인테이너 승인 PR로만" 유지, "직접 편집 브랜치 `category/<key>`. `validate` 통과 후 push" 명시.
- `07-workflow.md` 공통 쓰기 절차: 머리말 "작업 계획으로 만드는 review/migrate/category/move PR" → "review/move PR". 1번 "(`migrate`면 `--for migrate`)" 삭제. 마지막 불릿에 "마이그레이션·새 카테고리·사후 정리 브랜치도 계획이 없으므로 같은 직접 편집 절차다" 추가.
- `09-commands.md`: `migrate` 행을 "`migrate --to <N> [--dry-run]`: 메인테이너용. cwd가 이슈 DB clone이고 현재 브랜치가 `migrate/schema-v<N>`이며 깨끗할 때 `db_migrate --to <N>` 실행 후 `validate`·push 절차 안내. PR은 만들지 않는다"로. 아래 불릿의 "이슈 DB에 쓰는 커맨드(… `migrate`)" 목록에서 `migrate` 제거, "`migrate`는 lock을 잡지 않고 스냅샷도 옮기지 않는다(자기 브랜치 워킹 트리만 바꿈)" 추가. "`--for migrate`" 문장 삭제.
- `02-config.md §5.3` 마지막 불릿: "버전을 올리는 `migrate` PR은 예외다(`config.py check --for migrate`)" → "예외는 `migrate/schema-v<N>` 브랜치의 직접 편집(6.4)".
- `08-safety.md §9` 표 4번(생성 파일 정합성)·pre-commit: `migrate/schema-v<N>` 브랜치에서는 `generator_version` 불일치를 차단하지 않는다는 예외 추가(브랜치 이름 판별).
- `01-architecture.md §3.1`: `db_pr.py` 호출자에서 "review/migrate/category/move PR" → "review/move PR". `db_migrate.py` 호출자 "`migrate`, `sync-pr`" 유지. `config.py` 책임에서 `migrate` 삭제.
- `11-phases.md`:
  - Phase 7 할 일 "손으로 쓴 `tests/fixtures/plans/*.json`(analyze·record·migrate 계획 포함)" → "(analyze·record·import·review 계획 포함)". 완료 기준의 "`source: migrate` 계획은 `generator_version` 불일치 상태에서도 `stage`를 통과한다" 삭제.
  - Phase 9 완료 기준: "`migrate/schema-v<N>` PR이 버전 불일치 상태에서도 `db_pr` 경유로 올라간다(`--for migrate`)" → "`migrate/schema-v<N>` 브랜치에서 `migrate --to <N>` 실행 후 pre-commit과 `validate`가 버전 불일치를 차단하지 않고 통과하며, 다른 브랜치에서는 여전히 차단된다".
  - Phase 13 읽을 문서 변경 없음.
- `CLAUDE.md` 12장: "도구가 만드는 이슈 DB 변경은 …" 불릿 뒤에 "예외: 스키마 마이그레이션·새 카테고리·사후 정리는 메인테이너가 자기 로컬 브랜치에서 직접 편집한다(`migrate` 커맨드는 그 브랜치의 워킹 트리를 바꾼다)" 추가. 1장 표 "협업" 행 제외 목록은 그대로.
- `13-actions.md §13.5` 2번: "`migrate/ci-<mode>` PR로 … (공통 쓰기 절차 동일)" → "(직접 편집 브랜치)".
- `99-deferred.md` 머리말에 "계획 기반 마이그레이션·카테고리 PR(전용 op 또는 stage 특수 경로)도 v1에서 뺐다" 한 줄과 "되살릴 때 바꿀 곳"에 `source: migrate|category` 추가.
- `10-skill-eval.md`: 영향 없음(eval 13은 "쓰기를 막고 안내"라 그대로).

## 🟡

### Q3. D0를 두 모드 공통으로

문제: Phase 2·6·13 완료 기준이 D0 산출물(모의 site 백엔드, 모의 골든, `mock-jira`)을 전제하는데 "사내 처음부터" 모드에는 D0가 없다.

결정: D0는 모드와 무관하게 필수. 사내 처음부터 모드는 "Phase 0 → D0 → 1~14".

반영 위치: `CLAUDE.md` 모드 표 "사내 처음부터 | Phase 0 → D0 → 1~14". `11-phases.md` Phase D0 제목에서 "(사외 초안 모드에서만)" 삭제, 첫 줄에 "두 모드 공통. 사내 처음부터 모드에서는 Phase 0 다음에 한다(모의 환경은 사내에서도 테스트에 필요하다)". `15-local-draft.md §15.3` 표 D0 행 비고에 "사내 처음부터 모드도 수행". `GUIDE.md §2`는 변경 없음.

### Q4. 양성 fixture 기대값: DB 전체 배타 유지 + `also_allowed`

문제: `contracts §fixture`("유일한 1위")와 `04 §5.11 (4)`·`05` R2("C=1인 원인이 그것뿐")의 정의가 다르다. 후자로 가면 새 원인의 시그니처가 다른 유형의 기존 양성 fixture에서 실제 현상을 잡기만 해도 R4가 깨지고, 작성자가 남의 fixture 기대값을 못 고쳐 시그니처를 억지로 좁히게 된다.

결정: 정의는 **"대상 원인이 C=1이고, `also_allowed`에 없는 다른 active 원인은 모두 C=0"** 으로 통일(DB 전체). `.expect.yaml`에 `also_allowed: [<원인 ID>...]`를 추가한다. 새 원인 PR이 기존 fixture와 충돌하면 작성자가 그 fixture의 `.expect.yaml`에 `also_allowed`를 추가하는 op를 계획에 넣고, 그 fixture 소속 카테고리 오너가 리뷰어에 추가된다.

반영 위치:
- `contracts.md §fixture` 기대값 표: `expect_top: <원인 ID>` 설명을 "그 원인이 C=1이고, `also_allowed`를 제외한 다른 모든 active 원인은 C=0(신뢰도 표현은 쓰지 않는다, Q5)"로. 새 행 `also_allowed: [<원인 ID>...]` — "이 fixture에서 C=1이어도 되는 다른 원인. 같은 로그에 실제로 두 현상이 있을 때만 쓴다. 대상 원인 자신, 같은 유형의 다른 원인은 넣을 수 없다(같은 유형 안의 충돌은 시그니처 설계 문제)". `expect_top: "<유형 ID>:unresolved"`도 "`also_allowed` 제외 모든 원인 C=0"으로. `expect_not`은 그대로.
- `contracts.md §작업 계획` op 표: 새 op `allow-cause` — 필수 필드 `fixture`(유형 디렉토리 기준 경로), `cause`(허용할 원인 ID 또는 `temp_id`); 대상 `.expect.yaml`(없으면 기본 기대값으로 생성 후 추가); 적용 규칙 "`also_allowed`에 추가. 대상 fixture가 양성·recurrence·extra·`unresolved` 기대값일 때만"; ID 참조 필드 `cause`. drift 표에 "`allow-cause`: 대상 fixture가 없어지거나 `.expect.yaml`의 `also_allowed`가 바뀜" 추가. renumber 참조(원인 ID)에 "`.expect.yaml`의 `also_allowed`" 추가.
- `04-parser-matching.md §5.11 (4)`: "판정은 순위가 아니라 C 값과 신뢰도로 한다" → "판정은 S/C 값만으로 한다(Q5). 양성 = 대상 C=1 + 그 밖의 원인(`also_allowed` 제외) C=0". 기대값 요약 문장 수정.
- `05-verification.md` R2 통과 기준: "그 원인이 유일한 1위(C=1인 원인이 그것뿐), 신뢰도 medium 이상" → "그 원인이 C=1, `also_allowed`를 제외한 다른 모든 active 원인이 C=0". R3(원인) 통과 기준 "대상 원인이 C=0(점수 medium 미만)" → "대상 원인이 C=0. 단 그 fixture의 `also_allowed`에 대상 원인이 있으면 제외". R4 설명에 "R4 실패가 다른 유형 양성 fixture에서 대상 원인 C=1 때문이면, 결과에 그 fixture와 `allow-cause` op 초안을 함께 낸다" 추가.
- `07-workflow.md §Step 7` 초안 검증 뒤: "R3·R4가 다른 유형의 양성 fixture에서 새 시그니처가 C=1이 된 것을 보고하면, (a) 시그니처를 좁힐지 (b) 그 로그에 실제로 두 현상이 있어 `allow-cause`를 넣을지 사용자에게 묻는다. (b)면 그 fixture 소속 카테고리 오너가 리뷰어에 추가된다". `§record` 7번에도 같은 문장. Step 8-5 확인 화면 예시 "리뷰어" 줄 아래 "(다른 카테고리 fixture에 `also_allowed`를 추가했으면 그 카테고리 오너 포함)".
- `02-config.md §5.3` 리뷰어 계산: "계획에 `allow-cause`가 있으면 대상 fixture 경로의 카테고리 오너를 더한다".
- `03-issue-db.md §5.7 (4)` 체크리스트에 "`also_allowed`가 대상 원인 자신·같은 유형 원인·없는 ID를 가리키지 않음 (`db_lint`)" 추가. `§5.2` 디렉토리 예시의 `.expect.yaml` 주석에 `also_allowed` 언급.
- `06-collaboration.md §6.6` 리뷰 항목에 "`also_allowed` 누적: 한 fixture에 3개 이상, 또는 한 원인이 5개 이상의 fixture에서 허용됨 → 시그니처가 너무 넓은지 검토" 추가.
- `11-phases.md`: Phase 1 `schema/`에 `.expect.yaml` 스키마(`also_allowed`) 추가. Phase 5 lint 오류 주입 목록에 "`also_allowed`에 자기 원인·같은 유형 원인·없는 ID". Phase 7 완료 기준에 "`allow-cause` op가 `.expect.yaml`을 만들거나 갱신하고, drift(다른 PR이 같은 파일의 `also_allowed`를 바꿈)가 잡힌다". Phase 10 완료 기준에 "다른 유형의 양성 fixture에서 C=1이 된 새 시그니처는 R4에서 걸리고 결과에 `allow-cause` 초안이 나오며, `also_allowed`를 넣으면 통과한다".
- `10-skill-eval.md` eval 42 추가: "새 원인 시그니처가 다른 카테고리의 기존 양성 fixture에서 C=1(그 로그에 실제로 두 현상 있음) → R4 실패와 `allow-cause` 초안을 보여주고, 사용자가 허용을 고르면 `.expect.yaml` 변경이 확인 화면에 나오고 그 카테고리 오너가 리뷰어에 추가된다". eval 개수 41 → **42**로 `CLAUDE.md` 문서 지도·11.0, `11-phases.md` Phase 13, `14-site.md §14.4` 개수 목록, `GUIDE.md §3`, `15-local-draft.md §15.4`, `CHANGES.md` 갱신.

### Q5. 회귀·검증 모드 판정을 S/C 불리언으로만

문제: "C=1 ⇔ medium 이상"은 `cause_weight(0.6) ≥ confidence.medium(0.6)`일 때만 성립한다. `scoring` 값을 바꾸면 R2·R3·기대값 판정이 뒤집힌다.

결정: 회귀·검증 모드의 모든 판정 문구에서 점수·신뢰도를 빼고 S/C만 쓴다. 점수는 결과표의 참고 값으로만 낸다.

반영 위치: `contracts.md §fixture` 기대값 표(Q4에서 함께), `04-parser-matching.md §5.11 (4)`("점수는 base만으로 정해진다 … 판정은 순위가 아니라" 문단을 "판정은 S/C만 쓰고 점수는 표시용"으로), `05-verification.md` R2·R3·`db_verify resolution`/`fix` 판정 표(이미 "충족/불충족"이라 변경 없음 확인), `07-workflow.md` Step 8-5 확인 화면 예시 "R2 양성 ✅ (1.00) / R3 음성 ✅ (최고 0.40)" → "R2 양성 ✅ / R3 음성 ✅ (C=0 12/12)". `11-phases.md` Phase 3 완료 기준 "`--regress`에서는 그 원인이 0.6(medium)으로 나온다" → "C=1로 나온다(점수 0.6은 참고 값)". `CHANGES.md` "그 밖의 정리"의 "검증 점수를 회귀 모드 기준(R2 1.00, R3 최고 0.40)으로 맞춤" 항목은 이력이므로 그대로.

### Q6. review/move 계획 PR을 만드는 커맨드가 없다

결정: v1에서는 카테고리 오너가 리뷰 리포트를 보고 **Claude와 함께 계획 파일을 작성**해서 공통 쓰기 절차로 올린다(커맨드 없음). 작업 키는 브랜치 이름 규칙(`review-<category>-<YYYY-MM>`, `move-<옛 ID>-to-<새 ID>`).

반영 위치: `06-collaboration.md §6.6` 첫 문단 "(직접 편집 후 `validate`, 또는 작업 계획으로 `db_pr` 경유)" → "(직접 편집 후 `validate`, 또는 리포트의 조치를 계획 파일(`source: review`, op: `set-status`·`update-signature`·`reclassify`·`set-resolution`·`allow-cause`)로 적어 공통 쓰기 절차로 올린다. 계획 작성은 Claude가 돕고, 별도 커맨드는 없다)". `§6.6` 병합 단락에 `move` 계획 op 조합(`new-cause`(내용 복사)·`add-fixture`(옛 fixture 경로)·`set-status merged-into`·`reclassify`) 명시. `07-workflow.md` 공통 쓰기 절차 표 위에 같은 문장. `docs/review-guide.md` 내용(Phase 1)에 "계획 파일로 올리는 법" 항목 추가(`11-phases.md` Phase 1 할 일).

### Q7. 대상 OS = Ubuntu

결정: 사외·사내 모두 Ubuntu(Linux). POSIX 가정을 명시하고 다른 OS는 지원하지 않는다.

반영 위치: `01-architecture.md §3` 의존성 불릿에 "실행 환경: Ubuntu(Linux). 셸 스크립트(`.githooks/pre-commit`)는 `#!/bin/sh`, PATH 스텁·홈 경로·실행 비트 모두 POSIX 기준. 다른 OS는 v1 범위 밖" 추가. `14-site.md` S15 항목의 "OS" → "Ubuntu 버전, `python3` 버전(3.10+), git 버전". `15-local-draft.md §15.2` 표에 "OS | Ubuntu 기준으로만 시험 | S15" 행. `11-phases.md` Phase D0 완료 기준에 "Ubuntu에서 `.githooks/pre-commit`이 실행 비트와 함께 커밋된다(`git ls-files -s`로 100755 확인)". `GUIDE.md §4` 미리 준비할 것에 "Ubuntu PC(다른 OS 미지원)".

### Q8. 사내 보완 모드의 Phase 14

결정: `15-local-draft.md §15.5` 표에 **S-7 = Phase 14(배포·파일럿)** 행을 추가하고 할 일·완료 기준을 `11-phases.md` Phase 14에서 옮겨 적는다(11-phases 쪽은 "사내 보완 모드는 S-7"로 참조만).

반영 위치: `15-local-draft.md §15.5` 표 S-7 행(읽을 것: `14-site.md` S2, `06 §6.6·6.9`). `CLAUDE.md` 모드 표 "사내 보완 | S-1~S-7". `GUIDE.md §2` 그림·§4 표에 S-7. `11-phases.md` Phase 14 첫 줄 "사내 보완 모드는 `15-local-draft.md §15.5` S-7".

### Q9. pending 피드백과 같은 작업 키 lock

- `03-issue-db.md §5.4 (3)`: "같은 Jira의 작업 계획을 재개하면" → "같은 Jira의 계획을 만들거나 재개하면(analyze 새로 시작·이어서 하기, record 모두)". `07-workflow.md §Step 0` 계획 있음 불릿: "이어서 하면 … 지운다" → "이어서 하든 새로 시작하든 이 Jira의 pending 피드백을 지운다". `contracts.md §작업 계획` "이어서 하기" 문단 같은 문구.
- `contracts.md §3.2` 세션 lock: "같은 작업 키의 lock이면 이어받는다" → "같은 작업 키의 lock이면: `updated_at`이 10분 이내면 '다른 세션이 같은 작업을 진행 중일 수 있다'고 보여주고 사용자가 확인해야 이어받는다(`acquire --take-over`). 10분이 넘었으면 이어받는다". `07-workflow.md §Step 0`·`§record` 1번에 같은 분기. `11-phases.md` Phase 6 완료 기준에 "같은 작업 키의 최근 lock은 `--take-over` 없이는 종료 코드 2".

### Q10. 수정 상태 전이의 빈 칸

- `contracts.md` op 표 `verify-fix`: `partial` 규칙에 "대상이 `fixed`(재검증)면 `fixed` 유지 + `partial` 이력(원인 시그니처는 여전히 불충족이므로 이 원인의 수정은 유효하다고 본다)". `05-verification.md (2)` 5번 부분 통과에 같은 문장.
- `07-workflow.md §fix-submitted` 1번: "`wont-fix`·`not-a-bug`면 '수정 CL이 있으면 상태가 바뀐다'고 알리고 사용자 확인 후 `fix-submitted`로 진행(`update-fix`가 허용). `fixed`면 중단". `contracts.md` op 표 `update-fix`에 "`wont-fix`/`not-a-bug` → `fix-submitted`는 허용, `fixed` → `fix-submitted`는 거부(먼저 `verify-fix` 실패나 회귀 의심으로 open으로 되돌린다)".
- `07-workflow.md §record` 5번 수정 정보: "기존 원인이 이미 `fixed`면 `update-fix`를 넣지 않고 '이미 검증된 수정이 있다'고 보여준다".
- `contracts.md` op 표 `verify-resolution`: "`evidence`의 Jira 키는 `jira_key_regex`에 맞아야 하고 이슈 DB에 그 원인의 Jira 기록으로 존재해야 한다(없으면 apply 거부). fixture 경로는 존재해야 한다". `03-issue-db.md §5.7 (4)` 체크리스트와 `01 §3.1` `db_lint` 책임에 "evidence 존재 검사" 추가. `11-phases.md` Phase 5 lint 오류 주입 목록에 "없는 Jira/fixture를 가리키는 evidence".

## 🟢

- a. `07-workflow.md §Step 8-3` `git worktree add … origin/<base_branch>` → `<기준 SHA>` (`contracts` stage 4번과 일치).
- b. `CLAUDE.md 11.0` 첫 불릿: "각 Phase를 시작할 때 `11-phases.md`의 … (항상 `contracts.md` 포함)"을 "사외 초안·사내 처음부터 모드에서는 …; 사내 보완 모드(S 단계)는 `15.5`의 '읽을 것'만"으로.
- c. `01-architecture.md §3` 트리에 `docs/site/`, `tests/site/`(둘 다 `[사내 전용, SITE_PATHS]`) 추가. `db_pr discard --keep-branch` 옵션 삭제(`contracts.md §3.2`, 쓰는 흐름 없음).
- d. `sync` 커맨드 작업 키 `sync` 명시(`09-commands.md`, `contracts.md §3.2` 세션 lock 흐름 목록).
- e. 피드백 파일의 `date`와 파일명 timestamp는 계획의 `feedback.date`(Step 7 저장 시각)를 쓴다. `contracts.md §작업 계획` 예시 `feedback`에 `"date": "2026-09-27T18:30+09:00"` 추가, `03 §5.4 (3)`에 "재적용해도 바뀌지 않는다".
- f. R1 흔적 검사의 음성 fixture 범위를 "그 카테고리의 음성 fixture 전부"로 통일(`11-phases.md` Phase 10 완료 기준 "모든 음성 fixture" → "그 카테고리의 모든 음성 fixture").
- g. `contracts.md §브랜치` `import/` 행 "만드는 주체" 칸 수정(Q2에 포함).
- h. `@SITE_PROFILE.md` import: 파일이 없을 때 오류·경고가 나는지 D0 실험 항목에 추가(`15-local-draft.md §15.2` "사내 Claude Code 기능" 행, `11-phases.md` Phase D0 할 일). 경고가 나면 사외 초안에서는 빈 `SITE_PROFILE.md` 대신 `CLAUDE.md` 머리말 규칙 3(`.local-draft`)으로 판별하므로 문제없음을 `DRAFT_NOTES.md`에 기록.
- i. `04-parser-matching.md §5.8 (2)` `tags.yaml` 예시와 `07-workflow.md §Step 3` data 태그 목록에 Android 13+ 데이터 스택 태그 추가: `DSM-<phoneId>`(DataSettingsManager — data enabled/disabled 판별에 직접 관련), `DCM-<phoneId>`(DataConfigManager), `DSRM-<phoneId>`(DataStallRecoveryManager). `CLAUDE.md` 머리말·`14-site.md` S8의 "확정" 목록에도 같은 태그 추가. 문구는 여전히 placeholder.
