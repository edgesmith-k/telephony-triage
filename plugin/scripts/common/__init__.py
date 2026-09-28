"""플러그인 스크립트 공통 모듈 (01-architecture.md §3.1).

- site_defaults: `site-defaults.yaml` 로드 (D0)
- buildname: `sanitize_build`, 브랜치 이름 검사 (D0, Phase 2)
- yamlio: 이슈 DB YAML 읽기(날짜 → ISO 문자열) (Phase 2)
- parser_rules: `parser-rules/` 로드·스키마 검증 (Phase 2)
- compat: 이슈 DB 고정 파서 백엔드·외부 파서와 현재 환경 비교 (Phase 2)
- masking: 마스킹 함수 자리 (Phase 2 인터페이스, Phase 4 구현)
- patterns: 정규식 시간 상한 실행기 (Phase 3)
- signatures: 시그니처 컴파일·평가 (Phase 3)
- issuedb: 이슈 DB 읽기(설정·유형·Jira 건수·피드백) (Phase 3)
- builds: `build_compare` 빌드 비교 (Phase 3)
- dbpath: `--db` 기본값 (Phase 3, 사용자 config 연결은 Phase 6)
- fixtures: fixture 이름 규칙·기본 기대값 (Phase 5)
- compiled: `.cache/compiled.json` 컴파일 캐시 (Phase 5)
- gitscope: `--changed`·`--staged`·`--ref` 범위와 index·ref 트리 꺼내기 (Phase 5)
- versions: `GENERATOR_VERSION`, `SCHEMA_VERSION` (Phase 5)

config 로드·git 헬퍼는 Phase 6에서 더한다.
"""
