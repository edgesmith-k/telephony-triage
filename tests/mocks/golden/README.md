# 모의 골든 (16-existing-assets.md §16.3)

사외에서 **골든 테스트 틀이 도는지만** 확인하기 위한 모의 골든이다.
`tests/test_golden.py`가 읽는다.

- 실제 골든(포팅 전 기존 파서 출력)은 **사내 전용**이고 `tests/golden/`에 둔다
  (SITE_PATHS. 사외 레포에서는 비어 있어야 한다 — 반입 체크리스트 §15.4).
- 이 디렉토리의 파일은 모의 site 백엔드(`tests/mocks/parser_backends/site/`)의
  출력이다. 백엔드를 고치면 `python3 tests/test_golden.py --update`로 갱신한다.
- 사내에서 진짜 포팅을 할 때는 골든을 **사용자 승인 없이 갱신하지 않는다.**
