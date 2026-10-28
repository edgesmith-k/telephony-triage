# 재반입 노트 — 10/28 사내 피드백 17건 반영분

사내 피드백 17건(import-20261018 기준, 10/28)을 사외에서 고친 묶음. **PR #71(`REIMPORT_NOTES_1021.md`)과 한 묶음으로 들어간다** — 그 노트의 할 일도 같이 본다. 절차는 `docs/SITE_INSTALL.md §8`.

## 1. 반입 전에 (멈춤 방지)

기준선 뒤 사내에서 고친 사외 파일은 마지막 반입 버전으로 되돌리고 커밋한다(`git restore --source=$(git log -1 --format=%H -- .draft-manifest.json) -- <파일>`). 새 묶음에 정식 수정이 있다.

- `plugin/scripts/common/yamldoc.py` 2줄 삭제(1번) — 정식 수정은 `ListSection.render`가 마지막 항목 뒤 구분 줄을 쓰지 않는 것. `replace_block`의 `while` 줄을 지웠다면 그것은 틀린 수정이다(키 사이 빈 줄이 없어진다).
- 테스트 임시 수정: `test_android_identity.py`(4a), SKILL.md 크기 기준(4b), 사외 전용 테스트 skip(3).
- `SKILL.md` Step 7 질문(PR #71에 정식 문구).
- 손으로 고친 `SITE_PROFILE.md` 사유는 `SITE_PATHS`라 그대로 둔다.

## 2. 반입 뒤 테스트

- `python3 -m pytest -q tests`. 사내에서 skip이 정상: `test_site_paths_are_absent_in_draft`, `test_check_boundary_external`, `test_site_defaults_required`, `test_offline_eval_default_root_is_temporary_helper_root_without_site_defaults`(새로 나뉜 기본 루트 검사).
- 3번 나머지(`test_offline_eval_prints_accuracy_table_on_synthetic_labelset`, `test_late_warning_reaches_stderr`, `test_missing_site_defaults_stops_with_guidance`)는 skip이 아니라 사내에서도 통과하게 바꿨다(임시 플러그인 루트).
- 4a: `parser_backends/site/`만 android import 예외. `adapters/site_*`에서 실패하면 그 줄을 사외로.
- 4b: 크기 기준은 이미 9,063B(PR #71이 Step 7 문구를 정식으로 넣음). 사내 편집을 되돌리면 통과.
- `test_show_guard.py::test_hook_replay_counts_without_content`는 사외에서도 환경에 따라 실패한다(1021 노트와 같음).

## 3. 바뀌는 것과 사내에서 할 일

| # | 바뀐 것 | 사내에서 할 일 |
|---|---|---|
| 1 | 같은 섹션을 다시 써도 빈 줄이 늘지 않는다 | 운영 이슈 DB에 이미 쌓인 빈 줄은 메인테이너 PR로 정리 |
| 2 | `s4_seed`: config `categories`의 카테고리마다(data 제외) 실제 `fixtures/*.log`(`.expect.yaml`이 없거나 `origin: synthetic`이 아닌 것)가 있는 유형 수를 세고 5 미만이면 실패 | `site_step.py check S-4` 다시 — 시드가 실제로 모자라면 보충 |
| 5 | `parse_logcat.py cut --evidence`는 `--cause <ID>` 필수. 그 원인이 후보가 아니면(C=0·판정 불가·signatures_pending·`--top`에 잘림) 종료 2, 다른 원인도 맞으면 `evidence-other-causes` 경고. record 절차는 `--regress --top 0 --cause` | eval 30·50이 이 명령에 닿는다(사내 대상 아님, 기록만) |
| 6 | `jira_fields extract`: 빈 키는 `issue`에서 뺌, 고정 질문 `missing_question`. 계획 형식 오류에 필드 경로(`issue/carrier`) | — |
| 7 | `job_status`: Jira 키가 아닌 작업 키(`fix-submit-…`·`verify-fix-…` 등, 작업 파일 있는 폴더)도 후보(`kind: work`) | — |
| 8 | publish: PR을 리뷰어 없이 만들고 리뷰어마다 `gh pr edit --add-reviewer`. 실패는 경고(팀 오너 → S5·S19, 개인 → S5)·종료 0, 바로 병합 대신 리뷰로. 새 점검 `s4a.codeowners`(모의값·`<org>`·`TODO(SITE` 남으면 실패, `@login` 허용) | 운영 DB `CODEOWNERS`의 `mock-org` 정리(S5, 메인테이너 PR), `site_step.py check S-4a` |
| 9 | 계획 op `remove-parser-rule`(file·key·reason, section 선택; 없는 키·섹션 마지막 규칙 거부, R4/R5 검증). 뼈대 placeholder 규칙(데이터 스택 태그 제외, RILJ 포함)에 `reason: placeholder (…)`. 원칙: 파서 규칙 **삭제**도 사용자 확인 | 운영 DB `schema/plan.schema.json` 교체(메인테이너 PR) **뒤에** op 사용. 실제 이름이 아닌 placeholder 규칙은 이 op로 지운다(사용자 확인) |
| 10 | lock: 같은 owner·같은 작업은 다시 잡을 수 있음(`reacquired: true`), 반납 실패는 "lock은 풀리지 않았다", 출력의 owner는 앞 4자만 | — |
| 11 | `jira_bridge`: JSON(블록별)·JSONL 먼저, YAML은 key/fields/comments가 있는 dict일 때만. 자유 텍스트 댓글은 1건(`comments_format: text`), 자유 텍스트 이슈는 저장하지 않고 응답 형태만 알림 | 실패하면 메시지 끝 `형식: …`을 사외로(보류 중) |
| 12 | `config.py tracker-candidates`: 응답 오면 바로 반환, 프로세스 그룹 종료, 서버당 10초, `servers[].{probe,elapsed_ms,error}`, stderr `[tracker-candidates] …` 진행 줄 | 그래도 멈추면 서버별 `probe`·`elapsed_ms`·`error` 줄과 실행 명령 종류(npx·uvx 등)를 사외로 |
| 13 | `site_step.py --done --waive`: 사유를 줄 끝에, 120자 넘으면 `…(전체: docs/site/evidence.md)`, 쓴 줄을 출력, 같은 점검 중복 거부 | (원래 사유 형식 문의는 보류 중) |
| 14 | `s4.placeholder`(정보)·`s6.placeholder`가 placeholder 규칙·`TODO(SITE…)`·모의값 세 종류를 file:line으로 셈. `s6.placeholder`는 보고한 수 = 현재 수일 때만 통과. 새 `s6.mock`(사용자 필요, 사유로 면제 가능) | `site_step.py check S-6` 다시 — 보고 줄 갱신, 남은 모의값 정리 또는 사유와 함께 면제 |
| 15 | 뼈대 `fix_ref_regex` 기본값 `^MOCKCL-\d+$`(S18 전까지 실제 값 거부), "Gerrit" 단정 삭제 | 운영 DB `fix_ref_regex`를 실제 형식으로(S18, 메인테이너 PR) |
| 16 | `reviewers.format`(S19): 개인 오너(`@login`)만 쓰면 해당 없음 | 개인 오너면 SITE_PROFILE에 "해당 없음" 기록, 팀 오너면 샌드박스 PR로 형식 확인 |
| 17 | Jira 기록 `sw` 선택 필드(모르면 키 생략). 플러그인은 **운영 DB 자기 스키마**의 `required`로 묻고 거부 — 옛 스키마면 계속 필수, 거부 메시지에 "운영 DB schema 메인테이너 PR 필요". `schema_version`·마이그레이션·생성기 버전 변경 없음(호환 변경, 결정 (d)·06 §6.4) | 운영 DB `schema/issue.schema.json`·`templates/issue.yaml` 교체(메인테이너 PR). 그동안 `sw`에 "unknown" 같은 임시값을 넣었다면 그 기록을 알려 준다 |

## 4. 운영 이슈 DB 메인테이너 PR (한 번에 묶어도 됨)

새 뼈대(zip 해시가 바뀜)의 해당 파일과 비교해 옮긴다: `schema/plan.schema.json`(9), `schema/issue.schema.json`·`templates/issue.yaml`(17), `docs/analyzer-skills.md`(PR #71), CODEOWNERS(8), `fix_ref_regex`(15), 빈 줄 정리(1), 파서 규칙 placeholder 표시(`reason: placeholder (…)` — 옛 뼈대로 만든 운영 DB는 표시가 없어 S-6이 placeholder 규칙을 0으로 센다. 표시하거나 `remove-parser-rule`로 지운다). 스키마 PR이 먼저 병합돼야 새 op와 `sw` 생략을 쓸 수 있다. 버전을 올리지 않으므로 플러그인과 순서 제약은 없다.

## 5. 지난 단계 다시 점검 (읽기 전용)

`python3 tools/site_step.py check S-4`, `check S-4a`, `check S-6`. 실패·사용자 필요만 처리하고 단계를 처음부터 다시 하지 않는다. 그다음 `claude` → **계속**(S-7).

## 6. eval

PR #71이 `SKILL.md`를, 이번 묶음이 `jira_bridge.py`를 바꿨다 → `SITE_INSTALL.md §8` 기준으로 사내 대상 eval 11개 전체가 다시 돌릴 대상(1021 노트에서 추후로 미룬 것 포함). 언제 돌릴지는 사용자 결정. `hooks.json`·`guard.py`·`show_guard.py`는 바뀌지 않았다(바뀐 hook 스크립트는 `jira_bridge.py`).

## 7. 반입 뒤 후보 (P2)

analyze의 다른 원인 자르기(`--around` 우회)를 `--cause`로, `write-flow.md` 빈 필드 질문 문구, `tracker-candidates` 병렬 점검·`--no-probe` 등 플래그, `list_site_todos`의 번호 없는 `TODO(SITE)`, `model`·`platform_version` 필수 해제(보고 없음, 같은 방식으로 DB 스키마 PR만).
