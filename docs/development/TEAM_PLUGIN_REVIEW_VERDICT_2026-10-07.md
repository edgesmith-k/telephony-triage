# 팀 플러그인 검토 판정 (2026-10-07, 2차 보강 10/08)

- **기준**: main `d1fa863` 위의 브랜치 `tp/team-review`(TP-1 코드, TP-2 문서·eval, 2차 수정). **미커밋 상태** — 커밋 SHA는 커밋 뒤 이 줄에 적는다.
- **원문은 현행 지침이 아니다.** `docs/history/TEAM_PLUGIN_*_2026-10-07.md`는 작성 당시 제안·진단이고 틀린 서술이 있다(아래). 지침은 이 판정과 설계 문서(`docs/design/`)다. A~D 검증 표는 레포 밖 세션 자료라 복제하지 않고, 아래 행마다 재현 앵커(`file:line` 또는 명령)만 둔다.
- **상태 구분**: (코드 반영) 아래 "적용" 행 — 검증은 둘로 나눈다 — 수정 전(2차 의견 재검토 시점): 대상 테스트 15 통과. 수정 후(10/08, 2차 수정·리뷰 차단 반영 뒤): 전체 pytest 1093 통과·실패 4(Windows 환경: gh 토큰·`:` 파일명·zip 모드·guard 경로), `check_boundary`·`gen_contracts` 통과. (사내 미검증) 오류율·정확도 기준치는 S-1 합의, eval 59·60 실행은 S-2, 보존 기간·원문 정책은 S14.

## 적용 (반입 전)

| 항목 (출처) | 내용 | 재현 앵커 |
|---|---|---|
| 오탐 정의 (A7, C-G3, R-41) | `cause: null` 유형만 후보는 오탐 아님. `type_only` = unresolved 중 후보가 비어 있지 않고 전부 null. 혼합 `[null, X]`는 오탐 | `tools/offline_eval.py:151,167` / `pytest tests/test_commands.py -k offline` |
| 오류율 (C-G2) | `error_rate = 오류 / 전체 시도`, 오류 항목은 정확도에서 빠지되 숨기지 않음. S-5는 정확도 기준과 오류율 상한을 모두 충족해야 하고 null이면 미충족 | `tools/offline_eval.py:166`, `15-local-draft.md` S-5 |
| 작업 디렉토리 정리 (A3, C-G1) | `cleanup --older-than`은 도구가 만든 폴더(작업 키 + 표식)만, 폴더·하위·파일 mtime이 모두 기준일 밖일 때 후보. 원문만 남은 중단 작업은 포함. **`plan.json` 있고 PR 번호 없는 폴더는 제외하고 `retained`로 표시**(경과 일수·경로·원문 잔류, `unpublished`/`pushed-no-pr` 두 상태·복구 안내. 표시만으로 보존 문제가 해결된 것이 아니다). 삭제 실패는 `failed` | `worktree.py:286-310,330-350` / `pytest tests/test_commands.py -k cleanup` |
| `pr.json` 승인 결속 (A1, C-G4) | summary가 sha256을 `state.json`에 저장, publish가 없거나 다르면 push 없이 종료 1. 같은 로컬 작업 흐름에서 확인받은 PR 내용과 실제 게시 내용이 달라질 수 있는 무결성 문제이고, 서버 리뷰는 병합만 통제한다(S5 확인 전엔 설계 전제). PR 본문은 리뷰 전에 게시된다 | `publish.py:365,448-453` / `pytest tests/test_db_pr.py -k "pr_json or pr_digest"` |
| 프롬프트 주입 eval (A-R3) | eval 59·60 + 모의 Jira MOCK-1003·1004. `grade.py` 전용 검사 없음 = 수동 채점. 도구 호출 "시도"(hook이 막은 것 포함)도 실패. **실행은 S-2** | `python3 -c "import json;print(len(json.load(open('tests/skill_evals/evals.json',encoding='utf-8'))['evals']))"` |
| 14-site 보강 (A2·A6, C-G6~G8) | S1(PostToolUse 대체·guard 형식), S2(되돌리기·백업), S5(권한 부여), S14(원문 보존) | `docs/design/14-site.md:24,25,28,37` |

**원문 보존은 부분 해결이다.** 계획 보존은 원문 무기한 보존 허용이 아니다. 미게시 계획 폴더의 원문 잔류는 S14에서 결정한다. 90일은 cleanup을 실행할 때 후보를 고르는 기준일일 뿐이다.

## 사내 S-n / 파일럿 뒤 (보류, 재검토 조건)

| 항목 | 시점·조건 | 앵커 |
|---|---|---|
| `max_tokens_hint` 죽은 키 (B-T5) | S-4a. 쓸지 지울지 결정 | `site-defaults.example.yaml:113` |
| 코드 Read 범위 line 힌트 (B-T4) | S-2 측정 뒤(실제 트리에서만 측정) | `triagelib/driver.py:572-582` |
| setup Jira 없음 → 중단 (A-U1) | S-3(사용자 범위 등록 여부) | `14-site.md:26` |
| 카테고리별 분해 (A-R4) | S-5 라벨셋에 `category` 키를 만들 때 | `15-local-draft.md:80` |
| 검색 SHA 표시 (A-U4, C-G14) | 파일럿 뒤: 오래된 스냅샷 혼동이 관찰될 때 | `ARCHITECTURE_REVIEW_2026-10.md` 색인 |
| `fit()` 생략 표시 `omitted` (B-T0) | 파일럿 뒤. **`analysis.json`만 소비하는 웹·API·에이전트가 생기면 생략 계약부터 재검토** | `contracts.md`, `reference/` |
| 공유 전 report.md 검사 (C-G5) | 파일럿 뒤(공유 흐름은 v1 밖) | 색인 |
| 확장 아이디어 1~10·웹 포털 (D) | 파일럿 뒤 후보. 반입 전 가치 없음 | `docs/history/TEAM_PLUGIN_EXPANSION_IDEAS_*` |

## 적용 안 함

| 항목 | 이유 | 앵커 |
|---|---|---|
| 검색 markdown 연결 (B-T1) | W2 실측 +20~32%로 되돌림 | `docs/history/CHANGES.md:705-707` |
| 재분석 변경분만 전달 (B-T3) | 3C 실패 원인(결정적 칸 누락)과 충돌 | `docs/history/CHANGES.md` 3C |
| 예산 강제·선택적 에이전트·validate-plan (B-T5~T7) | API 없음 / 런타임 무관 / 이미 있음 | `contracts.md` stage 행(계획 형식 검사) |
| A4·A5·O1~O3·U2·U3·U5·R2·RM-1~3, C-G9~G24 | 해결·설계됨이거나 보류 결정(G·웹 UI·RF-8) 유지 | `DRAFT_NOTES.md` 남은 일 |

## 원문의 틀리거나 낡은 서술

- (낡음) 컨텍스트 문서 F8(L23) "스테이징된 변경이 있다": 작성 당시 상태이고 이후 커밋(`c24dd0e`·`fb9f45a`)되어 현재 상태 설명으로는 낡았다.
- (틀림) 토큰 검토 T1 "검색 결과 markdown 연결로 절약": W2 실측은 반대(증가).
- (부분) 확장 아이디어 3 "semantic rule diff": 의미 단위 변경 계산은 있다(`common/rulediff.py`, db_verify 검사 대상). 승인자용 의미 diff **화면**은 없다 — IDEAS 3의 새 기능은 화면이다.
- (부분) 확장 아이디어 6 "feedback" 묶음: feedback은 수락률 집계용이고 후보 수집 입력이 아니다.
- (부분 오류) 운영 검토 A4 Windows 전제, O2 `usage_stats.py` 누락. A1 위협 범위 표현은 위 "`pr.json` 승인 결속" 행처럼 정정한다.
