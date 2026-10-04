# DRAFT_NOTES — 사외 초안 상태 파일

> **작게 유지한다(≤8KB).** 사외 초안 모드의 진행 상태·활성 트랙·막힌 것만 둔다 (`docs/design/15-local-draft.md §15.1`).
> Phase별 산출물 표·완료 기준 결과·가정·TODO 목록 같은 **상세 이력은 `docs/history/draft-notes-2026-09.md`** 에 있고, 필요한 절만 찾아 읽는다.
> 이 파일은 반입 때 사내로 같이 간다. `.local-draft`는 가지 않는다. 모드 판별 규칙은 `CLAUDE.md` 머리말.

## 진행 상태

- 모드: **사외 초안** (`.local-draft` 있음)
- 완료 Phase: **D0, 1~13** (D0~12: 09/28~29, 13: 10/03). 상세: 이력 파일의 "Phase N" 절
- Phase 13 결과: 행동 평가 45개 중 41개 통과·4개 실패(5·22·29·44), 트리거 recall 26~33%. **사용자 결정(10/03): 이대로 완료, 실패 4건은 RF 후속, 트리거는 사내 S-2에서 실제 플러그인으로 확인.** 상세: 이력 파일 "Phase 13 행동 평가 결과"
- 기준 문서 세트: `telephony-triage-docs-v11` (변경 이력 `docs/history/CHANGES.md`)
- 마지막 전체 테스트: `pytest tests` 315개 통과 (10/03 RF-2, Windows·Py3.14). 도구 셸은 stdin을 `/dev/null`로, PATH 앞에 실제 Python과 `python3` shim을 둔다(`python`·`python3`이 Store 별칭이면 gh 스텁·git hook이 9009로 실패)

## 막힌 것

- Phase 13 실패 4건은 RF-2에서 고침(eval 5 스크립트, 22·29·44 eval 정의). 행동 eval 재실행은 안 함(토큰) — 사내 S-2 또는 사용자 결정.
- 트리거 시험(skill-creator `run_loop`, Windows는 scratchpad 사본을 스레드 읽기로 패치): precision 100%, recall 26~33%, description 미변경 → 사내 S-2에서 실제 플러그인으로 확인.

## 활성 트랙과 순서 (2026-10-01 결정)

반입 전 순서: **RF-0 → RF-1 → Phase 13 → RF-2 → 반입.** Phase 13 행동 평가는 RF-1 뒤 SKILL로 돌렸다(10/01~03).

| 순서 | 작업 | 근거 문서 | 상태 / 다음 할 일 |
|---|---|---|---|
| ✅ | **리뷰** — RF 계획 외부 리뷰 | 리뷰 문서 머리 "외부 리뷰 결과" | 완료(2026-10-01). 반영 내역은 RF-0·RF-1·RF-2 행에 들어감 |
| 1 | **RF-0** R1~R11 안전·정확성·의존성 + 재현 테스트·session 루트 | HANDOFF R1~R6·I0~I2, 리뷰 §U RF-0·머리 "외부 리뷰 결과" R7~R11 | ✅ 완료. 남은 격리 테스트·07 R6는 RF-1 때 정리 |
| 2 | **RF-1** `triage.py` driver + `SKILL.md` ≤8KB + 커맨드 보일러플레이트 + 외부 리뷰 토큰 항목 | 리뷰 §U RF-1·§V 1·2 | ✅ 완료(10/01). 토큰 실측(eval 1): Bash 20회·입력 0.91M·출력 17k. **남음**: `CLAUDE.md` ≤4KB(사용자 결정), R7(후속) |
| ✅ | **Phase 13** — 행동 평가 45개 + 수동 채점, 트리거 테스트, 빈 플러그인 실험(S1) | `11-phases.md` Phase 13, `tests/skill_evals/README.md`, 이력 파일 "Phase 13 행동 평가 결과" | 10/01~03 앞당겨 실행(사용자 결정). 45개 실행: 41 통과·4 실패, S1 ✅, 트리거 recall 낮음. ✅ 완료(10/03, 실패 4건·트리거는 위 "막힌 것") |
| 4 | **RF-2** 반입 도구 강화(staging·rollback) + `check_boundary.py` + 사외 CI. `export_external.py`는 만들지 않음(결정 a) | 리뷰 §U RF-2 | 구현(10/03), **사용자 확인 대기**: `check_boundary.py`, `import_draft --check-boundary`·staging, `plugin/schemas/`·`sync_schemas.py`, `external.yml`(push 뒤 첫 실행 확인), eval 5·22·29·44. pre-commit 연결은 안 함 |
| 4a | **탐색 분석(Step 5-2)** — 후보 없음·원인 미확인이면 `timeline.md` + Claude 가설(리포트 보조, 점수 무관) | `07 §Step 5-2`, `reference/explore.md` | 구현(10/04, 사용자 요청), **사용자 확인 대기**. 행동 eval은 추가 안 함(S-2 또는 사용자 결정) |
| 4b | **실패 스텝(선택 입력)** — 한 줄, 보조 정보(점수 무관) | `07 §Step 2`, `14 S22` | 구현(10/04). 앵커·우선 유형 구현, 사용자 확인 대기 |
| 5 | **반입** — `15 §15.4` 체크리스트(`check_boundary` 포함), `make_db_skeleton.py`, `git archive` 묶음 | `GUIDE.md` §3 "반입 전", §4 | 그 뒤 사내 S-1~S-7 |
| — | RF-3~RF-9, HANDOFF I3~I6(RF에 흡수) | 리뷰 §U | 반입 뒤 |

- 시작 전 **기존 remote/main을 fetch**, 끝나면 표 갱신. remote 이름은 PC마다 다르다(`telephony` 또는 `origin`) — 있는 것을 쓰고 새로 만들지 않는다.
- 사내 로그가 모의와 다를 때 가장 먼저: [S0_PROBE_CHECKLIST.md](docs/development/S0_PROBE_CHECKLIST.md) + `tools/s0_stats.py` (사내 PC, Claude 없이).
- 사내 확인 항목(TODO(SITE) 57곳)은 `python3 tools/list_site_todos.py`로 뽑는다. 사내 정보가 있어야 판단할 것은 `REVIEW-OPEN.md`.

## 결정 (2026-10-01)

- (a) **사내→사외 반출은 사용자가 직접 타이핑하는 사내 정보 없는 문장뿐.** 도구는 반출물(파일·마스킹 로그·diff·요약)을 만들지 않는다. 사외는 합성 데이터로만 재현한다.
- (b) 자동 게시(RF-8)는 `confidence`가 아니라 별도 품질 게이트로만 채택.
- 외부 리뷰(다른 에이전트, ZIP 기준) 대조 결과와 반영 내역: 리뷰 문서 머리 "외부 리뷰 결과" 절.

- RF-0 구현에서 정한 세부(lock owner·S/C 결합·파서 실패·의존성 고정): 이력 파일 "RF-0 구현에서 정한 세부".

## 문서 정리 남음

- `CLAUDE.md` ≤4KB(§12 이동, 사용자 결정), 리뷰 문서를 계획(§U·V·X)만 남기기, HANDOFF는 I0~I6 완료 후 삭제.

## 사외 Claude Code 실험 결과 (S1 예비)

`tests/mocks/plugin-probe/`로 확인한다. 절차는 그 디렉토리의 `README.md`.
**사내 버전은 다를 수 있으므로 S-2에서 다시 확인한다.**

2026-10-01, Claude Code 2.1.286(Windows), 헤드리스 `claude -p --plugin-dir <dir> --mcp-config tests/mocks/mcp.json`으로 확인.

| # | 항목 | 사외 결과 | 비고 |
|---|---|---|---|
| 1 | 플러그인 로컬 로드 | ✅ `--plugin-dir`로 로드 | init에 `probe@inline`, 슬래시 목록에 `probe:ping`·`probe:probe` |
| 2 | 커맨드 ↔ 스킬 관계 | ✅ 따로 | 커맨드도 `<plugin>:<name>` 스킬 목록에 같이 뜬다. `/probe:probe`는 스킬 본문만 쓰고 커맨드를 부르지 않는다 |
| 3 | `${CLAUDE_PLUGIN_ROOT}` 치환 | ✅ 커맨드·스킬 본문, hooks.json 모두 치환 | **Bash 도구 프로세스에는 환경 변수 `CLAUDE_PLUGIN_ROOT`가 없다**(hook 프로세스에는 있음). 본문 치환 경로만 쓴다 |
| 4 | hooks (SessionStart / PreToolUse / PostToolUse) | ✅ | 실제 `plugin/hooks/hooks.json`: SessionStart가 `scripts_path` 갱신, PostToolUse `jira_bridge.py`가 MCP 결과를 마스킹 요약으로 교체 |
| 5 | MCP 도구 이름 형식 | ✅ `mcp__mock-jira__jira_fetch_ticket` | hook 입력에 `mcp_server {name, source}` 필드도 있다 |
| 6 | hook matcher `mcp__.*` | ✅ | guard 규칙 2(쓰기 도구 거부) 동작 |
| 7 | 권한 결정 필드 | ✅ `hookSpecificOutput.permissionDecision` | `deny` → 실행 안 됨(`PreToolUse:<tool> hook error: <reason>`), `allow` → allowedTools에 없어도 실행, `ask` → allowedTools에 있어도 확인 요구(헤드리스는 거부). guard 규칙 6·8 deny 확인 |
| 8 | `@SITE_PROFILE.md` import (파일 없음) | ✅ 경고·오류 없음 | 조용히 무시 |
| — | 모의 MCP 붙이기 | ✅ `--mcp-config tests/mocks/mcp.json` | 레포 루트에서 실행(상대 경로). source `dynamic` |

## 사용자 확인이 필요한 항목 (Phase 2~6에서 쌓임, 미결)

- 계약 보완 후보: 각 Phase의 "구현에서 정한 세부" 절 (`parse` 출력 형식과 `ril_*` 이벤트, `--jira-meta` 형식,
  매처 출력, 마스킹 규칙, 생성 파일 표기와 급증 정의, 린터 코드, `config.py` 추가 서브커맨드 등).
  `contracts.md`에 옮길지 정한다.
- Phase 1 산출물 변경: 교차 슬롯 음성 fixture 순서(Phase 3), `type.schema.json`의 `must_match {id, pattern}`(Phase 3),
  fixture를 마스킹해서 생성(Phase 4). 
- 의존성: `pyyaml`, `jsonschema`, `pytest`만 쓴다. 정규식 시간 상한은 작업 프로세스 방식이다(가정 18).
