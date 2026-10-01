# DRAFT_NOTES — 사외 초안 상태 파일

> **작게 유지한다(≤8KB).** 사외 초안 모드의 진행 상태·활성 트랙·막힌 것만 둔다 (`docs/design/15-local-draft.md §15.1`).
> Phase별 산출물 표·완료 기준 결과·가정·TODO 목록 같은 **상세 이력은 `docs/history/draft-notes-2026-09.md`** 에 있고, 필요한 절만 찾아 읽는다.
> 이 파일은 반입 때 사내로 같이 간다. `.local-draft`는 가지 않는다. 모드 판별 규칙은 `CLAUDE.md` 머리말.

## 진행 상태

- 모드: **사외 초안** (`.local-draft` 있음)
- 완료 Phase: **D0, 1~12** (2026-09-28~29, Phase 7부터 Phase마다 사용자 확인). 상세: 이력 파일의 "Phase N" 절
- 진행 중 Phase: **13** (SKILL.md·reference·eval 45개). 정의·환경 준비 완료, **행동 평가 미실행**
- 기준 문서 세트: `telephony-triage-docs-v11` (변경 이력 `docs/history/CHANGES.md`)
- 마지막 전체 테스트: `pytest tests` 통과 (2026-10-01, 이 컨테이너 Ubuntu 기준 226개·779s — `ARCHITECTURE_REVIEW` B.3)

## 막힌 것

- Claude Code 주간 한도(HTTP 429)로 Phase 13 행동 평가·트리거 시험·빈 플러그인 실험(S1) 미실행. **Phase 13 재개일: 2026-10-11**(사용자 결정). 그 전까지는 eval 배치 실행(`run.py --execute`)을 하지 않고 코드 작업(RF-0, RF-1)만 한다. 작업 세션 자체도 같은 사용량을 쓰므로, 코드 전용인 RF-0은 다른 에이전트(Codex 등)에 맡겨도 된다.

## 활성 트랙과 순서 (2026-10-01 결정)

반입 전 순서: **RF-0 → RF-1 → (10/11) Phase 13 → RF-2 → 반입.** RF-1이 `SKILL.md`를 다시 쓰므로 Phase 13 행동 평가는 RF-1 **뒤**에 한 번만 돌린다. 10/11까지 RF-1이 끝나지 않으면: Phase 13을 현재 SKILL로 돌리고 RF-1 뒤 바뀐 eval만 다시 돌리거나(토큰 2회), Phase 13을 RF-1 완료까지 미룬다 — **그날 사용자에게 묻는다.**

| 순서 | 작업 | 근거 문서 | 상태 / 다음 할 일 |
|---|---|---|---|
| ✅ | **리뷰** — RF 계획 외부 리뷰 | 리뷰 문서 머리 "외부 리뷰 결과" | 완료(2026-10-01). 반영 내역은 RF-0·RF-1·RF-2 행에 들어감 |
| 1 | **RF-0** R1~R11 안전·정확성·의존성 + 재현 테스트·session 루트 | HANDOFF R1~R6·I0~I2, 리뷰 §U RF-0·머리 "외부 리뷰 결과" R7~R11 | 결함별 fail→pass·커밋 완료. 전체 테스트 확인 중 (`rf0/2026-10-01`) |
| 2 | **RF-1** `triage.py` driver + `SKILL.md` ≤8KB + 커맨드 보일러플레이트 + 외부 리뷰분(MCP 원문을 모델이 보지 않게, `--top`을 types/causes에도, `db_search --limit 3`, `code_refs` projection, Jira 코멘트 예산). `CLAUDE.md` ≤4KB는 §12 이동이 사용자 결정이라 보류 | 리뷰 §U RF-1·§V 1·2 | RF-0 뒤. **10/11 전 완료 목표.** `tools/offline_eval.py`가 driver를 쓰고 결과 동일 확인 |
| 3 | **Phase 13 재개 (2026-10-11)** — 행동 평가 45개(batch 1 재실행 + 남은 25개 B·C·D) + 수동 채점, 트리거 테스트, 빈 플러그인 실험(S1) | `11-phases.md` Phase 13, `tests/skill_evals/README.md`, 이력 파일 "Phase 13 재개 결과·남은 일" | Claude Code에서만. 새 iteration 경로로 실행(기존 폴더 덮어쓰기 금지) |
| 4 | **RF-2** 반입 도구 강화(staging·rollback) + `check_boundary.py` + 사외 CI. `export_external.py`는 만들지 않음(결정 a) | 리뷰 §U RF-2 | Phase 13 뒤 |
| 5 | **반입** — `15 §15.4` 체크리스트, `make_db_skeleton.py`, `git archive` 묶음 | `GUIDE.md` §3 "반입 전", §4 | 그 뒤 사내 S-1~S-7 |
| — | RF-3~RF-9, HANDOFF I3~I6(RF에 흡수) | 리뷰 §U | 반입 뒤 |

- 시작 전 **기존 remote/main을 fetch**, 끝나면 표 갱신. 이번 remote는 `telephony`(origin 신설 금지).
- 사내 로그가 모의와 다를 때 가장 먼저: [S0_PROBE_CHECKLIST.md](docs/development/S0_PROBE_CHECKLIST.md) + `tools/s0_stats.py` (사내 PC, Claude 없이).
- 사내 확인 항목(TODO(SITE) 57곳)은 `python3 tools/list_site_todos.py`로 뽑는다. 사내 정보가 있어야 판단할 것은 `REVIEW-OPEN.md`.

## 결정 (2026-10-01)

- (a) **사내→사외 반출은 사용자가 직접 타이핑하는 사내 정보 없는 문장뿐.** 도구는 반출물(파일·마스킹 로그·diff·요약)을 만들지 않는다. 사외는 합성 데이터로만 재현한다.
- (b) 자동 게시(RF-8)는 `confidence`가 아니라 별도 품질 게이트로만 채택.
- 외부 리뷰(다른 에이전트, ZIP 기준) 대조 결과와 반영 내역: 리뷰 문서 머리 "외부 리뷰 결과" 절.

### RF-0 구현에서 정한 세부

- `lock.owner`를 `TT_LOCK_OWNER`로 전달한다. OS guard 안에서 lease 원자 교체; 손상은 오류.
- 분석 S/C는 슬롯 호환·큰 쪽 window로 결합; 회귀 C는 독립. 회전 파일은 디렉터리·이름·buffer로 묶고 시간·부팅·pid 경계에서 분리.
- 파서 실패는 `complete=false`·검증 unknown. 반입은 apply 예외 rollback; crash 복구 staging은 RF-2.
- 별도 lock 대신 `pyproject.toml`에 직접·전이 의존성 고정(신규 파일 제한). 설치: `pip install .` / `pip install '.[test]'`.

## 문서 정리 상태 (2026-10-01)

- 완료: `REVIEW-10/11.md`·`CHANGES.md` → `docs/history/`, `EXTENSION_IDEAS.md` → 리뷰 문서 §X, 이 파일 축소(본문 → `docs/history/draft-notes-2026-09.md`).
- 남음(RF-1): `CLAUDE.md` ≤4KB(원칙 §12를 설계 문서로 옮겨야 가능 — 사용자 결정), 리뷰 끝난 뒤 리뷰 문서를 계획(§U·V·X)만 남기기, HANDOFF는 I0~I6 완료 후 삭제.

## 사외 Claude Code 실험 결과 (S1 예비)

`tests/mocks/plugin-probe/`로 확인한다. 절차는 그 디렉토리의 `README.md`.
**사내 버전은 다를 수 있으므로 S-2에서 다시 확인한다.**

| # | 항목 | 사외 결과 | 비고 |
|---|---|---|---|
| 1 | 플러그인 로컬 로드 | ⏳ 미확인 | 새 세션에서 `/plugin`으로 `tests/mocks/plugin-probe` 등록 후 `/probe:ping` |
| 2 | 커맨드 ↔ 스킬 관계 | ⏳ 미확인 | 같은 실험 |
| 3 | `${CLAUDE_PLUGIN_ROOT}` 치환 | ⏳ 미확인 | 치환 안 되면 config `plugin.scripts_path`를 읽는 방식으로 바꿔야 한다 (`01-architecture.md §3`) |
| 4 | hooks (SessionStart / PreToolUse) | ⏳ 미확인 | `probe-hook.log`에 남는지 |
| 5 | MCP 도구 이름 형식 | ⏳ 미확인 (예상 `mcp__<server>__<tool>`) | `probe_hook.py`가 `tool_name`을 그대로 기록한다. `guard.py`(Phase 8)가 이 형식에 의존한다 |
| 6 | hook matcher `mcp__.*` | ⏳ 미확인 | 같은 실험 |
| 7 | 권한 결정 필드(`allow`/`deny`/`ask`) | ⏳ 미확인 | `probe_hook.py --decide` |
| 8 | `@SITE_PROFILE.md` import (파일 없음) | ⏳ 미확인 | `CLAUDE.md` 첫 줄. **사외에서는 경고가 나도 동작에 문제가 없다** — 모드 판별은 `.local-draft`가 한다 (`CLAUDE.md` 머리말 규칙 3) |
| — | `--mcp-config tests/mocks/mcp.json` 로 모의 MCP 붙이는 법 | ⏳ 미확인 | 사외 Claude Code 버전에서 확인해서 여기 적는다 |

> **왜 아직 미확인인가**: 플러그인 로드·hook·`@import`는 **세션이 시작될 때**
> 결정되므로, D0를 진행한 이 세션에서는 관찰할 수 없다. 새 세션을 열어
> 위 절차를 돌리고 이 표를 채운다. 스크립트 자체(`probe.py`,
> `probe_hook.py`)는 직접 실행해서 동작을 확인했다.

## 사용자 확인이 필요한 항목 (Phase 2~6에서 쌓임, 미결)

- 계약 보완 후보: 각 Phase의 "구현에서 정한 세부" 절 (`parse` 출력 형식과 `ril_*` 이벤트, `--jira-meta` 형식,
  매처 출력, 마스킹 규칙, 생성 파일 표기와 급증 정의, 린터 코드, `config.py` 추가 서브커맨드 등).
  `contracts.md`에 옮길지 정한다.
- Phase 1 산출물 변경: 교차 슬롯 음성 fixture 순서(Phase 3), `type.schema.json`의 `must_match {id, pattern}`(Phase 3),
  fixture를 마스킹해서 생성(Phase 4). 
- 의존성: `pyyaml`, `jsonschema`, `pytest`만 쓴다. 정규식 시간 상한은 작업 프로세스 방식이다(`regex` 모듈을 쓰면
  더 가볍다, 가정 18).
