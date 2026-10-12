# 작업: 이슈 시스템 범용화 (jira → tracker) — 사용자 요청 10/11

공통 규칙 `W/RULES.md`(D1/D2·이견 줄은 지난 작업 것). 브랜치 `ccr-d022623a-2f4vdx`(main fdf3ced에서 새로 시작). 커밋·push는 메인만.

## 사용자 결정 (추천안 승인)
- 목표: Jira 외 다른 이슈 시스템(GitHub Issues 등)도 설정으로 쓸 수 있게. 범위 ①~④:
  ① 이름 변경 — **형식만**(나중에 바꾸면 DB·설정 변환이 필요한 것): 이슈 DB 기록 폴더 `jira/` → `issues/`, `jira.schema.json` → 중립 이름, `jira_key_regex` 등 DB 설정 키, `templates/jira.yaml`, 사용자·site 설정 키 `jira:` → `tracker:`, 작업 파일(`jira.json`, `jira_raw.json`, `jira_meta.json` 등)·`analysis.json`의 `jira` 키, CLI 옵션(`--jira-file`, `--jira-meta` 등). 사용자에게 보이는 "Jira" 문구, 설계 문서 본문, 내부 함수·스크립트 파일 이름(`jira_bridge.py` 등)은 그대로 둬도 된다(필요 없으면 바꾸지 않는다).
  ② `tracker.kind: jira | github | …` 어댑터: 도구 매핑, 본문 형식(이미 issuepost RENDERERS), 이슈 키 형식.
  ③ Jira 전용 가정 제거: 이슈 키 `ABC-123` 고정(경로 안전 정규식·폴더 이름·guard), guard 규칙 2의 jira·atlassian 이름 휴리스틱(트래커 일반화), 필드 매핑 기본값.
  ④ 두 번째 트래커(GitHub Issues)를 모의 MCP로 붙여 테스트·eval.
- 새 이름: 설정 키 `tracker`, DB 기록 폴더 `issues/`, 버전 필드 `platform_version`(복수 `platform_versions`) — 플랫폼 분리 K9에서 미룬 `android_version(s)` 개명도 이번에.
- 이슈 DB는 아직 사내에 없으므로 **하위 호환 마이그레이션은 최소**로: 스키마 버전 올림 + `db_migrate`로 샘플 DB 변환 경로는 두되(원칙 d: 반입 전에는 v1 스키마를 직접 고친다 — 이 원칙과 충돌 여부를 설계에서 판단), 옛 설정 키를 읽는 호환 계층은 필요한 만큼만.

## 제약
- 분석·매칭·출력 결과는 이름 변경 외에 동일해야 한다(db_regress 23/23, 골든 — 이름이 바뀐 키 외 바이트 동일 비교 방법을 설계에서 정의).
- 승인·lock·버전 검사·플랫폼 대조 규칙 유지, guard 보안 약화 금지(규칙 2: 설정된 트래커 서버의 쓰기 차단·승인 코멘트 예외가 트래커 일반화 후에도 동일 강도).
- 사내 정보 금지. 측정 없는 개편 금지. 생성 파일은 도구로만.
- 끝나면 문서(설계·GUIDE·README·스킬·커맨드·HTML) 전부 맞춘다.

## 사용자 결정 (설계 후, 10/11)
- **스키마 v1 유지(원칙 (d))**: 버전 올림·마이그레이션 없음. 이슈 DB는 main 밖으로 나간 적 없음(사용자 확인). 샘플 DB는 일회성 변환, 옛 형식 읽기 코드 없음.
- 설계서 W/design-tracker.md를 그대로 따른다(이름: tracker, issues/, issue.schema.json, platform_version(s)).
