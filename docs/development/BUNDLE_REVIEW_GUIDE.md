# 묶음 리뷰 안내 (일요일 사용자 리뷰용)

범위: `77e2827`(묶음 import-20261103) → `f5a4811`(11/06 G 반입 노트) 141커밋, 599파일. 다음 묶음은 토 11/7 18:00 KST(기준 `b4a5b42` + G).
사실의 출처는 `MODULE_SKILLS_RESULT.md`(결과 노트)·`MODULE_SKILLS_DECISIONS.md`(결정 원문)·`DRAFT_NOTES.md`·git log이다. 사람이 읽는 요약은 `CONCERNS.md`(HTML `docs/materials/21-concerns.html`).

## 읽는 법

```
git log --oneline 77e2827..HEAD          # 단계 이름이 커밋 앞머리(H-A1, H C1+D O7 …)
git diff --stat 77e2827..HEAD -- plugin/ opencode/ tools/   # 코드만
git diff 77e2827..HEAD -- <파일>
```
`templates/module-skills/*/cases`·`tests/fixtures`는 생성물·사례가 많으니 영역별로 따로 본다.

## 영역별로 볼 것

| 영역 | 주요 파일 | 확인할 것 |
|---|---|---|
| A1·A2 +1 병합·확인 화면 | `plugin/scripts/dbpr/merge.py`·`db_pr.py`·`reference/write-flow.md` | 바로 병합 삭제, '승인 필요' PR은 `needs_approval`로 거부, +1 거부에만 +1 안내 |
| guard 규칙 11 | `plugin/scripts/guard.py`·`show_guard.py` | 쉬운 P1 3개·P2 묶음 7개, 결과 노트의 "약해진 판정" 수 |
| B1·B2 모듈 스킬 받기·5-1/5-2 | `common/moduleskills.py`·`modulefilter.py`·`triagelib/modulecmd.py`·`reference/module-skills.md`·`SKILL.md` | 관리 clone 받기·점검, `prefer: module|skill`, deep check-output 결과 줄, 답 전 원문 열람 안 함 |
| B2 마스킹 | `common/masking.py`(로그 줄 전용 M1~M11, M12 IPv6 경계) | 결과 노트 "마스킹 관문 1 기준 미달 2건"(누출 아님) |
| C1+D 모듈 문서·사례 | `templates/module-skills/{ofono,android}/`(`_common`, 모듈마다 SKILL·analyzer·explore) | 사례 42개(oFono 21·Android 21, 처음 31 + 보정 11), 실제 발췌 사례는 마스킹 |
| C1+D 보정 | `_common/components.md` 역할 표, 모듈 explore 증상 표, `tags.yaml` `level`·`ipc` | 증상별 첫 점검 표, 대체 근거, 데몬 역할(지금 이름·구 이름), 선언 없으면 출력 바이트 동일 |
| B 이슈 DB 작성 지침 | `reference/db-authoring.md`·`03-issue-db §5.7`·`db_lint.py --advice` | OR 시그니처, `must_not_match` "일어났음" 줄, 플래그 없으면 출력 동일 |
| C′ 부분 일치·코드 대조 | `match_signatures.py`·`triagelib/report.py`·`code_roots.py find-text` | 후보 없음/1위 S=1·C=0일 때만, 출력은 path:line, 제안은 마스킹 로그 줄로만 |
| C drift 점검 | `tools/site_audit.py`(`site_step.py audit`) | "자주 맞던 시그니처 0건", 빌드 순서 모순은 skip 행 |
| 실행 중 IMSI/ICCID 갈린 값 | `common/dumpjoin.py`·`masking.py` | 골든·mask-gate 차이 0, 첨부 로그 마스킹 수 변화 0 |
| 후보 방식 채점 | `module_eval.py`·`tools/module_answers.py` | 탐색 27개 후보 1~3개 + 가장 유력, accept/trap, `GRADER_VERSION 2` |
| 계획 I OpenCode·사내 모델 | `opencode/`·`common/oc_adapter.py`·`oc_jira_gate.py`·`docs/RUNTIME_ADOPTION.md` | bash 허용 목록, guard 연결 파일 편집 거부, Jira 읽기는 `runtime-check opencode --jira` 통과 뒤 설정 |
| F 사내 트랙 | `tools/site_step.py`(modules·modules coverage·audit) | 토큰 0, MS-1·MS-2 |
| G 문서 | `docs/SITE_INSTALL.md`·`docs/TEAM_GUIDE.md`·결과 노트 "반입 노트" | 반입 뒤 사내 site eval 표·사내 할 일 8단계 |

## 주요 결정

`MODULE_SKILLS_DECISIONS.md` — P0·P1만 고치고 P2는 반입 뒤 후보(결정 (r)), 사내 토큰 최소(81회 재측정은 사외 G), 유료 eval $25 미리 승인, G 81회 상한 $80 미리 승인, 11/06 08:20 결정(정답 표 md 확인 뒤 유료 1회차, IMSI/ICCID 이번 묶음, C·C′ + 코드 대조 이번 묶음).

## 알려진 P2 (반입 뒤 후보)

`MODULE_SKILLS_RESULT.md`의 절: "P2 — C·C′·마스킹·후보 채점", "P2 — C1+D 보정", "근거 줄 소실 대응 B"의 P2 줄, "P2 — C1+D", "P2 — B1·B2 설정·guard", "P2 — B1·B2 통합 재리뷰", "P2 — 계획 I-2", "P2 — C0", "P2 — guard P2 묶음", "P2 — guard 쉬운 P1", "P2 — A2", "P2 — 병합 쪽"·"eval 75 채점"·"guard 규칙 11". 이번 묶음 밖 할 일은 "나중에 할 일"(증상 표 "(초안)" 행 정정, 행 130B 기준).

## 유료 eval 장부 ($25 미리 승인 안)

| 묶음 | 실제 | 누적 |
|---|---|---|
| C0 재실행 (6회) | $0.365 | $0.365 |
| B2 통합 eval (14회) | $4.36 | $4.73 |
| B2 수정 뒤 재실행 (12회) | $4.22 | $8.95 |
| B2 2차 수정 뒤 재실행 (6회) | $2.29 | $11.24 |

## 남은 것

1. 사용자 정답 표 확인(후보 방식 "인정 후보 / 함정") → 모듈 eval 유료 1회차(dry-run 추정 84회 $5.11), 미달이면 2회차.
2. 81회 전체 재측정(사외 G, 상한 $80).
3. 묶음(11/7) — 사람 확인·태그·반입은 사용자(SITE_INSTALL §8·반입 노트).
