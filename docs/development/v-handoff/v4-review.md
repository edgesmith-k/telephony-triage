# V4 리뷰 (R-2~R-8, 브랜치 `v/V4-safety` 작업 트리)

## 판정: **권고**

차단 사유 없음. 모든 변경이 판정 대상을 넓히는 방향(fail-closed)이고 새 fail-open 경로는 찾지 못했다. 새 테스트 11개를 단일 실행해 모두 통과(13.9s). 아래 권고 1~3은 머지 전에 넣는 것이 좋은 작은 보강이고(각 ≤5줄), 나머지는 정보·범위 밖.

재현 방법: `scratchpad/v4/review_probe.py` — 실제 `guard.invocations`·`check_mcp`·`mask_pii._without_nul`·`db_lint.PII_PROBES`·`masking.Masker`를 import해서 80여 개 입력으로 돌렸다(레포 변경 없음).

## R별 재현 표

| R | 시나리오 | 결과 |
|---|---|---|
| R-2 | `mcp_server: jira.corp` + `mcp__jira_corp__create_issue` | **막힘**(deny). `mcp__jira.corp__create_issue`도 deny, `mcp__jira_corp__get_issue` 허용 |
| R-2 | `mcp_server` 비고 `tools`만 (`mcp__jira_corp__get_issue`) | **막힘**: create deny, read_tools 비면 get_issue도 deny |
| R-2 | 플러그인 번들 `mcp__plugin_corp_jira__add_comment` (`mcp_server: jira`) | **막힘**. `mcp__jira__add`도 deny(합집합), `mcp__jira-2__get`·`mcp__other__x` 영향 없음 |
| R-2 | 도구 이름에 `__` (`mcp__srv__get__issue`) | 접두사 `mcp__srv__` 정확(빈틈 ① 반영). `mcp__srv__get` deny |
| R-2 | `tools` 값이 None/정수/비-mcp 문자열, `tools`가 list | 접두사 없음 → 경고만(스키마 문제, 기존과 같음) |
| R-2 | bridge: `tools.get_issue: mcp__jira.corp__…` + 세션 이름 `mcp__jira_corp__…` | **격리됨**(saved_to, PII 없음) |
| R-3 | `timeout 600`·`--foreground`·`-s KILL`·`-k 5 60`·`nice -n5/-5`·`ionice -c3`·`stdbuf -oL`·`sudo -u x`·`sudo --user=x`·`setsid`·`exec -a`·`time -p/-f/-o`·`env -u/-uFOO/--unset=/-i/-S/-S"…"/-C dir/--chdir=dir`·`/usr/bin/timeout`·`\timeout`·`'timeout'`·중첩 3단·`FOO=1 … nohup` | **막힘**(publish ask / main push deny / 규칙 10 deny 모두 동일 경로) |
| R-3 | **`sudo -Eu x git push`**, `-Hu x`, `-iu x` (짧은 옵션 묶음 끝에 값 옵션) | **안 막힘** — argv가 `['x','git','push']`로 읽혀 판정 없음 (권고 1) |
| R-3 | **`env -C/clone git push`**, `sudo -D/clone …` (값 붙은 chdir) | **부분** — 명령은 보이지만 cwd가 바뀌지 않아 다른 cwd에서 부르면 git 규칙 3~6 생략(publish ask는 유지) (권고 1) |
| R-3 | `env -vS "git push …"` | **안 막힘**(한 토큰) — 드묾, 권고 1에 포함 |
| R-3 | 잘못된 deny/ask: `env`·`timeout`·`nice`·`sudo` 단독, `timeout --help`, `command -v git`, `env -S` 단독, `builtin cd` | 모두 판정 없음(정상). 래퍼 해제로 **새 오탐 없음** |
| R-3 | `timeout 600 -- git push` | argv `['--','git','push']` → 판정 없음. GNU timeout은 `+` getopt라 실제로도 `--`를 명령으로 실행하려다 실패 → 실우회 아님 |
| R-4 | 깨진 `config.yaml` + 사용자 config에만 있던 도구 | 종료 0 + "설정을 읽지 못해" 문구, 원문·PII 없음 |
| R-4 | 깨진 `config.yaml` + site-defaults 매핑 도구 | 정상 격리(마스킹 요약) — 테스트 기대 정정(impl 2) 맞음 |
| R-4 | site-defaults 없음 + 사용자 `jira.tools` | 격리됨(기존 `return 0` 폐기) |
| R-4 | 비-MCP 도구 | 출력 없음(그대로) |
| R-5 | `imsi=…890\0tail`, UTF-16 LE/BE/BOM, 값 안 NUL, 한 글자 간격 NUL, NUL 패딩, `\0\r\n` | **모두 검출**, 줄 번호 보존(2·4행 확인) |
| R-5 | 2MB 무작위 바이너리 | 2.1s, 오탐 5건 → 커밋 거부(안전 쪽). 샘플 DB 82파일에 NUL 파일 0 |
| R-6 | allow `.*`·`\d+`·`\d{15}`·`[\d.]+`·`[0-9a-f:]+`·`.+@.+`·`\S+`·`^.{7,20}$`·`[\w.-]+` | **`mask-allow-too-broad`** |
| R-6 | `^10\.\d+\.\d+\.\d+$`·`^192\.168\.…`·`.*@corp\.com`·기존 `^MOCK…$` | 통과(의도) |
| R-6 | **`^\d{11}$`·`^010\d{8}$`·`^\d{10,11}$`·`^\+82\d+$`·`^\d{20}$`** | **통과하지만** 마스커가 잡는 `01012345678`·`+821012345678`(MSISDN)·ICCID 20자리를 전부 허용한다 (권고 2) |
| R-6 | `(`→`schema`, `(a+)+b`→`regex-unsafe`; `mask_pii --check` 종료 2 + "allow_patterns"; guard 문구 "실행하지 못했다" | 확인 |
| R-7 | `reference/*.md`에 `${CLAUDE_PLUGIN_ROOT}` 0건, SKILL·커맨드 4개에 `S/` 정의, rules 7·9·10행, `--clock-offset`, author | 확인 |
| R-8 | `db_pr preflight`는 `require_repo`+fetch만, lock owner 검사 없음(`dbpr/lock.py`에만) → Step 8 재호출이 lock 흐름과 충돌 없음 | 확인 |

## 권고 (머지 전 권장)

### 1. R-3 `_strip_prefix`: 짧은 옵션 묶음·값 붙은 chdir
- 위치: `plugin/scripts/guard.py:297-320`
- 내용: `opt in with_arg`는 정확 일치만 본다. `sudo -Eu x`(`-E`+`-u x`)·`-Hu`·`-iu`는 `-Eu`가 표에 없어 1칸만 건너뛰고 `x`를 명령으로 읽는다 → `sudo -Eu root git commit --no-verify`·`… git push origin HEAD:main`이 판정에서 빠진다(pre-commit은 `--no-verify`로 꺼지므로 guard가 유일한 장치, push는 pre-push가 2차). 같은 이유로 `env -C/clone`·`sudo -D/clone`(값 붙음)은 cwd에 반영되지 않아 다른 디렉토리에서 부르면 규칙 3~6이 생략된다. `env -vS "…"`도 한 토큰으로 남는다.
- 제안(≈5줄): 짧은 옵션 묶음(`-` 하나, `--` 아님)이면 `for ch in opt[1:]`로 돌며 `"-"+ch in with_arg`인 첫 글자에서 멈춘다 — 그 글자가 묶음 끝이면 다음 토큰 소비(`i += 2`), 중간이면 나머지가 값(`i += 1`). chdir은 그 값(다음 토큰 또는 나머지)을 `cwd`에 반영. `S`도 같은 규칙으로 처리하면 `-vS`가 풀린다. 테스트 `test_guard_sees_through_command_wrappers`에 `sudo -Eu x …`(ask)·`env -C<clone> …`(이미 있음)·`env -C"<clone>" …`를 붙인 형태로 1줄씩.

### 2. R-6 `PII_PROBES`에 마스커가 잡는 나머지 종류
- 위치: `plugin/scripts/db_lint.py:72-73`
- 내용: 마스커는 MSISDN을 `010-1234-5678` 외에 `01012345678`·`+821012345678`로도, ICCID 20자리도 잡는데 표본은 하이픈 MSISDN뿐이다. `^\d{11}$`·`^010\d{8}$`·`^\+82\d+$`·`^\d{20}$`가 lint를 통과해 그 종류 전체를 허용한다 — S-3에서 팀이 처음 쓰는 값이라 "넓은 패턴 차단" 목적에 구멍.
- 제안: 표본 3개 추가 `"MSISDN_PLAIN": "01012345678", "MSISDN_INTL": "+821012345678", "ICCID": "89820012345678901234"`(모두 테스트에 이미 있는 합성 값; ICCID는 `tools/boundary-allow.txt`의 db_lint 줄에 값 추가 필요). `test_mask_allow_patterns_checked`의 broad 목록에 `^\d{11}$` 1개.

### 3. R-7 `S/` 정의가 없는 커맨드 경로 (search·sync-pr)
- 위치: `plugin/commands/search.md:8`, `plugin/commands/sync-pr.md:7` ↔ `reference/search.md:11`, `reference/sync-pr.md:13,19,23,29`(`S/db_search.py`, `S/db_pr.py` 사용)
- 내용: 두 reference는 `S/`를 쓰는데 커맨드 본문은 `스크립트: python3 "${…}/scripts/<이름>.py"(결과 JSON)`만 있고 `= S/` 등식이 없다. D4의 논리(치환 지점에 정의)가 이 두 경로에는 적용되지 않았다. 테스트는 `rules.md`를 가리키는 커맨드만 검사해 걸러지지 않는다.
- 제안: 두 커맨드의 `스크립트:` 줄에 ` = \`S/\``를 더한다(각 +8B, 한도 여유 충분). 테스트 조건을 "가리키는 reference 파일에 `` `S/`` 가 있으면"으로 바꾸면 구조적으로 잡힌다.

## 정보 (수정 선택)

### 4. SKILL.md 크기 여유 5B
- `plugin/skills/telephony-triage/SKILL.md` 7,675B / 한도 7,680B(`tests/test_triage.py:379`). 다음 한 글자 수정이 테스트를 깨뜨린다. 권고 3과 무관하지만 Step 8 문단의 "(다시 잡지 않는다)" 같은 중복 괄호를 줄이거나 한도 근거(W6)를 다시 보는 것이 좋다.

### 5. R-4 `event`가 dict가 아닐 때
- `plugin/scripts/jira_bridge.py:146` `event.get(...)`이 try 밖 — stdin이 JSON 배열이면 traceback·종료 1(출력 없음). Claude Code가 보내는 입력에서는 일어나지 않는다. `event = ... if isinstance(..., dict) else {}` 한 줄이면 계약("항상 0")이 완전해진다.

### 6. R-5 바이너리 오탐 메시지
- NUL 파일(실제 바이너리)이 staged면 거부 문구가 "마스킹 안 된 개인정보가 있다"다(디코딩 잡음). DB는 텍스트만 두므로 실제로는 안 생기지만, 생기면 사람이 PII를 찾다 헤맨다. 검출 결과에 `nul: true`를 붙이거나 문구에 "(NUL 포함 파일: 바이너리면 커밋 대상이 아니다)" 한 줄이면 충분. 성능은 ≈1s/MB(guard Bash timeout 180s 안).

### 7. R-2 설정 엣지(fail-closed, 보고만)
- 사용자가 `set-jira --server mine`으로 바꿨는데 site-defaults 팀 기본값 `search_issues: mcp__jira_corp__…`가 merged에 남으면 `mcp__jira_corp__*` 전체가 판정 대상이 되어 read_tools에 없는 `mcp__jira_corp__get_issue`도 deny된다(재현). 드러나는 실패이고 D1 (c)의 의도대로 넓어진 것. docstring "설정 없음" 문단에 한 줄 있으면 좋다.
- `server_segment("日本")` → `""` → 접두사 `mcp____`(`server_prefix`는 None). 비ASCII 서버 이름은 S1 확인 항목에 포함.

## 계획과 다른 점 4개 — 모두 타당
1. NUL 이중 검사: 제거만 하면 `…890tail`로 붙어 미검출(재현). 공백 치환본 병행이 맞다. 두 변형 모두 놓치는 현실적 패턴은 찾지 못했다.
2. `env -C`·`sudo -D` cwd 반영: 올바른 방향(값 붙은 형태만 빠짐 → 권고 1).
3. write-flow 6행 축약: `§6`(121행)에 같은 문장이 있어 정보 손실 없음. `boundary-allow.txt` 추가 줄은 경로·값 모두 좁다.
4. R-4 테스트 기대 정정: 코드 동작과 일치(site-defaults 매핑이 살아 있으면 정상 격리).

## 계획 밖 변경·문체
- 계획 밖 변경 없음(impl 7의 guard 머리말 갱신은 동기화).
- 문체: 일관됨. 한 가지 — SKILL.md:20 "Bash엔 이 변수가 없다"는 치환 뒤 모델이 보는 텍스트에서는 "이 변수"가 가리키는 대상이 사라진다(절대 경로만 남음). rules.md:5의 "플러그인 경로 변수를 Bash에 그대로 쓰지 않는다"가 더 정확하므로 SKILL 쪽도 같은 표현으로 맞추면 좋다(바이트 여유 참고: 정보 4).

## 범위 밖 (이번 리뷰에서 확인한 기존 우회, V4 회귀 아님)
- `git -c alias.p=push p origin HEAD:main`·`git -c alias.c='commit --no-verify' c`: `GitCall`이 alias를 config override로만 저장하고 `sub`가 `p`/`c`라 규칙 전부 생략(재현). `overrides_hooks_path`처럼 `-c alias.*`·`--config-env=alias.*`를 deny하면 2줄. R-42 묶음 후보로 가장 먼저.
- 표 밖 래퍼·셸: `eval '…'`, `su -c '…'`, `script -qc '…'`, `doas`, `busybox timeout`, `flock`, `chrt`, `taskset`, `faketime`, `unbuffer`, `systemd-run`. `eval`·`su -c`·`script -c`는 `SHELLS` 쪽에 넣으면 같은 재귀로 풀린다. 08 §9 "표 밖 래퍼"에 포함되어 문서상 한계로는 맞다.
- (plan §6 그대로) guard가 사용자 config 깨지면 Bash 판정 생략, 다른 Masker 호출자 traceback, R-42·R-43.
