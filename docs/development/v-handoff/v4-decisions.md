# V4 결정 (R-2~R-8, plan.md §7 D1~D7)

판단 기준: 모든 선택은 판정 대상을 넓히거나 오류를 deny/오류 문구로 바꾸는 쪽(fail-closed)이어야 하고, 새 우회 경로를 열지 않는다. 코드 직접 확인: `guard.py`(check_mcp:183, _strip_prefix:263 — 호출처 1곳 :293, main:816~824 mcp__ deny 분기), `jira_bridge.py main`(SiteDefaultsMissing만 잡음), `mcptools.py`(full_name·candidates prefix), `mask_pii._scope_files:78`, `masking.Masker.__init__:128`, `site_defaults.plugin_root`(env 없으면 `__file__` 폴백), `driver.open_prs:336`, `commands/*.md`(analyze·record·fix-submitted·verify-fix에 `스크립트:` 줄 없음 확인), `run.py`(plugin 모드 system prompt는 경로 미언급, direct 모드만 `$CLAUDE_PLUGIN_ROOT` 언급).

## D1~D7

| D | 선택 | 근거 |
|---|---|---|
| D1 R-2 접두사 출처 | **(c) 합집합** | 접두사 후보가 늘수록 판정 대상만 넓어진다(fail-closed). 정규화 추정이 틀려도 `jira.tools.get_issue`(analyze가 실제로 성공한 이름)에서 뽑은 접두사는 맞고, 플러그인 번들 `mcp__plugin_x_jira__`도 덮는다. `mcp_server` 비어도 tools로 판정하는 것은 기존보다 엄격. 기존 `test_guard_jira_read_only_by_server`의 `mcp__mock-jira-2__…` None 기대는 `startswith("mcp__mock-jira__")`와 어긋나지 않아 유지. |
| D2 R-5 NUL | **(a) NUL 제거 후 검사** | 건너뛰는 파일이 0이 되고 `checked`에 센다(원칙 "건너뛴 검증을 통과로 표시하지 않는다"). UTF-16·잘린 logcat의 PII는 NUL만 빼면 그대로 잡힌다. (b)는 마스킹 끝난 정상 fixture까지 막아 사람이 우회하게 만든다. 진짜 바이너리 오탐 → 커밋 거부(안전 쪽, DB는 텍스트만). |
| D3 R-3 래퍼 범위 | **(b) 확장 표** | `time -p`·`env -S`는 이번에 실제 우회로 재현됐다. 표가 틀려도 결과는 "그 형태를 못 봄"(지금과 같음)이지 잘못된 deny가 아니므로 추가 비용 없이 넓어지기만 한다. 입구 1곳(`_strip_prefix`)이라 규칙 3~7·10·publish ask 전부 같이 막힌다. |
| D4 R-7 `S/` 정의 위치 | **(b) SKILL.md + 커맨드 4개** | 커맨드 4개는 SKILL.md·reference를 **Read**로 읽게 하므로 치환 지점이 커맨드 본문뿐이다(공식 문서: Bash 환경에 변수 없음, 치환은 Markdown body만). (a)만으로는 analyze·record·verify-fix·fix-submitted 커맨드가 그대로 깨진다. 다른 커맨드 7개와 같은 한 줄이라 새 형식도 아니다. |
| D5 plugin.json author | **(a) 일반 이름** | 한 줄, 사내 값 아님(경계 검사 무관), `claude plugin validate` 경고 1개 제거. 팀 이름은 S-1에서 description과 함께 바꾼다. |
| D6 R-8 방식 | **(a) Step 8 preflight 재호출 지시** | Step 4~8 사이 사용자 숙고 중 원격이 바뀔 수 있어 Step 8 직전 값이 맞다. `db_pr preflight`는 lock 없이 fetch만 하므로 재호출이 안전하고 코드·스키마 변경이 없다. (b)는 stale 값으로 `--lease`를 정할 위험 + contracts 변경. |
| D7 R-4 config 실패 시 대상 | **(a) 모든 `mcp__` 결과를 오류 문구로** | (b)에는 "아무것도 못 읽으면 통과"라는 fail-open 가지가 있다. (a)는 guard가 같은 상태에서 모든 `mcp__`를 deny하는 범위와 동일해 새 차단 범위가 아니고 가장 단순하다. `SiteDefaultsMissing`이면 사용자 config로 계속(guard와 같게) — 기존 `return 0`(격리 꺼짐)보다 넓어진다. |

## 범위 밖 처리 (plan §6 그대로, 보고만)
1. guard가 사용자 config 깨지면 Bash 판정 전체 생략(`main` 비-MCP `return 0`) → publish ask도 빠짐. publish 자체가 config 읽기 실패로 종료 2라 실해 낮음 — R-42 묶음에 포함.
2. setup이 플러그인 번들 Jira MCP를 `--server`로 받으면 `_tool_problems` 거부 — A2 보류와 함께 S1 뒤.
3. 다른 Masker 호출자(db_add·parse_logcat·triage·jira_fields·db_summary)의 `AllowPatternError`는 traceback 종료 1로 남음(메시지는 명확해짐). 일괄 종료 2는 R-38.
4. R-42·R-43은 반입 뒤.
5. **추가(이번 확인)**: 커맨드 `verify-fix`·`fix-submitted`를 `/telephony-triage:` 경로로 부르는 eval이 없다(prompt 기준 record·validate·search만). D4 변경은 구조 테스트(`test_script_path_is_defined_where_it_is_substituted`)로만 확인되고 30(record)이 같은 한 줄을 대표한다. 사내 S-2 전체 재실행 때 자연히 덮인다.

## 계획 빈틈 (3)
1. **R-2 접두사 추출 방식**: `normalize(v).rsplit("__",1)[0]+"__"`는 도구 이름에 `__`가 있으면(`mcp__srv__get__issue`) 접두사가 `mcp__srv__get__`로 틀어진다. `normalize`와 같은 `^mcp__(.+?)__` 그룹으로 서버 세그먼트를 뽑는 헬퍼 하나(`server_prefix(name)`)로 통일. 같은 이유로 비교는 **양쪽 정규화**(`normalize(tool) in {normalize(t) for t in read_tools}`)가 추정 규칙이 틀려도 분석을 멈추지 않으면서 우회를 열지 않는다(정규화 이름 충돌은 읽기 도구끼리뿐이고 bridge가 격리). 그러면 `cmd_set_jira`의 저장 전 재작성은 불필요하다 — 미확인 규칙을 설정 파일에 굳히는 쪽이라 빼는 것을 권한다(`candidates`의 구성 이름 정규화는 유지).
2. **R-6 IP 표본 `10.1.2.3`**: 사이트가 사설 대역만 허용하는 정당한 패턴(`^10\.\d+\.\d+\.\d+$`)도 `mask-allow-too-broad` 오류가 되고 lint 오류에는 우회 수단이 없다(결국 db_lint 수정 유도). 표본을 TEST-NET(`203.0.113.7`)로 두면 `.*`·`\d+\.\d+\.\d+\.\d+`는 그대로 잡히고 대역 한정 허용은 통과한다. 사내 판단 여지를 남기되 넓은 패턴 차단은 유지되므로 fail-closed 방향 안에서의 조정.
3. **R-8 "다시 묻지 않는다"**: Step 8 preflight 재호출 결과에 Step 0 때 없던 **새** 열린 PR이 있을 수 있다(그사이 다른 사람이 올림). 문구를 "triage.py가 이미 물은 것은 다시 묻지 않는다 — 단 `analysis.json open_prs`에 없던 PR이 새로 보이면 알리고 계속할지 묻는다"로. 그렇지 않으면 덮어쓰기 위험을 모델이 조용히 지나칠 수 있다.

## eval (결정 (i), 최소) — **1·28·30·43 그대로, 추가 없음**
- 바뀐 스킬 문서: SKILL.md(`S/` 정의·`--clock-offset`·`saved_to` 알림·publish `--json`·Step 8 preflight), rules.md 5·7·9·10, 커맨드 4개 `스크립트:` 줄, write-flow 1행, record.md:28; eval 환경에서 Bash `CLAUDE_PLUGIN_ROOT` 제거.
- 1: Skill 경로 `S/` 치환 + Step 8 새 preflight → 원격 없음 → `--lease new` → publish — 이 조합을 끝까지 가는 유일한 비-dry-run 흐름. 28: R-8 본 시나리오(`remote_sha`≠`pr.head_sha`). 30: 커맨드 경로(D4)의 유일한 batch 1 대표. 43: bridge 정규화·R-4 변경 뒤 격리·`saved_to`.
- 뺀 것 타당: 29(28과 같은 preflight 경로), 39(변경 없음), 12(triage.py가 묻는 쪽, 1·28 질문 수로 간접 확인). 3개로 줄이려면 1을 빼야 하는데 `--lease new` publish 경로가 사라지므로 불가 → 4개가 최소.
- 환경 변경 안전성 확인: 스크립트는 `site_defaults.plugin_root()`가 env 없으면 `__file__`로 폴백, `parse_logcat` 어댑터 치환도 그 값 사용, hooks.json 명령은 Claude Code가 치환 → env 제거로 깨지는 것은 모델의 `S/` 전개뿐(그것이 목적). direct 모드 프롬프트(run.py:125)만 `$CLAUDE_PLUGIN_ROOT`를 말하므로 direct는 그대로가 맞다.

## 사용자 확인 필요 여부
**원칙상 승인 대상 없음.** D1~D7은 분류·유형·시그니처·파서 규칙·수정 상태·이슈 DB push가 아니고, 리뷰가 "설계 변경(사용자 확인)"으로 꼽은 R-27·R-35·R-43에도 속하지 않는다. 08-safety·contracts 갱신은 동작 동기화다. 보고만 할 것: (1) R-2 정규화 규칙은 추정 → `SITE_PROFILE` S1 확인 항목, (2) D1로 "mcp_server 비어 있으면 경고만"이 "tools가 있으면 판정"으로 엄격해짐(문서 §9·guard docstring 갱신), (3) 빈틈 2의 IP 표본 선택은 실행자가 그대로 적용해도 되는 수준(사내 S-3에서 재논의 가능).
