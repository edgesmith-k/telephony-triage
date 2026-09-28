"""플러그인 스크립트 공통 모듈 (01-architecture.md §3.1).

- site_defaults: `site-defaults.yaml` 로드 (D0)
- buildname: `sanitize_build`, 브랜치 이름 검사 (D0, Phase 2)
- yamlio: 이슈 DB YAML 읽기(날짜 → ISO 문자열) (Phase 2)
- parser_rules: `parser-rules/` 로드·스키마 검증 (Phase 2)
- compat: 이슈 DB 고정 파서 백엔드·외부 파서와 현재 환경 비교 (Phase 2)
- masking: 마스킹 함수 자리 (Phase 2 인터페이스, Phase 4 구현)

config 로드·git 헬퍼·시그니처 컴파일은 Phase 3·6에서 더한다.
"""
