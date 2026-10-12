# 트래커 묶음 1 실제 구현 메모 (커밋 7926dc8·49cb249)
- 설계 §1 개명 전부 + 표 밖: mcptools 후보 키 tracker_tools, worktree JOB/RAW_MARKERS, 메시지 속 설정 키 표기 tracker.*, 커맨드 인자 --issue-file/--issue, 템플릿 {{이슈 키}}.
- 안 바꾼 것: eval setup "jira" 키, trace 단계 2-jira, 모의 Jira, 스크립트 파일 이름.
- legacy: userconfig.legacy_problems(site·user·platforms.<p> code_profiles·year_source·field_map.android_version), guard 모든 mcp 거부, bridge 대체, session.resolve·jira_fields·db_search 종료 2, doctor tracker fail, show/set/rename-legacy 관대. config.py rename-legacy [--apply].
- 원칙 (d): 옛 DB 키 대체 읽기 없음(issuedb.SUPPORTED_VERSION_KEY 하나), 옛 키·jira/ 폴더는 db_lint 오류(config·legacy-dir).
- guard RAW_NAMES에 jira_raw.json(방어), worktree RAW_MARKERS jira_raw.json, JOB_MARKERS 옛 3종.
- contracts.md 새 이름으로 정리됨(기준 문서). 나머지 설계 문서·HTML은 묶음 3.
- 비교 도구 W/rename_compare.py(C1~C16), 기준 worktree W/base-tracker(fdf3ced). 묶음 2는 묶음 1 결과(49cb249)를 기준으로 **정규화 없이** 바이트 동일(휘발 값 제외).
- tracker.kind는 받기만 하고 jira 고정. KEY_SAFE_RE·기본 키 정규식(4곳 중복)은 그대로 — 묶음 2에서 어댑터로.

# 묶음 2 실제 (c30a6c6·50124da)
- trackers/{__init__,base,jira}.py: known·get(import 예외 전부 TrackerConfigError)·kind_of/of·db_kind/of_db·mismatch·known_server_words·all_server_words(jira·atlassian 항상 포함). 계층: trackers 모듈은 stdlib + trackers.base만, 동적 import·exec·eval 금지(정적 테스트).
- issuepost: spec_check 공통 검사 유지 + 어댑터 spec_problems(트래커별만), call_arguments·check_call 위임, spec_tracker(spec), 설정에서는 trackers.of(cfg).
- guard: legacy → kind 오류(예외 전부 tracker_error, MCP만 거부) → 코멘트 승인 대조 → read_tools → 경고 → 휴리스틱(all_server_words) → 규칙 11.
- bridge: read_action 결과가 매핑 밖/None/예외면 unsupported로 원문 대체. key_from_read 경로 안전 검사.
- tracker-mismatch: check-key·extract(--db 또는 cwd·clone DB 찾으면), issue_post(스냅샷 → clone → 둘 다 없으면 종료 2), triage·offline.
- jira safe_key_re·default_key_regex는 [0-9]. 샘플 DB key_regex는 \d 그대로.
- 묶음 3으로 남긴 것: 승인 기록에 kind(P2-5), driver가 check-key 정규화 키로 작업 디렉토리(P2-9), github key_from_read는 spec 없이 key_from_args 호출(계약 주석).
