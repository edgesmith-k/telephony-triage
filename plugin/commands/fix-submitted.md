---
description: 수정 CL 반영 기록 — fix.status를 fix-submitted로 바꾸는 fix-submit PR을 만든다
argument-hint: <원인 ID> --ref <CL> --fixed-in <branch>[:<build>]
---

telephony-triage 스킬의 `fix-submitted` 흐름(`reference/verify.md`, 원본 `07-workflow.md §fix-submitted`)을 다음 인자로 실행한다: $ARGUMENTS
스크립트는 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py"`로 호출한다.
어떤 스크립트든 종료 코드 2와 "사내 기본값 없음(S-3 미완료)"을 내면 거기서 멈추고 메시지를 그대로 보여준다.

- `--fixed-in`은 여러 번 줄 수 있고 빌드는 선택이다. 빌드가 없으면 회귀 판정과 `verify-fix`를 할 수 없다고 알리고 계속할지 묻는다.
- 작업 키 `fix-submit-<원인 ID>`로 세션 lock을 잡고 끝나는 모든 경로에서 푼다. 브랜치는 `fix-submit/<원인 ID>`.
- `fix.status`가 `fixed`면 중단한다(회귀라면 analyze Step 7로 open 전환을 안내). `wont-fix`·`not-a-bug`면 상태가 바뀐다고 알리고 확인 후 진행한다.
- push 전에는 확인 화면 승인 후에만 한다.
