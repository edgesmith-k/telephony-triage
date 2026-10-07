# V5 결정 (D1~D11) — 위임 판단 2026-10-07

기준: `12-principles.md`("건너뛴 검증을 통과로 표시하지 않는다", "판정 기준은 스크립트 출력"), 결정 (c)(판정에 실패 스텝·가설 불사용 — V5는 건드리지 않음), 사내 적응 여지(설정 vs 하드코딩은 비용 대비). 코드 사실은 직접 읽어 확인했다(`logcat.py:130-158`, `parse_logcat.py:341-345,440-449,525-532`, `bugreport.py:21-137`, `platforms/__init__.py:148-168`, `driver.py:680`, `report.py:395-398`, `offline_eval.py:104-124`, `test_golden.py:166-178`).

## D별 선택

| D | 선택 | 근거 1줄 |
|---|---|---|
| D1 | **(a)** 0줄 또는 unparsed > 50% | 분모가 내용 줄(빈 줄·`beginning of` 제외, `logcat.py:135`)이라 50%는 헤더 몇 줄에 안 걸리고, "관측 불완전 → unknown"이 원칙 방향. 사내에서 50%가 안 맞으면 상수 하나라 S7에서 조정 — 설정 키는 YAGNI |
| D2 | **(a)** 경고 `year_rollover_ambiguous`만 | 입력 순서 ≠ 시간 순(`x.1`이 더 오래됨)이고 `--year`의 다중 파일 의미가 미정의. (b)는 설계 변경이며 연 1회 사례 |
| D3 | **(a)** 상수 `main` + `BugreportRules` 필드, site-defaults 키 없음 | logcat 기본 버퍼(main+system+crash)의 정체가 `main`이고 기본 `wanted_buffers`에 이미 있음. (b)는 loader 3줄 + `02-config.md:83` + example 2곳 동기화인데 사내 헤더 자체가 추정(S21) — 헤더가 다르면 `section_regex`(이미 설정)로 대응하고, 이름이 문제가 되면 그때 키 추가 |
| D4 | **(a)** 모의 그대로, 테스트에 AOSP 인라인 | (b)는 `test_extract_bugreport_txt_and_zip` 기대 파일·eval `no-candidates-bugreport` 입력을 바꿔 결정 (i)(eval 최소) 위반 유발, 막는 시나리오는 동일 |
| D5 | **(a)** 항목 `year` > 문서 `year` > `occurred_at` 연도 | `--year`는 "첫 줄 연도"라 12월 로그·1월 Jira처럼 `occurred_at` 연도가 틀리는 경우가 있어 명시값 우선이 맞고, 기존 라벨셋 호환. 틀린 문서 `year`는 새 "범위 밖 → 오류"로 드러남(조용히 0%가 되지 않음) |
| D6 | **(a)** reference `logcat.read_file` | S-0 목적이 "reference 파서 가정과의 차이"(S-4a 전)이고 전체 태그 빈도는 줄 목록이 필요해 (b) `coverage().stats`로 불가 |
| D7 | **(a)** `null`(계약 값 추가) | "로그 범위 밖"이라는 거짓 판정값을 계약에서 제거. 읽는 곳이 `driver.py:680`(`is False`)·`report.py:395,398`·`analysis.logs.in_range`뿐이라 비용 작음. 단 `--full`+0줄도 `null`이 됨(이전 `true`) — 계약에 "window와 무관"으로 명시 |
| D8 | **(a)** 경고 하나(섹션 이름 목록) | stderr/warnings 한 줄, 드라이버가 extract 경고를 analysis에 쓰지 않아 스키마 영향 0 |
| D9 | **(a)** 범위 밖 | `ril.error` 스냅샷 대량 변경 = fixture 기대값 변경(D11 승인 대상)이고 리뷰도 "검토"만 |
| D10 | **(a)** bugreport txt도 `open_log` | 같은 원인(PowerShell `>` UTF-16). `looks_like_bugreport`(:63 `utf-8`)가 UTF-16 헤더를 못 알아보면 logcat으로 오인 → 0줄 → 결국 `file-unparsed`로 멈추긴 하나 안내가 틀림. 2곳 치환 |
| D11 | 실행 중단·보고 | `test_golden.py:172-173` 자체가 "의도한 변경이면 사용자 승인 후 --update"를 요구. 스캔상 변경 0 예상이라 바뀌면 계획 밖 동작 = 멈출 신호 |

## 범위 밖 처리 (계획 §6 확인 + 추가)
- 계획 §6 그대로: D9 `"NONE"→None`, `dumpstate_at` 연도 판단 사용(S21 뒤), "C=1이나 결합 불가" 리포트 이름, R-39·R-41.
- **reference 백엔드 `version()` 올리지 않음**: R-10·R-11은 기존 정상 입력의 출력을 바꾸지 않고(스캔 0건) 이전에 잘못 읽던 입력만 바뀐다. 올리면 `test_golden` 버전 단언·이슈 DB `min_version`에 번진다. 사내 반입 시 S-4a 백엔드 판단과 함께 재검토.
- `platform.bugreport.default_buffer` 키: S21에서 사내 헤더 확인 뒤 필요가 보일 때(D3).
- D1 50% 상수의 설정화: 사내 S7에서 비율이 실제로 걸릴 때.

## 계획 빈틈 (3)
1. **`report.py:395`** — `in_range` 표시 매핑이 `{True, "partial", False}`뿐이라 D7의 `null`은 `"?"`로 찍힌다. 계획의 "읽는 곳 grep"에 빠졌다. `None: "해석한 줄 없음(형식·인코딩)"` 한 항목 추가(`:398`의 `is not True` 경고 분기는 그대로 맞음).
2. **R-13 D5 "현지 연도"** — 계획 코드 `datetime.fromisoformat(occurred_at).year`는 tz 변환이 없다. 리뷰 제안은 현지 연도. 항목/문서 `tz`가 있으면 `.astimezone(ZoneInfo(tz)).year`(1줄). 연말 몇 시간 차이지만 비용 0에 가깝다.
3. **D7 부수 효과 명시** — `_in_range`의 `first_ts` 검사를 `window is None`보다 앞에 두면 `--full`+0줄도 `null`(이전 `true`). `contracts.md:58` 문구를 "`null` = 해석한 줄 없음(window 유무와 무관)"으로 쓰고, `test_zero_lines_is_not_out_of_range`에 `--full` 변형 단언 1개 추가.
- (참고, 빈틈 아님) `file-unparsed` 메시지의 `path.name`은 basename만이고 `logs` 목록에 이미 같은 값이 있어 마스킹 문제 없음. 사내 백엔드가 `coverage()`를 재구현해 `stats.files`가 없으면 파일 단위 검사가 조용히 생략되는데, 이건 `base.py` 독스트링 + `contracts.md:403` 문서화로 충분(사외엔 해당 없음).

## 사용자 확인 필요 여부
- **D1~D10: 추가 확인 불필요.** `12-principles.md`의 확인 대상(분류 확정·새 유형/원인·시그니처·`parser-rules` 추가·수정 상태 변경·DB push·`also_allowed`)에 해당하지 않는다. verify `unknown` 전환(R-11)·연도 규칙(R-10)은 판정 **코드**를 더 보수적으로 바꾸는 것이고, 기존 fixture 기대값·이벤트 스냅샷은 바뀌지 않는다(스캔 0건). V 트랙 PR 리뷰에서 diff로 본다.
- **확인 필요(조건부) — D11**: `test_golden` 골든 또는 `tests/fixtures/logs/*.events.json`이 하나라도 바뀌면 멈추고 사용자에게 재생성 승인을 받는다(`test_golden.py` 자체 규칙 + "기대값 변경은 승인"). D9를 V5로 당기는 경우도 같은 이유로 승인 대상.
- 보고만: R-12 헤더 형식은 추정(S21 TODO 유지), 백엔드 version 미상승 판단.
