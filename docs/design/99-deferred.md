# 99. v1에서 뺀 설계 (확장 후보)

> **어느 Phase에서도 읽지 않는다.** 8차까지 설계했다가 9차에서 v1 범위를 줄이면서 뺀 내용이다. 10차에서는 계획 기반 마이그레이션·새 카테고리 PR(`source: migrate|category|cleanup`, 전용 op 또는 `db_pr stage` 특수 경로)도 뺐다 — v1은 메인테이너 직접 편집 브랜치다. 파일럿(Phase 14)에서 충돌이나 동시 작업이 실제 병목으로 확인될 때만 다시 검토한다.
> 다시 넣을 때는 이 문서를 `contracts.md`·`06-collaboration.md`·`07-workflow.md`·`11-phases.md`에 나눠 반영하고, 아래 "되살릴 때 바꿀 곳"을 함께 고친다.

v1이 이것들 없이도 되는 이유
- 도구가 만드는 PR은 모두 작업 계획이 있고, 적용 시점에 ID를 할당하므로 `sync-pr`는 계획 재적용으로 충분하다. 계획 대상이 main에서 바뀐 경우는 drift 검사가 잡는다 (`contracts.md §작업 계획`).
- "머지는 한 번에 하나씩"과 `sync-pr` 때문에 main에 같은 ID가 두 번 들어오는 일은 드물다. 생기면 사후 lint가 찾고 메인테이너가 직접 고친다.
- 작업 디렉토리는 사용자별이라, 동시 작업은 같은 사람이 세션 두 개를 여는 경우뿐이다. v1은 세션 lock으로 이슈 DB(플랫폼)마다 한 번에 한 작업만 허용한다.

---

## A. 3-way replay (계획 없는 브랜치의 자동 재동기화)

`sync-pr`가 원래 계획 없이 원격 브랜치 내용 자체를 최신 main에 합치는 방식이다. 직접 편집한 브랜치, 리뷰어가 원격에서 고친 브랜치, 다른 PC에서 만든 PR을 도구로 재동기화할 수 있다.

**CLI**: `db_add extract --branch <ref> --onto <ref> --out <plan.json>`(replay용 계획 추출, `source: replay`), `db_add replay --branch <ref> --onto <ref>`(= extract + apply).

**replay 알고리즘** — 세 트리를 각각 파싱한다.
- **base** = `git merge-base origin/<br> origin/<base>`
- **ours** = `origin/<br>` (브랜치)
- **theirs** = `origin/<base>` (최신 main)

0. **내 ID 치환**: merge-base에 없고 ours에서 새로 생긴 유형·원인 ID("내 ID")를 짝짓기 **전에** ours 트리 전체에서 `temp_id`(`NEW-TYPE-<n>`, `NEW-CAUSE-<n>`)로 바꾼다. 치환 범위는 `contracts.md §renumber 참조` 목록 전부다. 그래서 theirs에 같은 번호의 다른 원인이 먼저 머지돼 있어도 같은 엔티티로 짝지어지지 않는다. ours에만 새로 생긴 fixture 번호(`<n1>`/`<n2>`)도 비워두고 apply가 다시 할당한다.
1. **스키마 정렬**: 세 트리의 `schema_version`이 다르면 base와 ours에 theirs 버전까지의 마이그레이션(`db_migrate`)을 메모리에서 먼저 적용한다.
2. **무시 대상**: 생성 파일과 `.cache/`는 비교하지 않는다. apply 후 항상 재생성한다.
3. **엔티티 키**

   | 엔티티 | 키 | 비교 단위 |
   |---|---|---|
   | 유형 | 유형 ID | frontmatter 필드 (원인 목록 제외) |
   | 원인 | 원인 ID | 원인 필드 각각. 시그니처 목록은 시그니처 `id` 단위 |
   | 본문 섹션 | (유형 ID, `## <제목>` 또는 `### <ID>`) | 섹션 텍스트 전체 |
   | Jira 파일 | Jira 키 | 파일 전체 (위치 이동 포함) |
   | fixture | 파일 경로 | 파일 전체 (`.expect.yaml` 포함) |
   | 피드백 | 파일 경로 | 파일 전체 (항상 신규) |
   | parser-rule | (파일, 키) | 기능 필드와 이력 필드를 나눠서 비교 |
   | 그 밖의 파일 | 파일 경로 | 파일 전체 |

4. **필드 단위 3-way 판정**

   | base → ours | base → theirs | 결과 |
   |---|---|---|
   | 변경 없음 | 무엇이든 | theirs 유지 (op 없음) |
   | 변경 | 변경 없음 | ours 적용 (op 생성) |
   | 변경 | 같은 값으로 변경 | 통과 |
   | 변경 | 다른 값으로 변경 | **사용자에게 질문** (ours / theirs / 직접 입력) |
   | 신규 (ours에만) | — | ours 적용. 새 유형/원인은 `temp_id`로 op를 만든다. ours에서 `signatures_pending: true`였던 원인은 그대로 옮긴다 |
   | 신규 | 신규 (같은 키), 같은 내용 | 통과 |
   | 신규 | 신규 (같은 키), 다른 내용 | Jira 파일: 유지/재분류/이 PR에서 빼기 질문. parser-rule: 기능 필드가 같으면 theirs 유지, 다르면 질문. 그 밖의 파일: 질문 |
   | 삭제 (ours) | 변경 없음 | 삭제 적용 (유형/원인은 `status` 변경만 허용, 삭제면 질문) |
   | 삭제 (ours) | 변경 | 질문 |

   - parser-rule: 기능 필드가 같고 이력 필드만 다르면 main 값을 유지한다.
5. **plan 내보내기**: 판정 결과를 op로 바꿔 `replay-plan.json`(`source: replay`)에 쓴다. 전용 op로 표현할 수 있으면 그것을 쓰고, 나머지는 **replay 전용 op**를 쓴다. 원래 계획이 있으면 `issue`, `commit_message`, `pr`, 원래 `source`(`origin_source`)와 `issue.origin`을 이어받는다(라벨 유지). 없으면 브랜치의 마지막 커밋 메시지와 열린 PR 정보를 쓴다.
6. **apply 재사용**: `db_pr stage`가 일반 계획과 똑같이 적용한다.

**replay 전용 op** (계획 `source: replay`일 때만 허용)

| op | 필수 필드 | 대상 | 적용 규칙 |
|---|---|---|---|
| `set-field` | `id`, `path`, `value` | 유형/원인의 임의 필드 | `fix`, `resolution_verification`, `status`, `signatures_pending`을 바꾸면 `db_pr stage`는 종료 코드 `3`(승인 필요) |
| `set-body` | `id`, `section`, `text` | 본문 섹션 | `section`은 `## <제목>` 또는 `### <ID>` |
| `put-file` | `path`, `source` | 그 밖의 파일 (GLOSSARY, templates, schema, docs 등) | 파일 단위 교체 |

- `signatures_pending` 새 원인은 `record`와, 브랜치에 이미 pending으로 있던 원인을 옮기는 `replay`에서만 허용한다.

---

## B. 사후 main ID 재배치 자동화

v1은 메인테이너가 직접 편집한다 (`06-collaboration.md §6.3`). 자동화하면:

- `db_add renumber --in-main <ID> --owner-commit <sha>`: main에 같은 ID가 두 번 있을 때 나중 쪽을 다음 빈 ID로 옮긴다.
- **소유 판별**: 그 ID를 가진 각 파일(유형 디렉토리, type.md 원인 항목, Jira·fixture 파일)에 대해 `git log --diff-filter=A --format=%H -- <path>`로 처음 추가한 커밋을 구하고, 더 이른 쪽을 소유자로 본다. 같은 type.md 안의 원인 중복이면 `git log -L` 또는 blame으로 원인 블록을 추가한 커밋을 구한다.
- **공유 파일 참조**(다른 원인의 `related`, 피드백 `final`·`suggested`, parser-rules `added_for`): 그 참조를 추가한 커밋이 나중 쪽 PR의 커밋인지(`git log -L`/blame)로 옮길지 정한다. 판별할 수 없으면 사용자에게 묻는다.
- 사후 lint가 문제를 찾으면 정리 PR 초안(`chore/fix-db-<문제 ID>`, `source: cleanup`)을 만들고 `db_pr stage` → 확인 화면 → `publish`로 올린다. 같은 브랜치나 열린 PR이 있으면 만들지 않는다.
- Jira 중복은 나중 머지 쪽 파일을 지우는 계획을 만든다.

---

## C. 스냅샷 읽기 임대 (동시 작업)

v1의 세션 lock(이슈 DB(플랫폼)별 한 번에 한 작업) 대신, 같은 사용자의 여러 세션이 같은 이슈 DB에서 동시에 다른 작업을 하게 하는 방식이다.

- **작업 lock**: `<work_dir>/<작업 키>/.lock`(시각 기록). `stage`가 만들고 `summary`·`publish`가 갱신, `discard`가 지운다. 4시간 넘게 갱신되지 않으면 만료.
- **읽기 임대**: `db_pr snapshot --lease <작업 키>`가 `<work_dir>/_snapshot.readers/<작업 키>`(4시간)를 등록한다. 다른 작업 키의 살아 있는 임대가 있으면 스냅샷을 옮기지 않고 `updated: false`와 사유를 반환한다. 스킬은 기다릴지 현재 스냅샷으로 진행할지 묻는다.
- **알려진 문제(8차 검토)**: `discard` 없이 끝나는 흐름(읽기 전용 종료, `validate --cause` failed/unknown, `verify-fix` unknown)에서 임대를 지울 CLI가 필요하다. `sync-pr`와 analyze Step 8이 다른 작업 키로 같은 `tt/<br>`에 들어갈 수 있으므로, `stage`는 `tt/<br>`가 다른 worktree에 checkout돼 있으면 거부해야 한다. `cleanup`이 lock 없이 진행 중인 `draft`를 지우지 않게 `rules --draft`도 lock을 잡아야 한다. 스크립트는 호출마다 끝나므로 프로세스 생존으로 만료를 판단할 수 없다(명시 해제 + 사용자 확인 후 강제 해제).

---

## D. MCP로 Jira 첨부 가져오기 (실패 스텝)

v1의 실패 스텝은 필드·설명·시험 절차 텍스트와 사용자가 준 `--steps-file`에서만 얻는다. 첨부(txt/csv/xlsx)를 Jira MCP로 직접 받으려면 `tracker.read_tools`에 허용된 읽기 도구만 쓰고, 받은 파일은 `issue_raw.json`처럼 격리해 `--steps-file` 경로로 넘긴다 (`02-config.md`, 14-site.md S22). v1은 zip 첨부를 사용자가 직접 받아 `--steps-file`로 줄 때만 읽는다(안의 `report.html` 하나, 메모리에서만).

### D-2. 시계 차 자동 추정

시각이 있는 스텝(시작·종료 시각이 있는 PASS 스텝)의 장비 시각과 로그의 흔적 시각(`step_events`)을 맞춰 장비 시계와 단말 시계의 차를 **자동으로 추정**하는 것은 v1에서 뺐다. v1은 `--clock-offset`/`failed_step.clock_offset`을 사람이 줄 때만 장비 시각을 쓰고, 그 밖에는 스텝 순서(`step_order`)로 구간을 잡는다. 되살리면 추정값을 사용자가 확인한 뒤에만 쓴다.

### D-3. 중첩 zip

첨부 zip 안의 zip은 읽지 않는다(무시). 되살리려면 깊이·총 크기 상한과 같은 항목 선택 규칙을 재귀로 적용한다(`08-safety.md §8.1`).


## E. Read 도구 원문 통독 차단 (사내 S1 뒤)

규칙 10(`08-safety.md §9`)은 Bash 명령만 판정한다. Read 도구가 `limit` 없이 로그 원문·zip·`events.json`·`events-full.json`·`issue_raw.json`·`match.json`을 통째로 읽는 것은 막지 못한다. 사내 Claude Code(S1)에서 PreToolUse hook이 `Read`에 걸리고 입력에 `file_path`·`offset`·`limit`이 오는지 확인한 뒤, `hooks.json`에 matcher `Read`를 더하고 `guard.py check_file`(또는 같은 모양의 함수)에서 **`limit`·`offset` 없는 읽기**가 규칙 10과 같은 원문 대상(같은 이름·내용 판별, `fixtures/`·`draft/` 제외)이면 거부한다. 메시지는 규칙 10과 같게 구간 읽기를 안내한다. 대용량 파일은 Read 도구가 기본 줄 수 상한으로 자르기도 하므로(버전에 따라 다름) 상한이 있는 읽기를 어디까지 허용할지는 S1에서 정한다. 입력 확인은 S1 빈 플러그인 실험 21번(`tests/mocks/plugin-probe/README.md`)에서 18~20번과 한 번에 한다.

- 관찰(W1·W4 eval): Bash `cat`·`cat -n`·`sed -n 1,20p` 같은 로그 원문 구간·전체 읽기도 규칙 10 대상이나 guard가 막지 않았다(eval 18·40·46). 새 WP 여부는 W 끝에서 결정.
- 종결(W11): eval 18·40 trace에서 재현한 명령은 yaml·py·json 읽기이지 원문 로그가 아니었고, eval 46 trace는 없다. `fixtures/` 아래 로그는 설계상 예외다(`guard.py _is_raw_file`). W 끝 eval에서 다시 보이면 재개한다.

## F. verify-fix 흔적 검사 강제 (반입 뒤)

3E에서 Sonnet은 e25(코드·설정 수정 유형에 scenario·recovery 시그니처가 없음)에서 "판정 전 중단" 규칙을 문구만으로는 지키지 못했다(2/3). 구조로 강제한다.

- 방안 1(완료, W3): `db_verify.py fix`가 코드·설정 수정 유형이면서 scenario·recovery 시그니처가 모두 없을 때 `judgement: unknown`을 내는 대신 **종료 코드 2와 "판정 전 중단 조건" 오류**로 거부한다. 오류에 "update-signature로 scenario/recovery 추가 → 초안 R1 흔적 검사 통과 → 재실행" 안내를 `must_show`처럼 담는다.
- 방안 2(완료, W3): `db_search.py` 원인 출력에 `verify_fix_blocked: "<사유>"`를 내고 verify.md 3번에 "있으면 `db_verify fix`를 부르지 않는다"를 적는다.
- 같이 할 것(b-6): SKILL 5-1을 "report.md의 그 칸 줄을 **파일에서 바꿔 쓰고** 답변에도 보인다"로 명확히 한다(e40·e41은 답변만 채우고 `report.md`는 TODO로 남았다).
- ~~그때까지 verify-fix는 Opus를 권장한다~~ → W3 뒤 Sonnet 기본(eval 25 Sonnet 3/3, `GUIDE.md`).

## G. 설명 양식에서 SW·모델 추출 (H1, 사내 S-3 뒤)

사내 S-3(10/19)에서 본 것: Jira description의 양식 구역에 SW 버전·모델이 적히지만 v1은 본문 정규식 추출이 실패 스텝(`tracker.failed_step_patterns`, `failedstep.py`)뿐이고 `model`·`sw`는 `tracker.field_map` 필드 값만 읽는다. 확인값(양식 줄 꼴·필드 유무)은 `SITE_PROFILE.md`에 둔다.
- 후보: `failedstep.py`의 줄 단위 패턴 방식을 일반화해 `tracker.field_patterns: {model: [...], sw: [...]}`(마스킹된 설명에서 줄 순서·패턴 순서로 처음 맞는 것, `(?P<value>…)` 그룹)를 두고, `field_map` 값이 있으면 그것이 이긴다. 값이 없거나 패턴 오류면 지금처럼 없는 것으로 본다(질문·중단 없음, 정규식 오류는 경고).
- 바꿀 곳: `02-config.md`(`tracker` 키 표·"실패 스텝(선택)" 문단 옆), `common/failedstep.py` 또는 새 `fieldpatterns.py`, `trackers/jira` 필드 읽기, `db_lint`는 무관(이슈 DB 아님), `tests/test_jira_fields.py`. 사내 양식을 보기 전에는 만들지 않는다(S-3 확인 뒤 결정).
- 버전 문구: Jira의 버전 값이 숫자가 아니라 문구이면 `platform_version`도 같은 패턴 설정(`tracker.field_patterns`) 대상이다. 지금은 버전 일치가 안 돼 소스 프로필 자동 선택 없이 목록 질문으로 떨어진다(`jira_fields.py`·`code_roots.py suggest`는 문자열 그대로 비교). bugreport 헤더의 빌드 정보를 프로필 목록 정렬에 쓸지도 사내 형식을 본 뒤 정한다.

## H. 탐색 `--also` (보조 모듈 1개, 파일럿 뒤)

탐색은 모듈 하나만 본다(`--module` 단수, 모듈 보기 필터가 다른 모듈 줄을 뺀다). 예: call·sms 보기에는 등록 줄이 없어 "서비스 없음"의 근거가 안 보인다. 완전한 다중 선택은 인자·기록·질문·필터·예산(공통 + explore.md 1개 ≤ 8800B)·eval이 모두 바뀌어 비싸다.
- 후보: 주 모듈 + 보조 모듈 1개. 타임라인은 두 모듈 필터의 합집합(줄 수 상한 공유), 문서는 주 모듈 것만(보조 explore.md는 예산을 보고), 기록의 빈 `also` 자리를 쓴다(deep `--also`가 선례).
- 되살리는 조건: 사내 파일럿에서 후보 모듈이 둘 이상 나오는 빈도와 "다른 모듈 문서로 바꿀까요?" 질문 빈도, 탐색 실패 건에서 정답 줄이 빠진 곳(수집 태그에 없음 / 모듈 필터 / 줄 수 상한 `explore.timeline_max_lines` 200)을 사내에서 세어 본 뒤.

## I. 심층 분석 단계 (토큰을 덜 아끼고 원인 찾기, 파일럿 뒤)

DB에 맞는 것이 없고 탐색으로도 가설이 서지 않으면 "가설 없음/다음 확인"으로 끝난다.
- 후보: 사용자가 고르는 세 번째 단계(DB 매칭 → 탐색 → 심층). 푸는 것: 타임라인 줄 수 상한, 모듈 필터(여러 모듈 보기 합침), 문서 예산, 버전별 소스 읽기(코드 경로 추적). 풀지 않는 것: 마스킹된 로그만, 근거 줄 원문 대조(`check-output`), 채택은 사용자가, 시그니처·유형 추가는 확인 후.
- 조건: 시작 전 예상 비용을 보이고 동의를 받는다. 결과는 `로그로 확인`/`코드로 추정`으로 계속 구분한다.
- 되살리는 조건: 사내 파일럿에서 탐색이 "가설 없음"으로 끝나는 비율·모듈을 본 뒤. 검증은 사내 소스 경로(`SITE_PATHS`)가 있어야 한다.

---

## 되살릴 때 바꿀 곳

- `contracts.md`: `db_add` CLI(`extract`, `replay`, `renumber --in-main`), `db_pr snapshot --lease`와 lock 정의, op 표(replay 전용 op), `source: replay|migrate|category|cleanup`, `signatures_pending`의 replay 이어받기, 종료 코드 `3`의 `set-field` 예시, `config.py check --for migrate`와 `db_pr stage`의 마이그레이션 경로(`migration_to`)
- `06-collaboration.md §6.2·6.3`: sync-pr 알고리즘, 사후 정리 정책
- `07-workflow.md`: Step 8-2 선택지("sync-pr: 원격 기준 replay"), `§sync-pr`
- `11-phases.md`: Phase 7(replay·in-main 완료 기준), Phase 9(extract 스키마 정렬)
- `10-skill-eval.md`: eval 16·28
