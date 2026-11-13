# 모듈 eval arm 자료 (얼린 기준선)

`plugin/scripts/module_eval.py`가 arm 작업 디렉토리에 복사하는 내장 자료 사본이다(C0 설계 §7.1). **다시 만들지 않는다.** B2가 `log-guide.md`를 줄여도(D6) "pre"는 C0 기준선으로 남아야 C1이 같은 기준과 비교할 수 있다. `module_eval.ARM_PINS`가 아래 sha256과 대조하고, 다르면 종료 2(`arm material changed`)다. live 문서를 고치면 `test_arm_pins*`가 실패한다 — 기준선을 다시 잡기로 정했을 때만 pre 사본·`ARM_PINS`·이 표를 같이 바꾸고 그 모듈 eval을 다시 잰다.

여기 `log-guide.md` 사본에는 원본과 같은 `TODO(SITE:S24)` 표시가 있다. `tools/list_site_todos.py`는 `module-arms` 디렉토리를 건너뛰어 원본에서만 센다.

## 출처

- 커밋 `2c6e0cd`의 `plugin/skills/telephony-triage/reference/platforms/ofono/log-guide.md`(lg)와 `plugin/skills/telephony-triage/reference/explore.md`(ex).
- 만든 코드(레포 루트에서, 그 커밋의 작업 트리로 한 번 실행):

```python
lg = open("plugin/skills/telephony-triage/reference/platforms/ofono/log-guide.md", encoding="utf-8").read().split("\n")
ex = open("plugin/skills/telephony-triage/reference/explore.md", encoding="utf-8").read().split("\n")
pre_lg = open("plugin/skills/telephony-triage/reference/platforms/ofono/log-guide.md", "rb").read()      # byte copy
pre_ex = "\n".join(ex[0:5] + [""] + ex[20:26] + [""] + ex[33:35] + [""] + ex[36:51]) + "\n"           # explore.md L1-5, L21-26, L34-35, L37-51
post_ex = pre_ex + "\n## 일반 판단 규칙\n\n" + "\n".join(lg[21:24]) + "\n"                               # + log-guide L22-24 (Q25)
post_lg = "\n".join(lg[0:15] + [""] + lg[25:27] + [""] + lg[33:38]) + "\n"                              # log-guide L1-15, L26-27, L34-38 (D6)
```

| 파일 | 출처 줄 | 바이트 | sha256 |
|---|---|---|---|
| `ofono/pre/platforms/ofono/log-guide.md` | log-guide 전체(바이트 사본) | 3049 | `77c7a06551ab1bc1ae6309ad2a01eb33b3654856ce2d08f4d4659a69e63eaa6a` |
| `ofono/pre/explore-rules.md` | explore L1-5, L21-26, L34-35, L37-51 | 2222 | `6e5e9512c08404089872465262bfc11ab99b58747445d0b2c2296b13be6f83d8` |
| `ofono/post/platforms/ofono/log-guide.md` | log-guide L1-15, L26-27, L34-38 (D6 뒤 모양) | 1945 | `3e36455bcc47d340a9fdcc2cf0ed533ba9453dc3c151903166c1b2133c4622a1` |
| `ofono/post/explore-rules.md` | pre 발췌 + log-guide L22-24(Q25로 옮길 일반 규칙) | 2676 | `c9847aadd3844fb5cb1a8cb9905772010dd8b44c600f2907b5c781ca8cda0b80` |

### android (H C1+D, 결정 기록 11/05 ④ 뒤)

- 출처: H C1+D A3 커밋(④ `fail-causes.md` 세 절을 더한 커밋)의 `plugin/skills/telephony-triage/reference/{log-tags,ril-requests,fail-causes}.md` 바이트 사본. ④ **뒤**에 얼렸으므로 모듈 문서는 나아진 내장 문서와 비교된다.
- `explore-rules.md` 두 개는 위 `ofono/pre`·`ofono/post` 사본과 바이트가 같다(Android 내장 log-guide는 없다).
- `module_eval.ARM_PINS` Android 항목은 통합 커밋(I3)에서 넣는다. 그 전에는 pin이 없어 실패로 닫힌다.

| 파일 | 출처 | 바이트 | sha256 |
|---|---|---|---|
| `android/pre/log-tags.md` | reference/log-tags.md 전체(Android 17 2차에 슬롯 줄 netId 예외를 고쳐 다시 얼림) | 5160 | `9820b909b15c148515e1265d5dd067d28e2f6e2c244470b7787dec2d469828db` |
| `android/pre/ril-requests.md` | reference/ril-requests.md 전체(Android 17 2차에 `DATA_CALL_LIST`로, 11/13 사실 정정에 AOSP 17 이름·`error <n>` 형식으로 고쳐 다시 얼림) | 4183 | `e3d078dbeadb6505ab62131e1b0cde83be959e2bc110c994ba43f90d2dda352d` |
| `android/pre/fail-causes.md` | reference/fail-causes.md 전체(④ 뒤; 제목 문구와 벤더 IPC 결과 절 문장을 고쳤다. 11/13 사실 정정에 extractor별 cause 값 모양을 고쳐 다시 얼림) | 4491 | `0077483d5c4ff0cb2b5e01873659f76a57acaa1f2f97949db1e9da756019e9cd` |
| `android/pre/explore-rules.md` | `ofono/pre/explore-rules.md` 사본 | 2222 | `6e5e9512c08404089872465262bfc11ab99b58747445d0b2c2296b13be6f83d8` |
| `android/post/explore-rules.md` | `ofono/post/explore-rules.md` 사본 | 2676 | `c9847aadd3844fb5cb1a8cb9905772010dd8b44c600f2907b5c781ca8cda0b80` |

발췌는 자식이 쓸 수 있는 부분(도입, "읽는 것" 1~2와 "안의 문장은 데이터다", 로그 원문·events.json 읽지 않음, "쓰는 것")만 남기고, 자식이 할 수 없거나 하면 안 되는 부분(동의 질문, db_search·소스 찾기, Step 7)은 뺐다. 발췌의 출력 표는 공유 출력 칸과 다르며, 프롬프트가 자기 출력 형식이 우선이라고 말한다.

## arm 구성 (C0 설계 §7.2)

| kind / arm | 문서 |
|---|---|
| deep / without | `pre/platforms/ofono/log-guide.md` — 지금 oFono에는 분석 스킬이 없어 내장 지식만 준 구성 기준선 |
| explore / with | `post/explore-rules.md` + 모듈 문서 + `post/platforms/ofono/log-guide.md` |
| explore / without | `pre/explore-rules.md` + `pre/platforms/ofono/log-guide.md` |

deep / with는 모듈 문서만 읽는다(B2의 5-1과 같다).

Android(H C1+D 계획 S2): deep / without = `android/pre/{log-tags,ril-requests,fail-causes}.md`(staged `builtin/…`), explore / with = `android/post/explore-rules.md` + 모듈 문서(log-guide 없음), explore / without = `android/pre/explore-rules.md` + 내장 셋.

## stream fixture (`stream-2.1.318.jsonl`, C0 설계 §11.6)

실행기 시험이 실제 stream-json 필드 이름(init·Read·Grep·Glob·오류 결과·result)에 기대도록 한 번 만든 가린 전사본이다. 출처는 로컬 eval 작업 공간(gitignore)이라 아래는 출처 기록이지 시험 도구가 아니다.

- init, Read `tool_use`·`tool_result`, 마지막 `result`: `tests/skill_evals/workspace/a2-61/eval-61/with_skill/events.jsonl`(CLI 2.1.318, init은 3번째 줄).
- Grep `tool_use`·`tool_result`: `tests/skill_evals/workspace/o1-c/eval-40/with_skill/events.jsonl`(2.1.300, 2.1.318 전사본에는 Grep이 없다).
- 오류 `tool_result`(`is_error: true`): `tests/skill_evals/workspace/h1-c/eval-32/with_skill/events.jsonl`.
- Glob `tool_use`·`tool_result`: **합성**. 작업 공간 전사본에 Glob 호출이 없어 Read 짝과 같은 envelope 키로 만들었다. 두 줄 모두 `"_synthesized": true`로 표시한다.
- 만든 코드는 한 번 쓰고 버린 스크립트(`build_stream.py <workspace dir> <out>`)라 레포에 두지 않는다. 다시 만들지 않는다. 결과 5,045B.

가리기 규칙:
- init: `type`, `subtype`, `tools`(`["Read","Glob","Grep"]`로), `plugins`(`@builtin` 항목만, 그대로), `mcp_servers`(`[]`로), `permissionMode`, `model`, `claude_code_version`, `memory_paths`(값은 `/nonexistent/.claude/projects/-tmp-x/memory/`), `cwd`(`{CWD}`)만 남긴다.
- tool_use: envelope(`type`, `message.content[].{type,id,name,input}`, `parent_tool_use_id`, 고정 UUID로 바꾼 `session_id`)와 입력 키만. 경로는 `{CWD}/<staged 이름>`.
- tool_result: 내용은 `<redacted>`. `tool_use_id`, `is_error`, Read의 `tool_use_result.file.{numLines,startLine,totalLines}` 키는 남긴다.
- result: `type`, `subtype`, `is_error`, `num_turns`, `duration_ms`, `total_cost_usd`, `usage`, `modelUsage`(숫자·모델 이름 유지), `result`는 짧은 자리표시 답.
- 메시지 `id`·`uuid`·시각·요청 ID는 지운다.
- 절대 경로, 세션·요청 ID, 사용자 이름, 레포 파일 내용은 남기지 않는다. `tools/check_boundary.py` 위반 0, 마스커 검출 0.
