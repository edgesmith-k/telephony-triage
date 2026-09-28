# 99. v1에서 뺀 설계 (확장 후보)

> **어느 Phase에서도 읽지 않는다.** 8차까지 설계했다가 9차에서 v1 범위를 줄이면서 뺀 내용이다. 10차에서는 계획 기반 마이그레이션·새 카테고리 PR(`source: migrate|category|cleanup`, 전용 op 또는 `db_pr stage` 특수 경로)도 뺐다 — v1은 메인테이너 직접 편집 브랜치다. 파일럿(Phase 14)에서 충돌이나 동시 작업이 실제 병목으로 확인될 때만 다시 검토한다.
> 다시 넣을 때는 이 문서를 `contracts.md`·`06-collaboration.md`·`07-workflow.md`·`11-phases.md`에 나눠 반영하고, 아래 "되살릴 때 바꿀 곳"을 함께 고친다.

v1이 이것들 없이도 되는 이유
- 도구가 만드는 PR은 모두 작업 계획이 있고, 적용 시점에 ID를 할당하므로 `sync-pr`는 계획 재적용으로 충분하다. 계획 대상이 main에서 바뀐 경우는 drift 검사가 잡는다 (`contracts.md §작업 계획`).
- "머지는 한 번에 하나씩"과 `sync-pr` 때문에 main에 같은 ID가 두 번 들어오는 일은 드물다. 생기면 사후 lint가 찾고 메인테이너가 직접 고친다.
- 작업 디렉토리는 사용자별이라, 동시 작업은 같은 사람이 세션 두 개를 여는 경우뿐이다. v1은 세션 lock으로 한 번에 한 작업만 허용한다.

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
5. **plan 내보내기**: 판정 결과를 op로 바꿔 `replay-plan.json`(`source: replay`)에 쓴다. 전용 op로 표현할 수 있으면 그것을 쓰고, 나머지는 **replay 전용 op**를 쓴다. 원래 계획이 있으면 `jira`, `commit_message`, `pr`, 원래 `source`(`origin_source`)와 `jira.origin`을 이어받는다(라벨 유지). 없으면 브랜치의 마지막 커밋 메시지와 열린 PR 정보를 쓴다.
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

v1의 세션 lock(한 번에 한 작업) 대신, 같은 사용자의 여러 세션이 동시에 다른 작업을 하게 하는 방식이다.

- **작업 lock**: `<work_dir>/<작업 키>/.lock`(시각 기록). `stage`가 만들고 `summary`·`publish`가 갱신, `discard`가 지운다. 4시간 넘게 갱신되지 않으면 만료.
- **읽기 임대**: `db_pr snapshot --lease <작업 키>`가 `<work_dir>/_snapshot.readers/<작업 키>`(4시간)를 등록한다. 다른 작업 키의 살아 있는 임대가 있으면 스냅샷을 옮기지 않고 `updated: false`와 사유를 반환한다. 스킬은 기다릴지 현재 스냅샷으로 진행할지 묻는다.
- **알려진 문제(8차 검토)**: `discard` 없이 끝나는 흐름(읽기 전용 종료, `validate --cause` failed/unknown, `verify-fix` unknown)에서 임대를 지울 CLI가 필요하다. `sync-pr`와 analyze Step 8이 다른 작업 키로 같은 `tt/<br>`에 들어갈 수 있으므로, `stage`는 `tt/<br>`가 다른 worktree에 checkout돼 있으면 거부해야 한다. `cleanup`이 lock 없이 진행 중인 `draft`를 지우지 않게 `rules --draft`도 lock을 잡아야 한다. 스크립트는 호출마다 끝나므로 프로세스 생존으로 만료를 판단할 수 없다(명시 해제 + 사용자 확인 후 강제 해제).

---

## 되살릴 때 바꿀 곳

- `contracts.md`: `db_add` CLI(`extract`, `replay`, `renumber --in-main`), `db_pr snapshot --lease`와 lock 정의, op 표(replay 전용 op), `source: replay|migrate|category|cleanup`, `signatures_pending`의 replay 이어받기, 종료 코드 `3`의 `set-field` 예시, `config.py check --for migrate`와 `db_pr stage`의 마이그레이션 경로(`migration_to`)
- `06-collaboration.md §6.2·6.3`: sync-pr 알고리즘, 사후 정리 정책
- `07-workflow.md`: Step 8-2 선택지("sync-pr: 원격 기준 replay"), `§sync-pr`
- `11-phases.md`: Phase 7(replay·in-main 완료 기준), Phase 9(extract 스키마 정렬)
- `10-skill-eval.md`: eval 16·28
