# 외부 리뷰 요청서 — 11/19~11/20 작업 (플러그인 + 포털)

> 이 문서는 리뷰어에게 줄 **맥락과 규칙**만 담는다. 작성자(Claude)의 자체 평가와 "고쳤다·잘 된다"는 주장은 뺐다. 남아 있으면 그것도 발견으로 보고한다.
> 이 문서의 설명도 검증 대상이다. 코드·문서와 다르면 그 차이를 발견으로 보고한다.
> 작성자가 잰 숫자, 리뷰 이력, 작성자가 아는 한계는 **별도 파일** `REVIEW_BRIEF_1119_1120_AUTHOR_NOTES.md`에 있다. §7의 1~4를 다 쓴 **뒤에** 연다.

## 0. 붙여 넣을 요청문 (Claude·Codex 같은 문장)

```
레포 github.com/edgesmith-k/telephony-triage 의 브랜치 review/1119-1120 (코드 기준 커밋 77b877a1, 그 뒤 커밋은 요청서뿐) 와
레포 github.com/edgesmith-k/triage-screener 의 브랜치 feat/comment-clues-1120 (커밋 e71b71f)를 리뷰해 줘.
맥락과 규칙은 첫 레포의 docs/development/REVIEW_BRIEF_1119_1120.md 에 있다.
§4 "편향 방지"를 먼저 지키고, §5의 축을 모두 다뤄 줘. 결과는 §7 형식으로.
같은 폴더의 REVIEW_BRIEF_1119_1120_AUTHOR_NOTES.md 는 §7의 1~4를 다 쓴 뒤에만 열고,
거기 적힌 숫자·주장도 검증 대상으로 봐 줘.
```

## 1. 무엇인가 (사실만)

- **플러그인 telephony-triage**: Android·oFono 텔레포니 이슈를 Jira 이슈와 로그(logcat 등)로 분석한다. 스크립트가 로그를 읽어 "사건"(IPC 요청·응답, 상태 변화 등)을 뽑고, 이슈 DB(별도 비공개 레포)의 시그니처와 맞춰 원인 후보를 낸다. 모델은 문제 파악·탐색·심층 분석과 리포트를 맡는다. 설계 지도 `docs/design/README.md`, 표·정의의 정본 `docs/design/contracts.md`. 구조 설명은 `docs/development/CODEX_HOLISTIC_REVIEW_BRIEF.md` §1만 참고한다(그 문서는 11/09의 다른 리뷰 요청서라 요청문·대상은 이번과 무관하다).
- **포털 triage-screener**: 사내 Jira 이슈를 주기적으로 읽어 플러그인으로 "선별"(모델 없이 스크립트만)하고, 결과 카드로 보여 주고, 사람이 요청하거나 조건이 맞으면 분석(모델)을 돌린다. 선별 결과가 "확실한 일치"면 자동 분석을 건너뛸 수 있다(`auto_skip_confident`).
- **실행 환경**: 사내에서는 OpenCode + 사내 모델로 돈다(`opencode/`, `tt-oc`). 사외 개발 PC에는 사내 로그·사내 Jira가 없다. 레포의 로그·사례는 AOSP·에뮬레이터·합성 근거만 쓴다.
- **이번 작업의 단계 이름**: 단계 4 = 실패 지점이 없으면 원인을 보류하는 "판단 상태(`decision`)". 단계 5-1 = 실패 지점의 사건에 실제로 붙은 원인만 채택하는 "자격 검사". 단계 5-2 = 모델의 문제 파악 결과(`problem.json`)와 Jira 코멘트를 실패 지점 단서로 쓰기.
- **사용자가 정한 우선순위**: 틀린 원인을 "채택"하는 것을 가장 피한다. 원인이 "보류"되면 포털이 자동 분석(사내 모델 비용)을 돌리거나 사람이 원인을 직접 본다. 이 우선순위와 그 비용(보류가 얼마나 많아지는가)도 리뷰 대상이다. 레포 안 기준값 `tests/fixtures/accuracy/baseline.json`의 `by_condition`에 조건별 채택·보류 수가 있다.

## 2. 리뷰 대상

### 2-a. 플러그인: 브랜치 `review/1119-1120`

`main`(89cd7dbf) 위에 열린 PR 여섯을 머리 브랜치 셋(#168, #170, #169)으로 리뷰용으로만 합친 브랜치다(합침 커밋 3570b6a6·906e0faa·77b877a1, 충돌 없음). #165~#167은 #170·#169 아래에 쌓여 있어 함께 들어온다. #169와 #170은 둘 다 #167 위의 형제 브랜치라, 둘이 함께 있는 상태는 이 리뷰 브랜치에만 있다. 이 브랜치는 병합 대상이 아니다.

| PR | 브랜치(head) | base | 크기(테스트 포함) | 요지 |
|---|---|---|---|---|
| #165 | `feat/stage4-decision` (1cd95c74) | main | 60파일 +1097/−85 | 단계 4 판단 상태: 실패 지점이 없으면 원인 보류 |
| #166 | `feat/stage5-eligibility` (d815745c) | #165 | 115파일 +2543/−277 | 단계 5-1 자격 검사 |
| #167 | `feat/stage5-problem` (1a93a9e7) | #166 | 45파일 +2470/−175 | 단계 5-2: problem.json 읽기 |
| #169 | `feat/eval-adopt-1120` (a0eaa58e) | #167 | 6파일 +483/−6 | 채택 경로 eval 113과 '보류인데 원인 단정' 채점 행 |
| #170 | `feat/auto-clue-1120` (52347797) | #167 | 33파일 +1377/−127 | Jira 코멘트 단서를 run이 자동으로 쓴다(모델 없이) |
| #168 | `fix/oc-runtime-pins-1119` (f669ce9a) | main | 8파일 +299/−17 | OpenCode 실행 환경 고정: guard python과 opencode 경로 |

- 합친 범위 전체: `git diff 89cd7dbf 77b877a1` (173파일 +8004/−422). 새 clone에서 PR별로는 `git diff origin/<base>...origin/<branch>`.
- 주로 바뀐 코드: `plugin/scripts/common/eligibility.py`(새), `common/lookat.py`(새), `triagelib/anchor.py`, `triagelib/driver.py`, `triagelib/problem.py`, `triagelib/report.py`, `triagelib/output.py`, `triagelib/cache.py`, `match_signatures.py`, `jira_fields.py`, `jira_bridge.py`, `parse_logcat.py`, `guard.py`, `common/issuepost.py`, `common/oc_adapter.py`, `opencode/bin/tt-oc`, `tools/offline_eval.py`, `tools/gen_opencode.py`, `tests/skill_evals/grade.py`.
- 출력 형식: `plugin/schemas/output/analysis.schema.json`(`decision`이 필수가 됨).
- 기대값·eval 입력: `tests/fixtures/accuracy/baseline.json`(기대값 다시 만듦, 약 +2200줄), `templates/module-skills/*/evals/*` 아래 eval 입력 약 50개.
- 문서: `docs/design/contracts.md`(`decision` 항목 248행 부근), `contracts-cli.md`, `02-config.md`, `08-safety.md`. 설정: `plugin/site-defaults.example.yaml`의 `eligibility:`.

### 2-b. 플러그인: 이미 병합된 11/18~11/19 PR (가볍게)

`main`에 병합됐고, 11/19 사내 반입 묶음(import-20261119b)에 들어갔다. 반입 뒤 사내 첫 실행이 OpenCode 권한 차단으로 멈춰, 사내에서 동작을 확인한 적은 아직 없다. 레포 안 `DRAFT_NOTES.md`의 반입 기록은 이보다 앞선 시점의 것이다. 범위 `f12e9049..89cd7dbf`(first-parent 합침 커밋 5개).

| PR | 요지 |
|---|---|
| #160 | 기준값 도구 시험 파일 두 개에 실행 권한 |
| #161 | analyze 인자 설명에 --problem-only |
| #162 | 사내 레포·사용자 HOME에 흔들리던 시험 격리 |
| #163 | 단계 3 줄 읽기: token·결과 표기 넓히기, IPC 기록에 SIM 슬롯 |
| #164 | DRAFT_NOTES 11/19(문서만) |

### 2-c. 포털: 브랜치 `feat/comment-clues-1120` (e71b71f)

스택 PR 셋이 이 브랜치 하나에 모두 들어 있다. 범위 `git diff origin/main...origin/feat/comment-clues-1120`.

| PR | 브랜치(head) | base | 바뀐 코드 | 요지 |
|---|---|---|---|---|
| #15 | `feat/stage4-decision` (f7dd38d) | main | jobs.py, screener.py, session.py, web.py | 플러그인 판단 상태를 따른다 |
| #16 | `feat/stage5-reasons` (7b85cf4) | #15 | screener.py, web.py | 원인 보류 사유 3개 |
| #17 | `feat/comment-clues-1120` (e71b71f) | #16 | jira.py, jobs.py, screener.py, session.py, web.py | 선별에 Jira 댓글 넘기기 |

포털 단위 시험은 가짜 플러그인(`tests/fakeplugin`)으로 돈다. 진짜 플러그인과 붙인 통합 시험은 없다.

### 2-d. 짝 관계 (작성자가 정한 배포 묶음 — 이것도 리뷰 대상)

- 플러그인 #165~#167과 포털 #15·#16은 함께 배포한다고 적혀 있다. 옛 포털 + 새 플러그인, 새 포털 + 옛 플러그인 조합에서 무슨 일이 생기는지도 본다.
- 플러그인 #170과 포털 #17도 짝이다.

## 3. 문서가 말하는 목표 동작 (검증 대상 — 코드가 이대로인지 확인)

정본은 `contracts.md`의 `decision` 항목과 `common/eligibility.py` 설명이다. 요지만 옮긴다.

- **실패 지점 기준(앵커)**: 담당자가 짚은 실패 지점(명령 인자 `--look-at` 줄, `--steps-file` TC 구간, 로그 안 FAIL 마커)이나 단서(`problem.json`의 단서, Jira 코멘트 단서)로 로그 위치를 정한다.
- **채택 조건**: 그 위치의 "실패 사건"에 실제로 붙은 시그니처 원인만 "원인 채택"으로 낸다. 근처의 다른 사건 원인은 "관측된 규칙 일치"로만 보인다. 위치가 없거나 모호하거나 사건이 성공 응답이면 "원인 보류"와 사유 코드를 낸다.
- **위치 확신도**: 채택(accepted)일 때 `confirmed`는 앵커가 붙은 사건의 근거 줄 그 자체이거나 같은 RIL 요청일 때(`same_line`, 조건 줄로만 맞은 경우는 제외)뿐이고, 그 밖은 `found`다. 보류이면 앵커에서 정한 상태가 그대로 남는다. 코멘트 단서 출처는 늘 `found`다.
- **코멘트 단서 자동 추출(#170)**: `problem.json`이 없을 때 Jira 코멘트의 이번 회차(마지막 재시험 요청 뒤, 낱말은 설정 `retest_words`)에서 IPC 이름+token, logcat 시각이 붙은 줄을 스크립트로 뽑는다. 코멘트 목록이 일부만 왔거나(`comments_partial`) 전체 수·순서를 알 수 없으면(`comments_unchecked`) 뽑지 않는다. 단서 하나라도 확인되지 않거나 token 값이 둘 이상이면 보류한다. 설정 `eligibility.comment_clues`, `eligibility.comment_adopt`.
- **포털 "확실한 일치"**: 기존 조건(판정이 match·regression, 강도 high, 버그 아님 경고·약화 주의 없음)에 더해, 플러그인 판단이 accepted이고, 위치가 confirmed이며, 근처(near)·코멘트 출처가 아니고, 근거가 `same_line`일 때만. 자동 분석을 건너뛰려면 사용자가 질문을 적지 않았고 심층 분석 요청도 아니어야 한다(`portal/screener.py` 563~585행 부근).
- **포털 코멘트 넘기기(#17)**: 선별 때 Jira 코멘트를 다시 읽어 최근 쪽을 넘기고, 페이지 응답이 요청과 어긋나면 "일부만 읽음"으로 둔다. 새로 읽지 못하면 코멘트를 넘기지 않는다.
- **#168**: tt-oc가 보호 장치(guard)를 tt-oc와 같은 python으로 띄우고, venv의 bin을 PATH 앞에 두고, 값이 빈 `OPENCODE_*` 환경 변수를 지우고, 설치 때 opencode 실행 파일 경로를 기록한다. doctor가 보호 장치 python을 실제로 띄워 보고 opencode 버전이 바뀌면 알린다.

## 4. 편향 방지 (먼저 읽고 지킨다)

1. **PR 본문, 커밋 메시지, 이 문서, 코드 주석은 주장이다.** 코드와 실행 결과로 확인한 것만 사실로 적는다. 확인하지 못한 것은 "추정" 또는 "실행 안 함"으로 표시한다.
2. **PR 본문은 날짜별 절이 쌓여 있다.** 앞 절의 규칙이 뒤 절에서 바뀐 곳이 있다. 지금 코드가 기준이다.
3. **레포 밖 기록을 근거로 쓰지 않는다.** 코드·PR 본문에 나오는 `Y1`, `H18`, "설계 메모 M4", `STAGE4-DECISION-1119.md`, A 번호 등은 작성자 PC의 기록이라 볼 수 없다. 필요하면 §7-4로 묻는다.
4. **앞선 리뷰가 있었다는 사실에 기대지 않는다.** "이미 리뷰됐으니 괜찮다"도, "리뷰가 많았으니 문제가 많다"도 근거가 아니다.
5. **장점과 약점을 같은 기준으로 적는다.** 칭찬도 근거(파일·실행)가 있어야 하고, 근거 없는 지적은 추정으로 표시한다.
6. **작성자의 설계 방향 자체도 의심해도 된다.** 예: 규칙을 계속 덧붙이는 방식이 유지 가능한가, 보류가 너무 많아 쓸모가 줄지 않는가, 사내 자료 없이 정한 규칙이 사내에서 맞을까. 대안을 낼 때는 그 대안의 비용도 적는다.
7. **테스트 통과를 정확성의 증거로 쓰지 않는다.** 테스트도 틀릴 수 있다(공허한 통과, 다시 만든 기대값이 동작을 고정만 함, 합성 fixture가 실제 로그 모양을 대표하지 못함).
8. **사내 사정은 모른다고 적는다.** 사내 Jira MCP 응답 모양, 벤더 IPC 줄 모양, 재시험 요청 문구는 사외에서 확인되지 않았다. 그것에 기대는 판단은 조건부로 적는다.
9. `docs/history/`는 읽지 않는다(낡은 기록).

## 5. 리뷰 축 (모두 다룬다)

1. **틀린 채택**: 엉뚱한 사건의 원인을 "원인 채택"으로 내는 입력이 있는가. 가능하면 §6의 방법으로 작은 로그·이슈 YAML을 만들어 실제로 돌려 보인다.
2. **지나친 보류**: 사람이라면 분명히 채택할 흔한 경우를 보류하는가. 얼마나 흔할지도 추정한다.
3. **Jira 코멘트 처리**(플러그인 #170 + 포털 #17): 일부만 받은 목록, 순서가 다른 목록, 정정·인용·참고 줄, 재시험 회차 경계, 페이지 나눔, 다시 읽기 실패. 플러그인이 MCP 응답을 직접 받는 경로와 포털이 넘기는 경로가 다르게 동작하는지.
4. **플러그인과 포털의 약속**: `decision` 키 모양, 사유 코드, 옛/새 조합 동작, 포털의 "확실한 일치"가 플러그인 판단과 어긋나는 경우.
5. **사내 실행 환경(#168)**: 환경 변수·python·opencode 경로 고정이 막으려는 실패를 막는가, 새 실패를 만드는가(PATH, 셸 별칭, 권한, 스스로 업데이트되는 opencode).
6. **테스트 품질**: 핵심 줄을 되돌리면 테스트가 실패하는가. 다시 만든 `baseline.json`과 eval 입력이 옳음을 보는가, 지금 동작을 고정만 하는가.
7. **문서와 코드 일치**: `contracts.md`, `02-config.md`, `08-safety.md`, `site-defaults.example.yaml`의 설명이 코드와 같은가.
8. **복잡도·유지보수**: 같은 판단이 여러 곳에 흩어져 있는가, 지울 수 있는 규칙·분기가 있는가, 다음 사람이 규칙을 고칠 때 어디를 봐야 하는가.
9. **보안과 신뢰 경계**: 신뢰할 수 없는 Jira 코멘트 글이 스크립트 판정, `reference.json`, `report.md`(모델이 읽는 글)로 들어간다. `guard.py`의 `eligibility.json` 보호(08-safety.md), 포털의 코멘트 파일 권한.
10. **업그레이드·호환·부하**: `decision` 필수화와 캐시 형식 변경이 옛 작업 폴더·check-output에 주는 영향, 새 `eligibility:` 키가 없는 기존 사내 설정, 포털이 선별마다 Jira를 다시 읽는 요청 수.
11. **11/18~11/19 병합분(§2-b)**: 위 축 가운데 해당하는 것만 가볍게.

## 6. 실행 방법

- 설치: 레포 루트에서 `pip install '.[test]'`(pytest-xdist 포함). Linux, Python 3.10 이상.
- 플러그인 테스트: `python3 -m pytest -q -n 8 tests`. opencode 1.19.5가 없으면 OpenCode 실행 시험이, node가 없으면 guard JS 시험 등이 건너뛰거나 실패할 수 있다(그 경우 이름만 적는다).
- 판단만 보는 시험: `tests/test_eligibility.py`, `tests/test_extract_clues.py`, `tests/test_accuracy_baseline.py`, `tests/test_jira_bridge_formats.py`.
- 모델 없이 한 이슈 돌리기(이슈 DB는 비공개라 시험용 씨앗 DB를 만든다):
  ```
  python3 tests/helpers/make_plugin_root.py --out /tmp/proot
  python3 tests/helpers/make_accuracy_fixtures.py --seed-db /tmp/seeddb
  python3 /tmp/proot/scripts/triage.py run KEY-1 --offline-db /tmp/seeddb --out /tmp/job1 \
      --logs tests/fixtures/accuracy/tokpos.log --issue-file issue.yaml [--look-at …] [--steps-file …]
  ```
  - `--issue-file`은 YAML이다. 모양 예시는 `tests/test_extract_clues.py`의 `_run()`. 코멘트는 `fields.comment: {startAt, total, comments: [{body, created?}]}`.
  - 출력: `reference.json`, `eligibility.json`, `analysis.json`, `report.md`.
- 경계·문서 검사: `python3 tools/check_boundary.py --mode external`, `python3 tools/gen_contracts.py --check`.
- 포털 테스트: 포털 레포 루트에서 `PYTHONPATH=.:tests python3 -m unittest discover -s tests`(추가 설치 없음).
- 모델 호출은 하지 않는다. 모델을 부르는 평가(eval)는 비용 승인 대상이다.

## 7. 결과 형식

1. **한 단락 결론**: 배포해도 되는가, 무엇이 막는가.
2. **발견 목록**: 심각도(P0 틀린 채택·데이터 손실·보안 / P1 흔한 경우의 잘못된 동작 / P2 드문 경우·정리), 고칠 PR 번호(#165~#170, 포털 #15~#17), 파일:줄, 재현 입력, 실행 여부(실행함/추정), 고칠 방향(선택).
3. **장점과 약점 표**: §5 축마다 같은 기준으로.
4. **작성자에게 묻는 것**: 코드만으로 판단할 수 없는 것.
5. **작성자 메모를 읽은 뒤**: `REVIEW_BRIEF_1119_1120_AUTHOR_NOTES.md`의 숫자·주장 가운데 네 결과와 다른 것.

## 부록. 배경 문서

- `docs/design/12-principles.md`(원칙), `docs/design/07-workflow.md`(분석 단계), `docs/design/contracts.md`(정의).
- 실행 환경: `docs/development/RUNTIMES.md`, `opencode/README.md`.
