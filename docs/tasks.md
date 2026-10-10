# 사내 보완 단계별 읽을 것 (pack)

`python3 tools/context_pack.py S-n`이 `읽을 것`의 항목을 이어서 출력한다. 항목은 `경로` 또는 `경로 §절`(여러 절은 `§14.2·14.3`, 표의 한 행만은 `§14.2:S2`). `DRAFT_NOTES.md`는 사외 전용 절(새 세션 시작·남은 일)을 빼고 절 단위로 싣는다. `CLAUDE.md`와 `SITE_PROFILE.md`는 자동 로드(import)되므로 넣지 않는다. 할 일은 `docs/design/15-local-draft.md §15.5`.

| pack | 읽을 것 | 비고 |
|---|---|---|
| S-0 | `docs/design/04-parser-matching.md §5.8`, `docs/development/S0_PROBE_CHECKLIST.md` | 선택. CLI는 `parse_logcat.py --help`·`s0_stats.py --help`·`s0_suggest.py --help` |
| S-1 | `docs/design/12-principles.md`, `DRAFT_NOTES.md §진행 상태·사내로 넘긴 것·사외에서는 못 하는 것·막힌 것·결정`, `REVIEW-OPEN.md`, `docs/design/14-site.md §14.2·14.3` | 이력 `docs/history/draft-notes-*.md`는 읽지 않는다. TODO(SITE)는 `python3 tools/list_site_todos.py` |
| S-2 | `DRAFT_NOTES.md §진행 상태·사내로 넘긴 것·사외에서는 못 하는 것·막힌 것·결정`, `tests/skill_evals/README.md`, `tests/mocks/plugin-probe/README.md` | 실패한 코드 파일을 더 읽는다 |
| S-3 | `plugin/site-defaults.example.yaml`, `docs/design/02-config.md` | |
| S-4a | `docs/design/16-existing-assets.md` | 기존 자산(파서·분류·분석 스킬) 추가 |
| S-4 | `docs/design/04-parser-matching.md`, `docs/design/16-existing-assets.md §16.4` | 테스트 출력 추가. tags.yaml diff·슬롯·벤더 RIL 초안은 `s0_suggest.py --help` |
| S-5 | — | 실패 시 해당 `07-workflow.md` 절만 |
| S-6 | `REVIEW-OPEN.md` | |
| S-7 | `docs/design/14-site.md §14.2:S2`, `docs/design/06-collaboration.md §6.6·6.9`, `docs/design/01-architecture.md §3` | 파일럿 뒤 측정하고 정한다(반입 차단 조건 아님): D1 후보 없을 때 단어별 DB 검색 반복(4-hints, 호출마다 DB 재로드) → trace 측정 뒤 상한·단일 로드, D2 `prepare()`가 재사용 판정 전에 bugreport 추출 → 대형 첨부 측정 뒤 재사용, D3 setup 질문 묶기·코드 위치 힌트·`fit()` 생략 표시, D4 읽기 전용 상태 한 화면(작은 상태 명령부터, 웹 UI 아님), D5 월간 리뷰 후속 조치를 기존 업무 도구와 연결, D6 머지 병목 측정 뒤 `13-actions.md` 전환 검토 |
