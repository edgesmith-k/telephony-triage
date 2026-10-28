# 10/28 변경 리뷰 인계 (사내 피드백 17건, 브랜치 `ccr-d022623a-2f4vdx`)

> **결과(10/28): 리뷰 완료.** P0 1·P1 2, 수정 커밋 0637564. P1 `jira_bridge` 게시 결과(`bridge_post`)가 읽기용 새 `_payload`를 같이 써 `error:` YAML·YAML로 못 읽는 텍스트 응답이 posted(승인 소모) → 57d2846 전 해석(`isError`는 항상 실패). P1 `contracts.md` 초안 검증 게이트 op 목록에 `remove-parser-rule` 없음. P0(수정 리뷰에서 발견) 게시 실패 기록 `error`를 json.dumps 뒤에 마스킹해 줄바꿈·탭 이스케이프 뒤 식별자가 남음. 남긴 P2 9건은 `REIMPORT_NOTES_1028.md` §7. 테스트: 57d2846 전체 2,213 통과(Python 3.10.12), 수정 뒤 related 32파일 1,282·관련 10파일 443 통과. eval은 돌리지 않았다.

새 세션에서 이번 변경을 **선입견 없이** 리뷰하기 위한 자료. 기준: `c3dd0c2..`(10/28 커밋). 66파일 수정 + 새 파일 5개(+1,582 −247).

## 리뷰 방법

- 이 문서에는 **무엇을 요청받았고 무엇을 결정했는지**만 있다. 구현이 맞는지는 적지 않았다. 구현자·이전 리뷰의 판단(커밋 메시지, `REIMPORT_NOTES_1028.md`의 "바뀐 것" 설명, 코드 주석 포함)은 검증할 주장으로 보고, **코드와 테스트를 직접 읽는다**.
- 각 항목마다: (1) 요청을 실제로 해결하는지 (2) 결정 범위를 넘거나 모자라지 않은지 (3) 새 결함·회귀 (4) 테스트가 수정 전 코드에서 실제로 실패하는지 (5) 문서·`contracts.md`가 코드와 맞는지.
- 등급: P0 안전 위반(이슈 DB push·병합 승인, guard, 마스킹, fail-closed, main 보호), P1 기능 결함·계약 불일치, P2 그 밖. 결정 (r): P0·P1만 고치고 P2는 기록한다. 수정 절차는 결정 (p).
- 먼저 `CLAUDE.md`, `docs/design/12-principles.md`를 읽는다. `docs/history/`는 읽지 않는다.
- 사내 환경: Python **3.10.12**, Ubuntu 20.04. 3.11+ 문법·모듈은 결함이다.

## 사내 보고 원문 (사용자가 옮겨 적음, 오타 가능)

1. `common/yamldoc.py`(보고에는 "tamldoc"): 같은 섹션을 쓸 때마다 빈 줄이 2배로 는다. 사내에서 2줄 삭제로 고침.
2. `tools/site_checks.py` s4 seed: 시드 0인데 통과. `*.expect.yaml` 없는 fixture를 안 세고, 유형 0개 카테고리를 빼고 계산.
3. 사외 전용 테스트 4개가 사내에서 실패 → 사내 모드에서 skip: `test_site_defaults_required`, `test_offline_eval_prints_accuracy_table_on_synthetic_labelset`, `test_late_warning_reaches_stderr`, `test_missing_site_defaults_stops_with_guidance`.
4. 사내 구조와 맞지 않는 테스트: (a) `test_no_android_module_import_outside_platforms` — 사내 site 백엔드 경로 예외 필요 (b) SKILL.md 크기 테스트 — 사내에서 Step 7 질문을 넣어 8,972B.
5. record: `cut --evidence`가 1위 후보 근거만 씀. 기록할 원인을 지정할 수 없어 1위가 다른 원인이면 엉뚱한 구간이 잘림.
6. record: 빈 필드 질문 문구가 정해져 있지 않고, carrier가 null인데 missing 목록에 없음.
7. `job_status.py`: push만 되고 PR이 없는 작업(`pr.head_sha`만)이 후보에 안 나옴(candidates 빈 목록).
8. publish: CODEOWNERS 리뷰어를 못 찾으면 PR 생성 자체가 실패 → 리뷰어 없이 만들고 경고. 뼈대 CODEOWNERS의 모의값(`mock-org`) 정리.
9. 계획 op에 parser-rule 삭제가 없음. placeholder 규칙을 지우려면 직접 편집뿐.
10. 같은 lock owner라도 잠시 쉬었다 다시 잡으면 `lock acquire`가 종료 2, `--take-over` 요구.
11. Jira 댓글 도구 ScannerError: analyze.record 헤드리스 실행에서 get_issue_comments 실패, 세션에서 직접 호출하면 정상.
12. tracker-candidates 간헐 무응답(이전부터).
13. `site_step.py --done --waive` 사유가 SITE_PROFILE에 기록될 때 `-`에서 잘림(S-3·S-5 두 번).
14. s6.placeholder: `reason: placeholder` 문자열만 셈 → TODO(SITE:…) 주석, 실제 로그로 확인 못 한 규칙, 모의 설정값이 빠지고 "0건".
15. 뼈대 `fix_ref_regex` 기본값 `^(MOCKCL-\d+|[0-9a-f]{7,40})$`가 숫자 7자리를 커밋 해시로 받음. 주석의 "Gerrit" 단정 → placeholder로.
16. 뼈대 `reviewers.format` 주석(S19): 개인 계정 CODEOWNERS에는 이 값이 안 쓰인다는 설명이 없어 사내에서 무엇을 정할지 모름.
17. 이슈 기록 스키마의 `sw`가 필수(minLength 1)라 Jira에 빌드 정보가 없으면 비울 수 없음(사용자: Jira에 빈칸이 많다).

## 사용자 결정 (10/28)

- 범위: 위 17건. PR #71(병합 대기)에 이어서. 사내 추가 정보 요청(7·11·13번)은 보류 — 원인을 사외에서 확정 못 한 채 고친 것이 있다(7: Jira 키 작업은 재현 안 됨, 13: `-` 잘림은 재현 안 됨 — 80자 자름을 원인으로 보고 고침, 12: 사외에서는 후보 원인만 확인).
- 3: skip 대신 사내에서도 통과하게(임시 플러그인 루트), offline_eval은 기본 루트 부분만 사내 skip. 4a: `parser_backends/site/`만 예외. 4b: 기준 변경 없음(PR #71이 같은 문구를 넣음).
- 5: `--evidence`에는 `--cause` 필수. analyze의 `--around` 경로는 그대로(P2).
- 6: null 키 제거 + 고정 질문 `missing_question`. `write-flow.md`는 안 고침(P2).
- 8: 뼈대 CODEOWNERS 활성 줄은 유지, 새 점검 `s4a.codeowners`. "ock-ord" = `mock-org`.
- 9: 최소 `remove-parser-rule` op. 뼈대 placeholder 규칙에 `reason: placeholder` 표시(RILJ 포함, 데이터 스택 태그 제외). **원칙·`CLAUDE.md`: 파서 규칙 삭제도 사용자 확인.**
- 10: 같은 owner 재획득 허용, 출력 owner 마스킹. 11: 자유 텍스트 댓글은 1건으로 저장, 이슈 본문 자유 텍스트는 거부.
- 12: 응답 즉시 반환·프로세스 그룹 종료·서버당 10초·진단 필드. 병렬 점검·새 플래그는 P2.
- 14: 세 종류(placeholder 규칙·TODO(SITE)·모의값) 집계, 새 `s6.mock`(사유로 면제 가능). 15: 기본값 `^MOCKCL-\d+$`.
- 17: `sw` 선택 필드(모르면 키 생략), 운영 DB 자기 스키마의 `required`를 따름. **`schema_version`·마이그레이션 없음** → 결정 (d)·`06 §6.4`를 "구조 변경은 올림, 호환 변경은 올리지 않고 운영 DB `schema/`를 메인테이너 PR로"로 고침.
- 상세 결정표 원본은 세션 scratchpad에만 있었다(레포에 없음). 위 요약이 기준이다.

## 바뀐 파일 (항목별, 직접 확인할 것)

| # | 주요 파일 | 새 테스트 |
|---|---|---|
| 1·9 | `common/yamldoc.py`, `dbadd/ops/parser_rules.py`, `dbadd/drift.py`, `common/draftcheck.py`, `plugin/schemas/plan.schema.json`(+ 샘플), `tools/make_db_skeleton.py` | `test_yamldoc.py`, `test_parser_rule_remove.py` |
| 2·8(점검)·14·15·16 | `tools/site_checks.py`, 샘플 DB `issue-db.config.yaml`·`.github/CODEOWNERS`, `dbadd/ops/fix.py`, `db_lint.py` | `test_site_checks.py`, `test_sample_db.py`, `test_db_lint.py` |
| 3·4 | `test_platform_rawcheck.py`, `test_s0_stats.py`, `test_commands.py`, `test_android_identity.py`, `10-skill-eval.md` | — |
| 5·6·17 | `parse_logcat.py`, `jira_fields.py`, `dbadd/core.py`, `dbadd/ops/jira.py`, `common/issuedb.py`, 샘플 `schema/issue.schema.json`·`templates/issue.yaml`, `reference/record.md`·`db-authoring.md` | `test_record_optional_sw.py`, `test_jira_fields.py`, `test_masking.py` |
| 7·8(publish)·10 | `common/jobstatus.py`, `job_status.py`, `common/session_lock.py`, `dbpr/lock.py`·`publish.py`·`merge.py`·`worktree.py`, `tests/mocks/bin/gh_stub.py`, `reference/write-flow.md`, `commands/status.md` | `test_job_status.py`, `test_db_pr.py`, `test_lock_recovery.py` |
| 11·12 | `jira_bridge.py`(hook), `common/mcptools.py`, `config.py` | `test_jira_bridge_formats.py`, `test_config_setup.py` |
| 13 | `tools/site_step.py` | `test_site_step.py` |
| 문서 | `contracts.md`(+ 생성 `contracts-cli.md`), 02·03·04·06·07·12·14·15, `GUIDE.md`, `CLAUDE.md`, `DRAFT_NOTES.md`, `REIMPORT_NOTES_1028.md` | — |

## 검증 사실 (커밋 전)

- 전체 pytest: 2,212 통과, 실패 1(`test_show_guard::test_hook_replay_counts_without_content` — 수정 전 HEAD에서도 같은 실패, 환경 의존). 리뷰 뒤 고친 부분은 관련 135개만 다시 돌림.
- `gen_contracts.py --check`·`sync_schemas.py --check`·`check_boundary.py` 통과. 3.10은 컴파일(`compileall`)과 일부 테스트만 확인.
- eval은 돌리지 않았다. `reference/record.md`·`db-authoring.md`·`write-flow.md`가 바뀌어 eval 30·50 등이 닿는다(사외 결과 미갱신).
- 크기 기준 근처: `db-authoring.md` 12,264/12,288B, `write-flow.md` 15,869/15,872B, `CLAUDE.md` 4,041B, `DRAFT_NOTES.md` 8,172B.

## 리뷰 결과 기록

리뷰를 마치면 이 문서 맨 위에 결과 한 줄(P0·P1 수, 수정 커밋)을 넣고, P2는 `DRAFT_NOTES.md` 또는 `REIMPORT_NOTES_1028.md` §7에 남긴다.
