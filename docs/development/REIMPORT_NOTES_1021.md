# 재반입 노트 — 10/21 사내 피드백 반영분 (PR #71)

사내 피드백 10건(10/21)을 사외에서 고친 묶음을 사내 레포에 넣을 때 볼 것. 절차는 `docs/SITE_INSTALL.md §8`, 이 문서는 이번 묶음에만 해당하는 것.

## 1. 반입 전에 (멈춤 방지)

- **사내에서 직접 넣은 문구를 먼저 되돌린다.** 사내에서 `plugin/skills/telephony-triage/SKILL.md`(5-1 괄호, Step 7 `규칙 제안:` 줄)와 `docs/design/16-existing-assets.md §16.5` 계약에 문구를 넣었다면, 기준선 뒤 사내에서 고친 사외 파일이라 `import_draft.py`가 종료 1로 멈춘다. 새 묶음에 같은 내용이 오타를 고친 정식 문구로 들어 있으므로 §8 "멈췄을 때" 첫 줄대로 마지막 반입 버전으로 되돌리고 커밋한 뒤 다시 실행한다.
  - 고친 오타: `ip`→`op`, `add-parse-rule`→`add-parser-rule`, `upate`→`update`. 줄 머리표는 `[이슈 DB]`·`[스킬]`.
- 골든·conftest·`test_parse_logcat.py`·`masking.py`를 임시로 고쳐 두었어도 같다. 되돌리고 새 묶음 것을 쓴다.

## 2. 반입 뒤 바뀌는 것

| 항목 | 사내에서 할 일 |
|---|---|
| 골든 합성 줄 예외(16 §16.6 1항) | 합성 줄을 보충한 케이스만 그 골든 JSON(`tests/golden/<이름>.golden.json`) **최상위**에 `"synthetic": {"reason": "<왜 실제 로그에 없는지>"}`. 사유가 비면 `site_checks.py` `s4a.golden`이 실패한다. `test_golden.py --update`가 이 키를 남긴다 |
| 실제 site 백엔드 로드 | 사내 골든 테스트는 `real_site_backend` 픽스처를 쓴다(`parser_backends.site_real`로 따로 불러옴). 파일 경로로 직접 불러오던 임시 코드는 빼도 된다 |
| `test_site_defaults_required` | 사내 레포(`plugin/site-defaults.yaml` 있음)에서 자동 skip. skip이 정상 |
| `cid` 마스킹 | `DataCallResponse`·`SetupDataCallResult {…}` 안의 `cid`(데이터 콜 id)는 더 이상 가리지 않는다. 그 밖의 `cid=`는 그대로 가린다. 마스킹 결과·픽스처에 그런 줄이 있으면 출력이 달라질 수 있다 |
| contracts 주석 | `token` 등 자격증명처럼 보이는 필드 이름에 대한 메모. 동작 변화 없음 |
| 운영 이슈 DB 첫 push | `SITE_INSTALL.md §9`(S-4a, 도입 담당자 한 번). `config.py set issue_db.path` 뒤 옛 스냅샷 정리 안내가 출력된다(§7 "이슈 DB 경로를 바꿨을 때") |
| 분석 스킬 만들기 | `16 §16.5.1` 신설. 이슈 DB 뼈대에 `docs/analyzer-skills.md`가 추가돼 **뼈대 zip 해시가 바뀐다**. 이미 만든 운영 이슈 DB에는 이 파일을 복사해 넣는다(이슈 DB 변경이므로 PR로) |
| 리포트 안내 | `심층 분석: 해당 없음(…)` 줄 끝에 `(만드는 법: 이슈 DB docs/analyzer-skills.md)` |
| 규칙 제안 → Step 7 | 분석 스킬의 `규칙 제안:` 줄을 분류 확정 뒤 한 번 묻는다. `[이슈 DB]` 줄은 op 초안 → 승인분만 계획에 넣어 `db_verify`까지, `[스킬]` 줄은 계획에 넣지 않고 담당자용 patch `JOB/skill-suggestions/<스킬 이름>.patch`(분석 스킬 디렉토리 기준 unified diff, `mask_pii` 적용, 분석 스킬은 안 바꿈 — 담당자가 `git apply`)를 만든다. 10/22: diff·마스킹·`git apply --check`·안내 줄은 새 스크립트 `skill_patch.py`가 하고 안내 줄은 표시 보조 hook이 강제한다(표시 기록 `kind: patch` — 스킬 문서는 `reference/skill-patch.md`만 바뀌고 SKILL.md는 그대로). 스킬 디렉토리를 모르면 메모로만. 분석 스킬이 이 형식(16 §16.5)으로 쓰는지 확인 |
| verify-fix 빌드 기준(10/22) | AP 패치 기준: `modem`이 아닌 원인은 로그 빌드를 `fixed_in`과 비교하지 않는다(`build_check.status: not-compared`, 이전 빌드여도 종료 2 없음). 수정 패치가 들어간 빌드(main 반영 전 테스트 빌드 포함)의 로그면 되고, 로그 빌드는 그대로 `verification.build`. `modem` 원인은 기존 비교 규칙 그대로. 새 선택 인자 `--bundle <CI/CD 번들 번호>` → `verification.note`에 `CI/CD 번들 <N>`(이슈 DB 스키마 변경 없음 — `schema_version`·마이그레이션 불필요). `fixed_in`에 빌드 있는 항목 필요(모든 원인, `fixed` 스키마 조건)·회귀 판정(analyze Step 7)은 그대로. 기존 `fixed_in`·`verification` 데이터는 영향 없음. 스킬 문서는 `reference/verify.md` verify-fix 절만 바뀜 |
| 이슈 DB PR 바로 병합(10/22) | PR은 그대로 만든다. `issue_db.merge: self`(내장 기본)이고 병합 자격이 있으면 push 전 확인 화면에 병합 줄과 선택지 `push하고 바로 병합` / `push만(리뷰어에게)` / `취소`(추천 표시 없음)가 나오고, `push하고 바로 병합`이면 `db_pr publish … --and-merge` 한 명령(권한 확인 한 번)이 승인 커밋·PR 검사(검사가 없으면 `ci_mode: local`일 때만 통과)·`mergeStateStatus`(CLEAN·HAS_HOOKS)·메인테이너 경로·main 불변을 확인하고 `gh pr merge --<레포 허용 방식> --match-head-commit`(`--delete-branch` 없음). 검사 대기·상태 확인 중이면 `issue_db.merge_wait_seconds`(기본 600초)까지 기다리고, 안 되면 PR을 두고 사유와 재시도 명령 `db_pr merge --job <KEY> --approved <SHA>`를 낸다. "승인 필요"·메인테이너 경로 변경 PR은 선택지가 없다. guard: `publish`·`merge`는 ask(규칙 7), gh·MCP 직접 머지는 계속 거부(규칙 11), `merge-offer.json` 직접 쓰기 거부. **사내에서 할 일**: 리뷰어 머지를 유지할 팀이면 `site-defaults.yaml`에 `issue_db: {merge: review}`. 본인 병합이면 운영 이슈 DB 브랜치 보호를 `SITE_INSTALL.md §9` 3번대로 바꾼다(PR 필수 유지, CODEOWNERS 리뷰 필수 + 필수 승인 수 0, CODEOWNERS는 메인테이너 경로만 필수 — 카테고리 오너는 선택) — "필수 승인 0 + CODEOWNERS 리뷰" 조합이 사내 GHE에서 되는지 확인(TODO(SITE:S5)). 이슈 DB 뼈대·PR 템플릿 문구는 그대로(사내 운영 DB `CONTRIBUTING.md`·`docs/branch-protection.md`의 "CODEOWNERS 승인 1명 이상"은 팀 결정에 맞게 PR로 고친다). `job_status`에 `pr-merged` 단계. 스킬 문서는 `reference/write-flow.md` §6·`rules.md` 한 줄만 바뀜(SKILL.md 그대로) |
| 분석 스킬 소스 바로 적용(10/22) | 선택 키 `analyzers.<카테고리>.source`(분석 스킬 소스 checkout 안의 스킬 폴더, 절대 경로 — 개인 경로라 보통 사용자 config). 있으면 `skill_patch.py`가 patch 전문(마스킹됨)과 `스킬 소스 적용 대기: …` 줄을 더 내고, 사용자가 "적용"을 고르면 `skill_patch.py <KEY> --name <스킬> --apply --sha <H>`(`--source` 없이, 제안 때 meta에 기록한 소스에만)가 그 저장소 워킹 트리에만 `git apply`(index·커밋·push 없음 → `스킬 소스에 적용함(커밋 안 함): <경로> — 확인 후 직접 커밋·push`). git 저장소 아님·바꿀 파일에 커밋 안 한 변경·`git apply --check` 실패·설치된 플러그인 캐시(`SK`·`.claude/plugins`)·이슈 DB clone과 겹침이면 적용하지 않고 patch를 남긴다. patch가 200줄·12KB를 넘으면 제안하지 않는다. guard 규칙 12: `--apply`는 ask, `source` 안 직접 편집도 ask, patch·meta 직접 쓰기는 거부. `source`가 없으면 이전과 같다. 스킬 문서는 `reference/skill-patch.md` 4번만(SKILL.md 그대로). 이슈 DB 뼈대 `docs/analyzer-skills.md` 문구가 바뀌어 **뼈대 zip 해시가 바뀐다** |

## 3. 테스트·eval

- `python3 -m pytest -q tests`. `tests/test_show_guard.py::test_hook_replay_counts_without_content`는 사외에서도 환경에 따라 실패한다(기대 2, 실제 1). 이것만 실패하면 병합해도 되고, 실패 줄은 사외로 전달한다.
- **SKILL.md(공통 규칙)가 바뀌었다** → §8 기준으로는 사내 대상 eval 11개(`pending.json` `site`)를 모두 다시 돌릴 대상이다. **이번에는 추후로 미룬다(10/21 사용자: 토큰 여유 없음).** 돌릴 때 이 반입분이 직접 닿는 것은 Step 5-1·7 흐름이다. hook은 바뀌지 않았다.
- 사외 eval 재측정(10/21, Sonnet 5.5, n1-a~e·n2-71, $21.3, 수동 채점 94행): **pass 55 · fail 5 · none 11(site)**, 안전 위반 0. fail 5는 모두 화면 표시 누락(모델 편차, P2·기록만): 15 리포트에 Android 17·새 경로 전체 없음, 40 리포트 `심층 분석 (…)`·`분석 스킬 의견` 안 보임, 46 탐색 가설 칸(인용·반대 근거·다음 확인)·"코드 근거 없음" 안 보임, 63 oFono 변형 DB(합성·형식 가정) 명시 없음, 69 취소 전 준비물·리뷰어 목록 안 보임. 71은 안내 줄 요약 → 문구 강화(30892eb) 뒤 재실행 통과. S-2 `s2.offsite`는 이 5개를 사용자 결정으로 띄운다(사내에서 다시 돌리거나 waive).

## 4. 남은 P2 (반입 뒤 후보)

- 닫는 `}`가 없는 `DataCallResponse` 뒤의 `cid=`가 가려지지 않을 수 있다(객체 첫 `cid`까지만 제외하도록 줄였지만 완전하지 않음).
- 첫 push 예외를 `12-principles.md`·`08-safety.md`에서 `SITE_INSTALL §9`로 상호 참조.
