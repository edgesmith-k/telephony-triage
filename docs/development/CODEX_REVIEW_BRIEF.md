# 외부 리뷰 요청서 (Codex 등) — 이번 주 변경 + 전체

> 이 문서는 **리뷰어에게 줄 맥락**만 담는다. 작성자(Claude)의 자체 평가·테스트 결과·"고쳤다"는 주장은 일부러 넣지 않았다.
> 리뷰어는 이 문서의 설명도 검증 대상으로 본다.

## 0. 붙여 넣을 요청문

```
레포 github.com/edgesmith-k/telephony-triage 의 브랜치 ccr-d022623a-2f4vdx 를 리뷰해 줘.
맥락과 규칙은 docs/development/CODEX_REVIEW_BRIEF.md 에 있다. 그 문서의 §6 "편향 방지"를 먼저 지켜 줘.
범위: (A) 이번 주 변경 77e2827..HEAD 를 깊게, (B) 프로젝트 전체를 넓게.
결과는 §7 형식으로, 심각도 순서로. 추측은 추측이라고 표시하고, 재현한 것은 재현 방법을 적어 줘.
```

## 1. 프로젝트

- Android·oFono 텔레포니 이슈 분석 도구다. Claude Code 플러그인(`plugin/`)과 OpenCode용 설정(`opencode/`)이 있다.
- Jira 이슈와 로그(logcat, oFono syslog/journal)를 파싱한다(`plugin/scripts/parse_logcat.py`, `platforms/`). 이슈 DB(별도 GitHub 레포, 예시는 `tests/fixtures/issue-db-sample/`)의 시그니처와 매칭해(`match_signatures.py`, `common/signatures.py`) 원인 후보를 낸다.
- 후보가 없으면 모델이 탐색 분석을 한다. 그 결과는 사용자 확인을 거쳐 PR로 이슈 DB에 기록한다(`db_pr.py`, `dbpr/`).
- 안전장치:
  - hook: `plugin/hooks/hooks.json`, `guard.py`, `show_guard.py`, `jira_bridge.py`
  - 마스킹: `common/masking.py`, `mask_pii.py`
  - 이슈 DB 병합 관문(+1 승인)
- 모듈 스킬: 모듈(data·sim·network·call·sms·ims·modem)별 분석 문서를 담는 별도 레포가 있다. 그 템플릿이 `templates/module-skills/`에 있고, 평가기는 `plugin/scripts/module_eval.py`다.
- 사내 단계 도구는 `tools/site_step.py`, `tools/site_audit.py`다. 사내 환경 값은 레포에 없다. 문서의 태그·로그 문구·서버 이름은 placeholder다.
- 설계 문서는 `docs/design/`에 있다(지도는 `README.md`, 표와 정의는 `contracts.md`).

## 2. 범위

- **(A) 이번 주 변경 (깊게):** `77e2827`(2026-11-03, 직전 반입 묶음 main)부터 브랜치 HEAD까지. 커밋 약 140개, 파일 약 600개, +5.5만 줄이다. 대부분은 템플릿, 사례, fixture, 시험이다.
  - 보는 법: `git log --oneline 77e2827..HEAD`, `git diff --stat 77e2827..HEAD`
- **(B) 전체 (넓게):** 구조, 안전 경계, 문서와 코드의 일치, 시험이 실제로 무엇을 보장하는지.
- **범위 밖:** `docs/history/`(과거 기록), 사내 전용 값.

## 3. 실행 환경

```
pip install '.[test]'                 # 고정 버전
python3 -m pytest -q                  # 전체(4코어 기준 30~35분)
python3 tools/related_tests.py --base 77e2827 --run   # 변경 관련만
python3 tools/check_boundary.py       # 사외/사내 경계 검사
python3 tools/gen_contracts.py --check
python3 tests/helpers/make_module_eval_inputs.py --check   # 생성물 drift
```

- gh가 필요한 시험은 레포 안의 mock(`tests/mocks/bin`)을 쓴다. 실제 GitHub·Jira·유료 모델 호출은 필요 없다.
- `module_eval.py`는 `--dry-run`으로 비용 없이 실행 계획을 볼 수 있다.
- 사내 로그는 사외에서 본 적이 없고 레포에도 없다. 레포에 있는 로그는 모두 합성 로그와 placeholder라야 한다(§4).

## 4. 요구사항 — 위반 여부를 확인할 대상

출처는 `CLAUDE.md`, `docs/design/12-principles.md`, `docs/design/08-safety.md`, `docs/design/contracts.md`다.

1. 분류 확정, 새 유형·원인, 시그니처·파서 규칙 추가·삭제, 수정 상태 변경은 **사용자 확인 뒤에만** 한다. 코드가 이것을 자동으로 쓰는 경로가 있으면 안 된다.
2. 이슈 DB push는 변경, diff, 검증 결과, 커밋 메시지를 보여 주고 승인받은 뒤에만 한다. main 직접 push는 금지다. 병합은 +1 승인 뒤 요청할 때 `db_pr merge`로만 한다. 도구가 스스로 Approve하지 않는다.
3. 사용자의 이슈 DB clone은 브랜치도 파일도 바꾸지 않는다(작업은 별도 worktree에서).
4. 시험, 매칭, 이슈 DB에는 **마스킹된 로그만** 쓴다(IMSI·ICCID·MSISDN·IP·자격증명 등). Jira는 읽기와, 확인 화면에서 승인한 본문의 코멘트 추가만 한다(본문이 바뀌면 재승인).
5. 생성 파일(README·STATS·CHANGELOG)은 `db_build.py`로만 만든다.
6. 판정 기준은 스크립트 출력이다. LLM 결과는 리포트 보조다. 건너뛴 검증을 통과로 표시하지 않는다.
7. git 충돌, 인증 실패, MCP 부재, 버전 불일치는 우회하지 않고 보고한다.
8. 사내 값과 코드는 레포에 넣지 않는다(`check_boundary.py`가 지킨다고 되어 있다).
9. hook(guard)은 위 규칙의 실제 강제 지점이다. Bash·파일 도구·MCP를 통한 우회 경로가 없어야 한다. 실패하면 막는 쪽으로 닫혀야 한다.

## 5. 이번 주 변경 영역 지도

각 영역의 의도된 동작과 주요 경로만 적었다. 의도는 `docs/development/MODULE_SKILLS_PLAN.md`(계획)와 `docs/development/MODULE_SKILLS_DECISIONS.md`(사용자 결정)에 있다.

| 영역 | 의도된 동작 | 주요 경로 |
|---|---|---|
| +1 병합 관문·확인 화면 | 이슈 DB PR 병합은 승인 1개 이상 뒤에만, 바로 병합 경로 삭제 | `plugin/scripts/db_pr.py`, `dbpr/`, `db_summary.py`, `guard.py` |
| guard 규칙 보강 | 원격 쓰기·관리 clone 변경 우회 차단 | `plugin/scripts/guard.py`, `common/` |
| 모듈 스킬 받기·흐름 | 모듈 문서 레포를 관리 clone으로 받고, 분석 5-1(심층)·5-2(탐색)에서 동의 뒤 사용. 출력은 관문(`check-output`)을 거침 | `triagelib/modulecmd.py`, `common/modulefilter.py`, `common/skillcheck.py`, `plugin/skills/telephony-triage/SKILL.md` |
| 모듈 문서·평가 사례 | oFono·Android 7모듈씩: 문서, 증상별 첫 점검 표, 대체 근거, 데몬 역할 표. 사례 42개 | `templates/module-skills/**`, `tests/test_module_templates*.py` |
| 모듈 평가기 | 문서 있음/없음 두 arm 비교. 탐색 사례는 후보 1~3개 형식, 인정 후보·함정으로 채점 | `plugin/scripts/module_eval.py`, `tools/module_answers.py` |
| 파서·태그 속성 | oFono·Android 파서 보강, 데몬 이름을 이슈 DB `tags.yaml` 속성(`level`·`ipc`)으로 지정 가능(oFono는 0.0.5부터 지정·구성요소 설정이 없으면 판별 없음) | `platforms/ofono/`, `platforms/android/`, `parser_backends/`, `tests/fixtures/issue-db-sample/parser-rules/` |
| 마스킹 | IPv6 경계(C++ 범위 이름 제외), 여러 줄 문맥 규칙, oFono 덤프 조각에 갈린 IMSI/ICCID | `common/masking.py`, `common/dumpjoin.py`, `mask_pii.py`, `tools/fixture_residual.py` |
| 부분 일치·코드 대조 | 후보가 없을 때 부분 일치를 보이고, 시그니처 추가는 제안만. code root가 있으면 없는 줄 문구를 grep(path:line만 출력) | `common/signatures.py`, `match_signatures.py`, `code_roots.py`(find-text), `triagelib/report.py` |
| 이슈 DB 작성 지침·lint | 근거 줄 하나에 기대지 않기 지침, `db_lint --advice`(참고만, 종료 코드 영향 없음) | `docs/design/03-issue-db.md`, `plugin/scripts/db_lint.py` |
| 사내 단계 도구 | 모듈 점검·커버리지, 정기 점검(토큰 상한), 시그니처 소실(drift) 감지, OpenCode 사내 확인 | `tools/site_step.py`, `tools/site_audit.py`, `tools/module_coverage.py` |
| OpenCode 지원 | guard를 OpenCode 도구 호출에 연결, bash 허용 목록, Jira 읽기 관문(사내 확인 뒤 설정), 오류 본문 숨김 | `opencode/`, `plugin/scripts/common/oc_adapter.py`, `tools/gen_opencode.py` |
| 문서 | 도입 가이드, 팀원 가이드, 반입 노트 | `docs/RUNTIME_ADOPTION.md`, `docs/TEAM_GUIDE.md`, `docs/SITE_INSTALL.md` |

## 6. 편향 방지 (먼저 지켜 주세요)

- **작성자 자체 평가 파일은 독립 리뷰를 마친 뒤에만 읽는다.** 아래 파일에는 "통과했다", "고쳤다", "P2로 미뤘다" 같은 작성자 주장이 있다.
  - `docs/development/MODULE_SKILLS_RESULT.md`
  - `docs/development/CONCERNS.md`
  - `docs/development/BUNDLE_REVIEW_GUIDE.md`
  - `DRAFT_NOTES.md`의 진행 상태
  - 커밋 메시지의 "리뷰 P1 수정" 같은 표현

  이 주장들로 지적을 지우지 않는다. 읽은 뒤에는 중복 표시에만 쓰고, 이미 적혀 있어도 근거가 있으면 다시 보고한다.
- 요구사항(§4)과 의도(계획·결정 문서)는 기준으로 쓴다. 결정 문서의 "근거" 문장은 작성자 판단이므로 그대로 믿지 않는다.
- 시험이 통과한다는 사실만으로 동작이 맞다고 보지 않는다. **실패할 수 없는 시험, 같은 코드로 기대값을 만든 시험, mock이 실제와 다른 시험**을 찾아 주세요.
- 문서와 코드가 다르면 어느 쪽이 맞는지 판단하지 말고 차이를 보고한다.

## 7. 결과 형식

```
[P0|P1|P2|Q] 제목
- 위치: path:line (여러 곳이면 모두)
- 주장: 무엇이 잘못됐나 (한두 문장)
- 근거: 재현 명령·입력·출력, 또는 코드 경로 추적. 재현 못 했으면 "미재현(추정)"
- 영향: 어떤 사용자·데이터가 어떻게 잘못되나
- 제안: 최소 수정
```

- **P0:** 안전 위반이다. 마스킹되지 않은 식별자가 시험·DB·출력에 남는 경우, 사용자 확인 없는 DB·규칙 쓰기·push·병합, guard 우회, 사내 값 유출이 해당한다.
- **P1:** 기능 결함, 잘못된 판정·측정, 요구사항 미충족, 크래시가 해당한다.
- **P2:** 그 밖의 정확성·유지보수 문제다(문체 지적은 빼거나 맨 뒤에 묶는다).
- **Q:** 의도를 확인해야 하는 질문이다.
- 맨 끝에 다음을 적어 주세요.
  - 본 범위: 읽은 디렉토리, 돌린 시험
  - 못 본 범위
  - 전체 구조에 대한 의견: 3~5줄
