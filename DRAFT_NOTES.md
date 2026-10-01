# DRAFT_NOTES — 사외 초안 상태 파일

> **작게 유지한다(≤6KB).** 사외 초안 모드의 진행 상태·활성 트랙·막힌 것만 둔다 (`docs/design/15-local-draft.md §15.1`).
> Phase별 산출물 표·완료 기준 결과·가정·TODO 목록 같은 **상세 이력은 `docs/history/draft-notes-2026-09.md`** 에 있고, 필요한 절만 찾아 읽는다.
> 이 파일은 반입 때 사내로 같이 간다. `.local-draft`는 가지 않는다. 모드 판별 규칙은 `CLAUDE.md` 머리말.

## 진행 상태

- 모드: **사외 초안** (`.local-draft` 있음)
- 완료 Phase: **D0, 1~12** (2026-09-28~29, Phase 7부터 Phase마다 사용자 확인). 상세: 이력 파일의 "Phase N" 절
- 진행 중 Phase: **13** (SKILL.md·reference·eval 45개). 정의·환경 준비 완료, **행동 평가 미실행**
- 기준 문서 세트: `telephony-triage-docs-v11` (변경 이력 `docs/history/CHANGES.md`)
- 마지막 전체 테스트: `pytest tests` 통과 (2026-10-01, 이 컨테이너 Ubuntu 기준 226개·779s — `ARCHITECTURE_REVIEW` B.3)

## 막힌 것

- Claude Code 주간 한도(HTTP 429) — **10월 4일 09:00(Asia/Seoul) 해제**. 그때까지 Phase 13 행동 평가·트리거 시험·빈 플러그인 실험(S1) 불가.

## 활성 트랙 (셋, 우선순위 순)

| # | 트랙 | 문서 | 다음 할 일 |
|---|---|---|---|
| 1 | **Phase 13** (개발 Phase 마무리) | `docs/design/11-phases.md` Phase 13, 이력 파일 "Phase 13 재개 결과·남은 일" | 한도 해제 후 batch 1 재실행 + 남은 25개 행동 평가(`tests/skill_evals/run.py --execute`, 새 iteration 경로) → 트리거 테스트 → 빈 플러그인 실험(S1) |
| 2 | **개선 RF-0~RF-9** (구조·token·경계) | [ARCHITECTURE_REVIEW_2026-10.md](docs/development/ARCHITECTURE_REVIEW_2026-10.md) §U·§V (리뷰 대기 중, 코드 변경 없음) | 다른 에이전트 리뷰 → RF-0(안전 결함 R2·R3·R6 + 테스트 속도) → RF-1(`triage.py` driver) |
| 3 | **정확성·안전 결함 I0~I6** | [PLUGIN_IMPROVEMENT_HANDOFF.md](docs/development/PLUGIN_IMPROVEMENT_HANDOFF.md) (R1~R15) | RF-0에 흡수됨. 별도로 진행하지 않는다 |

- 트랙 2·3은 Phase 13과 독립이며 코드 변경은 아직 없다. 어느 트랙을 하든 **시작 전에 `git fetch` 후 `origin/main` 기준**으로 한다.
- 사내 로그가 모의와 다를 때 가장 먼저: [S0_PROBE_CHECKLIST.md](docs/development/S0_PROBE_CHECKLIST.md) + `tools/s0_stats.py`.
- 사내 확인 항목(TODO(SITE) 57곳)은 문서가 아니라 `python3 tools/list_site_todos.py`로 뽑는다. 사내 정보가 있어야 판단할 것은 `REVIEW-OPEN.md`.

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
- 설계와 다르게 해석한 곳: Phase 3 완료 기준의 교차 슬롯 C 값은 `--regress`로 확인했다(분석 모드는 S=0이라 원인을
  평가하지 않는다).
- 의존성: `pyyaml`, `jsonschema`, `pytest`만 쓴다. 정규식 시간 상한은 작업 프로세스 방식이다(`regex` 모듈을 쓰면
  더 가볍다, 가정 18).
