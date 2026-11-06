# 종합 리뷰 요청서 (Codex 등) — 구조·사용성·유지보수·도입 가치·판정/추정 스킬·런타임 호환

> 이 문서는 **리뷰어에게 줄 맥락**만 담는다. 작성자(Claude)의 자체 평가, "잘 된다"는 주장, 측정 결과 해석은 빼려고 했다. 남은 것이 있으면 그것도 발견으로 보고한다.
> 이 문서의 설명도 검증 대상이다. 코드·문서와 다르면 그 차이를 발견으로 보고한다.
> 지난 외부 리뷰(`CODEX_REVIEW_BRIEF.md`)는 이번 주 코드 변경의 결함을 봤다. 이번은 **제품·구조 전체**를 본다.

## 0. 붙여 넣을 요청문

```
레포 github.com/edgesmith-k/telephony-triage 의 main(커밋 d263cc0, 다음 사내 반입 후보)을 종합 리뷰해 줘.
맥락과 규칙은 브랜치 ccr-d022623a-2f4vdx 의 docs/development/CODEX_HOLISTIC_REVIEW_BRIEF.md 에 있다.
그 문서 §6 "편향 방지"를 먼저 지키고, §3의 축(사용자 편의성·관리자 유지보수·매니저 도입 가치와 이슈 관리/모니터링·
이슈 판정 스킬·이슈 추정 스킬·런타임 호환·구조)을 모두 다뤄 줘. 결과는 §7 형식으로.
장점과 약점을 같은 기준으로 적고, 근거가 없는 평가는 "추정"으로 표시해 줘.
('이슈 추정' = 모델이 원인 가설을 세우는 탐색·심층 분석)
```

## 1. 무엇인가 (사실만)

- **목적**: Android·oFono 텔레포니 이슈를 분석한다. Jira 이슈와 로그(logcat·bugreport, oFono syslog/journal)를 받아 원인 후보와 근거를 보이고, 사람이 확인한 원인·해결책을 별도 GitHub 레포인 **이슈 DB**에 쌓는다. 이슈 DB 구조는 카테고리 > 이슈 유형(증상) > 원인이다.
- **형태**: Claude Code 플러그인(`plugin/`)이다. 구성은 다음과 같다.
  - 커맨드 14개: `plugin/commands/*.md`
  - 스킬 1개와 참조 문서: `plugin/skills/telephony-triage/SKILL.md`, `reference/`
  - hook: `plugin/hooks/hooks.json`
  - 스크립트: `plugin/scripts/`
- **분석 흐름**(단계 번호는 `docs/design/07-workflow.md`의 Step 1~9를 따른다. 명령은 `09-commands.md`):
  - Jira를 추출하고, 로그를 파싱·마스킹하고, 이슈 DB 시그니처와 매칭한다. 드라이버는 `triage.py run`이다.
  - Step 5-1 심층 분석: 설정(`analyzers`/`deep_source`)이 있고 1위 후보의 카테고리가 일치할 때 돈다. 기본은 사용자 동의 뒤다.
  - Step 5-2 탐색 분석: 후보가 없거나 1위가 C=0일 때 돈다. 기본은 사용자 동의 뒤다.
  - 5-1·5-2 모두 `triage.py module --for deep|explore`로 모듈 문서를 쓸 수 있다.
  - 리포트를 만든 뒤, 사용자가 확인하면 기록한다: 분류 확정, 새 유형·원인, 시그니처 제안.
  - 이슈 DB에 PR을 연다(`db_pr.py`). +1 승인 뒤 병합한다.
- **이슈 판정 지점**(스크립트):
  - 파서·백엔드: `parse_logcat.py`, `platforms/`, `parser_backends/`
  - 시그니처 매칭·점수: `match_signatures.py`, `common/signatures.py`
  - 검증: `db_verify.py`, `db_regress.py`
  - 이슈 DB 검사: `db_lint.py`
- **이슈 추정 지점**(모델 + 스크립트 검사):
  - 탐색·심층 분석 지침: `SKILL.md`, `reference/explore.md`, `reference/module-skills.md`
  - 모듈 문서: 별도 레포, 템플릿은 `templates/module-skills/{ofono,android}/<모듈>/`
  - 출력 검사: `triage.py check-output`, `common/evidence.py`(근거 원문 대조)
  - 평가기: `plugin/scripts/module_eval.py`, 사례는 `templates/module-skills/**/evals/`
- **강제·검사 지점**(설계상 역할이며 검증 대상):
  - hook: `guard.py`(4,848줄, d263cc0 기준), `show_guard.py`, `jira_bridge.py`
  - 마스킹: `common/masking.py`, `mask_pii.py`
  - 경계 검사: `tools/check_boundary.py`
- **운영·관측 도구**:
  - 이슈 DB 생성물: README·STATS·CHANGELOG(`db_build.py`)
  - 파일럿 지표: `usage_stats.py`
  - 작업 상태: `job_status.py`
  - 정기 점검과 시그니처 drift: `tools/site_audit.py`(`site_step.py audit`)
  - 사내 설정 단계: `tools/site_step.py`, `tools/site_checks.py`
- **실행 환경 셋**(`docs/RUNTIME_ADOPTION.md`, `docs/development/RUNTIMES.md`):
  1. Claude Code + Claude
  2. Claude Code + 사내 모델: 게이트웨이로 모델만 바꾼다.
  3. OpenCode + 사내 모델: v1은 분석 전용이다. 구성은 다음과 같다.
     - 층: `opencode/`
     - guard 연결: `common/oc_adapter.py`, `opencode/plugins/tt-guard.js`
     - Jira 읽기 관문: `common/oc_jira_gate.py`
- **개발·배포 방식**(`docs/design/15-local-draft.md`, `GUIDE.md` §3~4):
  - 사외 PC에서 초안을 만들고, 반입 묶음(`tools/make_bundle.py`)을 사내로 옮기고, 사내에서 보완한다.
  - 사내 확인값은 레포 밖(`SITE_PROFILE.md`·`SITE_PATHS`)에 둔다. 확인할 항목은 `docs/design/14-site.md`의 S1~S36이다.
  - 문서의 태그·로그 문구·서버 이름은 placeholder다.
- **지원 트래커**: Jira가 기본이고, 설정으로 GitHub Issues도 쓴다(`docs/design/18-trackers.md`). 플랫폼은 Android가 기본이고, 켜면 oFono를 쓴다(`17-platforms.md`).

## 2. 사람과 역할 (리뷰 관점)

| 역할 | 하는 일 | 주로 보는 문서·명령 |
|---|---|---|
| 엔지니어(사용자) | 설치, 설정, 이슈 분석, 결과 확인, 기록 승인 | `README.md`, `docs/TEAM_GUIDE.md`, `GUIDE.md` §5~6, `/telephony-triage:setup`·`analyze`·`help` |
| 관리자(이슈 DB 메인테이너·플러그인 관리자·반입 담당) | 이슈 DB 리뷰·병합, 시그니처·파서 규칙 관리, 사내 반입·설정, 모듈 스킬 레포 관리 | `GUIDE.md` §4, `docs/SITE_INSTALL.md`, `docs/design/03-issue-db.md`·`06-collaboration.md`·`14-site.md`, `tools/site_step.py` |
| 매니저(도입 결정) | 도입 여부, 파일럿 범위, 효과 측정, 위험 판단 | `README.md`, `docs/RUNTIME_ADOPTION.md`, `docs/design/01-architecture.md`, `05-verification.md`, `10-skill-eval.md` |

위 문서들도 평가 대상 산출물이다. 그 안의 효과·안전 주장은 사실 근거로 쓰지 않는다.

## 3. 리뷰 축과 질문

질문은 방향을 정해 두지 않은 열린 질문이다. 답이 "괜찮다"여도 근거를 적는다.

**A. 사용자 편의성**
- 설치부터 첫 분석 결과까지의 단계 수, 입력해야 하는 것, 걸리는 시간(추정)은?
- 분석 중 사용자에게 묻는 확인·질문은 몇 번, 언제 나오는가? 각 질문이 무엇을 막는가? 빼면 무엇이 달라지고, 더 필요한 확인은 없는가?
- 실패·막힘(설정 누락, 인증 실패, 로그 형식 미지원, 후보 없음)에서 사용자가 다음에 할 일을 알 수 있는가? 오류 문구가 이해되는가?
- 리포트가 엔지니어가 판단하기에 충분하고 읽기 쉬운가? 근거·불확실성 표시가 적절한가?
- 커맨드 14개와 옵션의 학습 비용은? 처음 쓰는 사람이 반드시 알아야 하는 최소 집합은?
- 새 팀원 온보딩 경로(문서·교육 자료, 한국어 전용)와, 작성자가 없을 때 지원은 누가 맡는가?

**B. 관리자의 장기 유지보수**
- 코드·문서·시험의 크기와 복잡도가 1인(또는 소수) 관리자에게 감당할 만한가? 가장 큰 유지비가 드는 곳은 어디인가(코드·문서·시험 크기와 변경 빈도로 근거를 든다)?
- 시그니처·파서 규칙·태그를 추가하거나 바꾸는 절차가 명확하고 안전한가? 잘못 넣었을 때 어떻게 드러나는가?
- 이슈 DB 스키마 변경(`db_migrate.py`), 생성물, 브랜치 보호, +1 병합 같은 운영 절차의 반복 비용은?
- 사외/사내 분리와 반입 주기가 유지보수를 돕는가, 비용을 늘리는가? 사내 확인값(S1~S36)이 늘어나는 구조인가?
- 사외→사내 반입(`tools/make_bundle.py`, 재반입, 오프라인 설치 `docs/SITE_INSTALL.md`)·롤백·제거 절차의 반복 비용과, 실패했을 때 복구는?
- 시험(3,900개 수집, 파라미터 포함·함수 2,707개)이 실제로 회귀를 잡는가, 유지 부담이 되는가? 깨지기 쉬운 시험(문구·바이트 상한 고정 등)의 비율은?
- 의존성·Python 3.10~3.14 지원·외부 도구(git·gh·Claude Code·OpenCode 버전) 변화에 얼마나 민감한가?
- 버스 팩터: 작성자 없이 다른 사람이 이어받을 수 있는가? 문서의 진입점(`CLAUDE.md`, `docs/design/README.md`)으로 충분한가?

**C. 매니저 관점: 도입 가치, 이슈 관리, 모니터링**
- 이 도구가 푸는 문제는 무엇이고, 효과(분석 시간, 정확도, 지식 축적)를 어떻게 측정할 수 있나? 지금 있는 측정 장치(`tools/offline_eval.py`, `usage_stats.py`, eval)가 그 효과를 재는가?
- 이슈 관리: 이슈 DB에 쌓인 원인·해결책이 다음 분석에 실제로 재사용되는 경로가 있는가? 중복·오분류·낡은 시그니처를 어떻게 관리하나?
- 모니터링: 매니저나 관리자가 "누가 얼마나 쓰고, 무엇이 맞고 틀렸고, 무엇이 막혔는지"를 볼 수 있는가(STATS·usage_stats·audit·job_status)? 빠진 지표는?
- 실패·막힘이 관리자에게 알림으로 가는가, 사람이 찾아봐야만 보이는가? 오분류가 병합된 뒤 발견하고 되돌리는 경로는?
- 비용 모델: 토큰·사람 시간·사내 모델(GPU) 비용을 어떻게 추정하고 기록하나(`usage_stats`, 사내 모델은 비용 미상·토큰만 — `docs/RUNTIME_ADOPTION.md`)? 빠진 비용 항목은?
- 비용(토큰·사람 시간)과 위험(개인정보, 잘못된 분류가 퍼지는 것, 사내 모델 품질)은? 파일럿을 어떻게 설계해야 판단할 수 있나?
- 더 단순한 대안(Jira 검색 + 위키, grep 스크립트 모음, 범용 AI 도구만 쓰기)과 비교해 이 구조의 추가 가치와 추가 비용은?

**D. 이슈 판정 스킬 (스크립트 매칭·분류)**
- 시그니처 모델(유형·원인, 매칭 점수, 부분 일치)이 텔레포니 이슈를 표현하기에 적절한가? 표현하지 못하는 이슈 부류는?
- "판정은 스크립트, LLM은 보조"(`docs/design/12-principles.md`) 원칙 자체가 이 문제에 맞는가? 그리고 코드와 스킬 지침에서 지켜지는가? 모델이 판정을 바꿀 수 있는 경로는?
- 오판·누락이 일어났을 때 사용자에게 무엇이 보이는가? 오판이 이슈 DB에 쌓이는 경로와 막는 장치는?
- 시그니처 품질 관리(`db_lint`, `db_regress`, `site_audit` drift)가 충분한가?

**E. 이슈 추정 스킬 (탐색·심층 분석, 모듈 문서)**
- `SKILL.md`·`reference/explore.md`·모듈 문서가 모델에게 주는 지침이 명확하고 일관되며, 텔레포니 관점에서 맞는가? 모델을 잘못된 결론으로 이끌 문장은?
- 출력 형식(후보 1~3개와 가장 유력)과 근거 원문 검사가 잘못된 추정을 걸러내는가? 사용자에게 불확실성이 정직하게 보이는가?
- 평가 사례(합성·마스킹 발췌, `templates/module-skills/**/evals/`, `tests/skill_evals/evals.json`)와 채점 방식(인정 후보·함정, 스크립트 채점)이 실제 사용 가치를 재는가? 사례의 대표성과 수는 충분한가? 채점이 너무 너그럽거나 엄한 곳은?
- 토큰 사용량을 줄이는 장치(모듈 보기, 바이트 상한)가 정확도에 영향을 주는가? 주지 않는다면 그 근거는?
- 평가 규모: `tests/skill_evals/evals.json` 79개, `templates/module-skills/**/evals/` 아래 파일 210개.

**F. 런타임 호환 (Claude Code + Claude / Claude Code + 사내 모델 / OpenCode + 사내 모델)**
- 각 런타임에서 hook·guard, 스킬 선택, MCP(Jira·GitHub), 출력 관문, 기록·병합 흐름이 어떻게 달라지는가? 동작·제한·미확인으로 나눠 표로 만들어 주세요.
- "안전은 스크립트가 지킨다"는 설계가 약한 모델(형식 위반, 지시 무시, 긴 문맥 한계)에서도 성립하는가? 무너지는 지점은?
- Claude Code + 사내 모델(게이트웨이)에서 스킬 선택·tool-use 형식·hook 동작이 Claude와 같다는 가정의 근거는? `docs/development/RUNTIMES.md`와 `site_step.py runtime-check claude-gateway`가 실제로 무엇을 재는가?
- OpenCode v1의 제약(분석 전용, bash 허용 목록, Jira 읽기 관문)이 사용자 경험과 안전 사이에서 적절한가? OpenCode·Claude Code 버전이 바뀔 때 깨질 곳은(예: `OPENCODE_VERSION` 고정 표)?
- 사내 확인 도구(`site_step.py runtime-check`)가 확인하는 것과 확인하지 못하는 것은? 사외에서 확인할 수 없는 가정은 무엇이고, 그 가정이 틀리면 어떻게 되나?

**G. 안전·개인정보 (넓게만)**
- 지난 리뷰가 코드 결함을 봤다. 이번에는 구조 차원에서 본다: 강제 지점이 여러 곳(파일 도구·Bash·MCP·개별 CLI)에 흩어진 것이 장기적으로 위험한가? 마스킹을 한 곳에서 보장하는가?
- 데이터 보존: JOB 디렉토리, 마스킹 전 원본 로그, `usage_stats --transcripts`, 이슈 DB 기록의 보존 기간·삭제·접근 권한이 정의돼 있나?

**H. 구조 전반**
- 과설계나 부족한 설계가 있는가? 지울 수 있는 층이나 합칠 수 있는 모듈은?
- 문서(`docs/design/`의 번호 문서 18개와 `99-deferred.md`·`contracts.md`·`contracts-cli.md`)와 코드가 맞는가? 계약 생성물(`tools/gen_contracts.py`)이 실제로 drift를 막는가?
- 확장(새 플랫폼·트래커·모듈·런타임)이 설계대로 쉬운가? 확장 하나를 가정해 필요한 변경 지점을 세어 주세요.

## 4. 직접 돌려 볼 수 있는 것 (유료 모델·외부 서비스 없음)

```
pip install '.[test]'
python3 -m pytest -q                                   # 전체(3,900개 수집, 실행 시간은 작성자 추정 30~40분)
python3 tests/helpers/make_plugin_root.py --out /tmp/proot
python3 tools/offline_eval.py tests/fixtures/offline-eval-sample.yaml --plugin-root /tmp/proot   # 합성 라벨셋 매칭 정확도 표
python3 plugin/scripts/module_eval.py --module ofono/data --dry-run      # 모듈 평가 실행 계획(비용 없음)
python3 tests/skill_evals/run.py --iteration /tmp/it --eval 3 --prepare-only   # 스킬 eval 입력 준비(모델 호출 없음)
python3 tools/check_boundary.py ; python3 tools/gen_contracts.py --check
python3 tools/site_step.py --help ; python3 plugin/scripts/usage_stats.py --help
```

- 이슈 DB 예시는 `tests/fixtures/issue-db-sample/`, 합성 로그는 `tests/fixtures/logs/`, 모의 Jira는 `tests/skill_evals/jira/`에 있다.
- 실제 Claude·사내 모델·Jira·GHE 호출은 사외에서 확인할 수 없다. 그 부분은 코드·문서로 판단하고, 판단했다면 "미실행"으로 표시한다.

## 5. 전제·제약 (사실)

- 개발자는 1명이다. 사외에서 초안을 만들고 주기적으로 반입한다. 사내 값(실제 태그·로그 문구·서버·모델 이름)은 레포에 없다.
- 실행 환경은 Ubuntu다. 사내 git은 2.34일 수 있다(사이트 리허설 CI 기준). Python은 3.10 이상이다.
- 사내 모델의 이름·한도·품질은 사외에서 알 수 없다. 문서의 한도 값은 가정이다.
- 레포에 있는 로그는 합성이거나 마스킹된 발췌라야 한다.

## 6. 편향 방지 (먼저 지켜 주세요)

- **아래 파일은 독립 평가를 마친 뒤에만 읽는다.** 작성자의 주장, 측정 해석, 소개·홍보 문구, 지난 리뷰 결과가 들어 있다. 읽은 뒤에는 중복 표시에만 쓰고, 그 주장으로 평가를 바꾸지 않는다.
  - `docs/development/` 중 `MODULE_SKILLS_RESULT.md`, `CONCERNS.md`, `BUNDLE_REVIEW_GUIDE.md`, `*_RESULT.md`, `*REVIEW*.md`(예외: 이 문서, `CODEX_REVIEW_BRIEF.md`는 범위 구분에만 쓴다), `REIMPORT_NOTES_*.md`, `H_OFFSITE_REMEASURE.md`, `TEAM_PLUGIN_REVIEW_VERDICT_*.md`, `IMPROVEMENT_PLAN_*.md`, `*HANDOFF*.md`, `k-repro/`
  - 루트 `REVIEW-OPEN.md`, `docs/tasks.md`
  - `docs/history/` 전체(과거 기록, 읽지 않는다)
  - `docs/materials/*.html`, `docs/book/`(소개·교육 자료)
  - `DRAFT_NOTES.md`의 진행 상태, 커밋 메시지
  - `tests/skill_evals/offsite_results.json`, `module_offsite_results.json`(측정 기록은 형식만 보고, 수치로 결론 내지 않는다)
- 계획·결정 문서(`MODULE_SKILLS_PLAN*.md`, `MODULE_SKILLS_DECISIONS.md`)는 의도를 알기 위해 읽어도 되지만, 그 안의 "근거" 문장은 작성자 판단이다.
- 설계 문서의 "이유·근거" 문장도 작성자 판단이다. 요구사항(`CLAUDE.md`, `12-principles.md`, `08-safety.md`, `contracts.md`)은 기준으로 쓰되, 요구사항 자체가 적절한지도 평가 대상이다.
- 시험이 많다는 것, 통과한다는 것만으로 가치나 정확성을 인정하지 않는다.
- 장점과 약점을 같은 엄격함으로 적는다. 약점마다 "어떤 증거가 있으면 평가가 바뀌는지"를 한 줄 적는다.
- 작성자가 이미 알고 있다고 적어 둔 문제도 근거가 있으면 다시 보고한다.

## 7. 결과 형식

1. **매니저용 한 장 요약** (먼저):
   - 권고: 도입 / 조건부 파일럿 / 보류 / 도입하지 않음(더 단순한 대안 권고) 중 하나와 그 조건
   - 기대 효과, 측정 지표, 주요 위험 3개
2. **축별 평가**(A~H): 각 축마다 다음을 적는다.
   - 점수 1~5와 기준
   - 강점 최대 3개, 약점 최대 3개(각각 근거 path:line 또는 실행 결과)
   - 가장 큰 위험 1개
   - 효과 대비 비용이 큰 개선 제안 1~3개
3. **런타임 호환 표**: 행은 기능(hook·guard, 스킬 선택, Jira MCP, 출력 관문, 기록·병합, 모듈 스킬, 비용 기록), 열은 런타임 셋, 칸은 동작·제한·미확인과 근거다.
4. **유지보수 위험 Top 5**와 **사용성 마찰 Top 5**: 각각 위치와 개선안.
5. **발견 목록**(결함·불일치):
   ```
   [P0|P1|P2|Q] 제목
   - 위치: path:line
   - 주장 / 근거(재현 또는 경로 추적, 못 했으면 "추정") / 영향 / 제안
   ```
   - P0은 안전 위반, P1은 기능 결함·잘못된 판정·측정·요구사항 미충족, P2는 그 밖, Q는 의도 질문이다.
6. **본 범위·못 본 범위**: 읽은 곳, 돌린 것, 실행하지 못한 것과 이유.
