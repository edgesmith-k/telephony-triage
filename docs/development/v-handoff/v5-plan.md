# V5 계획 — S-0 도구·파서 (R-9~R-14)

- 기준: `v/V4-safety` 체크아웃(HEAD a36ce89 위 V4 작업 중). V5 코드 파일은 V4 대상(guard·jira_bridge·mask_pii·스킬 문서)과 겹치지 않는다. **단 V4 작업 트리가 `docs/design/contracts.md`를 수정 중**(계획 시점 `git status`) — V5의 contracts.md 편집(:58·:59·:403 근처)은 V4 커밋 뒤 그 위에서 한다(줄 번호는 grep으로 다시 찾는다).
- 실험 재료(scratchpad, 레포 밖): `scratchpad/v5/exp/` — `r11.py`, `r11v.py`, `r12.py`, `r13.py`, `scan.py`, `oe/offline_eval.py`(R-13 수정 시험본), `proto/lc.py`(R-10·R-11 수정 시험본).
- 결정 (c)(실패 스텝·Claude 가설은 판정에 쓰지 않음)와 무관한 변경만 있다. 판정 경로 변경은 R-11 하나(관측 불완전 → `unknown`/회귀 오류, 더 보수적인 방향).

## 1. R별 재현 확인 (현재 코드, 합성 로그)

| R | 재현 | 실측 |
|---|---|---|
| R-9 | **재현됨** | 형식이 정상인 3줄(RILJ 1 + 미수집 태그 2) → `시각 파싱: 1/3 (33%)`, `태그 상위: [('RILJ', 1)]` (미수집 태그는 안 보임) |
| R-10 재부팅 | **재현됨** | `09-22 …` → `01-01 …`(재부팅) → `09-22 12:05` 줄이 `2027-09-22`로. `--around 2026-09-22T12:05+09:00 --minutes 1` → events 0, `window_in_range: true`(범위가 2027까지 늘어나 "범위 안"으로 보임) |
| R-10 다중 파일 | **재현됨** | `12-31 23:59`(파일1) + `01-01 00:01`(파일2), `--year 2026` → 파일2가 `2025-12-31T15:01Z`(= 2026-01-01 KST, 1년 이름) |
| R-11 UTF-16 | **재현됨** | `dual-sim-ril.log`의 UTF-16LE+BOM 사본 → `window_in_range: false`, warnings `unparsed-lines`·`no-lines-parsed`, `complete: true`, events 0 → 드라이버는 "로그 범위 밖, 전체 파싱할까?"를 묻는다 |
| R-11 UTF-8 BOM | **재현됨**(부분) | 첫 줄 1개 손실 → `window_in_range: partial` |
| R-11 부분 실패 | **재현됨(강함)** | `db_verify fix --cause CALL-001-01 call-fixed.log <call-recurrence.log의 UTF-16 사본>` → **`passed`** (원문 UTF-8이면 `failed` "재발"). `observation_errors()` = `[]` |
| R-12 | **재현됨**(헤더는 **추정**) | `------ SYSTEM LOG (logcat -v threadtime -v printable -v uid -d *:v) ------`(‑b 없음) + EVENT(-b events) + RADIO(-b radio) → files `[('radio', 1)]`, warnings `[]`. AOSP 헤더 형식은 dumpstate.cpp 기억 기준(확인 불가, 사내 S21에서 재확인). 계획은 `-b`가 있든 없든 맞게 동작하게 한다 |
| R-13 | **재현됨** | 샘플 라벨셋에서 `year` 줄만 제거 → top1 85.7% → **0.0%**, errors 0, EVAL-7(unresolved)은 "정답". 드라이버 출력 `logs: {in_range: false, events: 0, range: ["2000-…"]}`이 이미 있어 offline_eval이 판별할 수 있다 |
| R-14 | **확인**(문서) | `match_signatures.py:263-270,386-389` `_compatible`(같은 슬롯 + 근거 전체 시각 폭 ≤ `max(window_sec)`)이 `04 §5.11`에 없음 |

부수 확인
- 픽스처 영향(`exp/scan.py`, `tests/**/*.log|*.txt` 34개, skill_evals 제외): 파일 단위 unparsed > 50% 또는 0줄 = **0개**, 한 파일 안 월이 6 넘게 줄어드는 곳 = **0개**, BOM 있는 `.log` = 0개 → R-10·R-11 변경은 `tests/fixtures/logs/*.events.json`(14개)·`test_golden` **스냅샷을 바꾸지 않을 것으로 예상**(새 경고는 조건이 맞을 때만 나간다). 실행 에이전트가 `test_golden`으로 확인하고, 바뀌면 멈추고 보고.
- 기존 `test_parse_logcat.py:194-204`(12-31 → 01-01 한 파일)은 새 규칙에서도 그대로 통과(시험본으로 확인).

## 2. 변경

### R-9 — `tools/s0_stats.py` (~+25/−8)
- `stats()`에서 원문 줄 수(`read_text().splitlines()`) 대신 reference 줄 해석으로 센다(D6):
  ```python
  def _reference(root): sys.path.insert(0, str(root / "scripts")); from platforms.android import logcat; return logcat
  lines, st = logcat.read_file(log, 0, args.tz, args.year)   # parse() 뒤에 호출(사내 기본값 없음 안내 순서 유지)
  out["format_lines"], out["raw_lines"] = st.lines, st.lines + st.unparsed
  out["all_tags"] = Counter(l.tag for l in lines)
  ```
  `parsed_lines`(수집 줄)는 그대로.
- `show()`:
  - `시각 파싱: format_lines/raw_lines` (라벨 유지 — 이제 형식만 본다)
  - 새 줄 `수집 태그 비율: parsed_lines/format_lines   (tags.yaml에 있는 태그의 줄)`
  - `태그 상위(전체): all_tags.most_common(8)`, `미수집 태그 상위: (all_tags - tags).most_common(5)`
  - 합계 줄에 `format_lines` 추가, `--json`은 `all_tags`도 dict로.
- 독스트링 지표 설명 갱신. `ERROR_RE` `"NONE"` → `None`은 **범위 밖**(D9).

### R-10 — `plugin/scripts/platforms/android/logcat.py` `read_file` (~+12)
```python
base_year = current_year = year or DEFAULT_YEAR
...
if prev_month == 12 and month == 1:            # 해 넘김
    current_year += 1
elif prev_month == 1 and month == 12 and current_year > base_year:   # 12월 중 재부팅(01-01) 뒤 NITZ 복귀
    current_year -= 1
```
- `FileStats`에 `first_month: int|None = None`, `last_month: int|None = None`(연도 없는 줄의 첫/끝 월). 기본값이 있어 site 백엔드 호환.
- 다중 파일(D2 권장 a): `parser_backends/base.py` `coverage()`가 `stats["files"] = [{lines, unparsed, first_month, last_month}]`(파일 순서)를 더한다(R-11과 공유). `parse_logcat.run_parse`에서 연도 인자가 없는 줄이 있고, 어떤 파일의 `last_month == 12`이고 다른 파일의 `first_month == 1`이면 경고 `year_rollover_ambiguous`("여러 파일이 해를 넘긴다 — 연도는 파일마다 --year 기준이라 1월 파일이 1년 이를 수 있다. 파일을 나눠 --year를 따로 준다"). 판정 경로 아님.
- 모듈 독스트링 "12월 → 1월" 문장 갱신.

### R-11 — 인코딩·0줄·부분 실패 (~+35)
1. `logcat.py`에 공용 열기 함수(모든 호출자가 지나가는 한 곳):
   ```python
   def open_log(path):  # UTF-16 BOM이면 utf-16, 아니면 utf-8-sig (BOM 제거). errors=replace, newline=""
       with open(path, "rb") as fh: head = fh.read(2)
       enc = "utf-16" if head in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE) else "utf-8-sig"
       return open(path, encoding=enc, errors="replace", newline="")
   ```
   호출자 교체: `read_file`(:130), `parse_logcat.run_cut`의 원문 읽기(:849), `parse_logcat._read_texts`(:356, `open_log(p).read()`), D10이면 `bugreport.looks_like_bugreport`·`open_bugreport`의 txt 분기.
2. `parse_logcat._in_range`: `if not coverage["first_ts"]: return None`을 **맨 앞**(window None 검사보다 먼저)으로 → 0줄이면 `window_in_range: null`(D7). `no-lines-parsed` 문구: "해석한 logcat 줄이 없습니다 — 로그 범위 밖이 아니라 형식·인코딩 문제입니다(S7)". 드라이버(`driver.py:680`)는 `is False`만 묻으므로 **코드 변경 없음**(경고 문구는 기존 `extra_warnings`로 리포트에 나감).
3. 파일 단위 부분 실패(D1): `run_parse`에서
   ```python
   for path, f in zip(paths, stats.get("files") or []):
       n = f["lines"] + f["unparsed"]
       if f["lines"] == 0 or f["unparsed"] * 2 > n:
           warnings.append({"code": "file-unparsed", "message": f"{path.name}: 해석한 줄 {f['lines']}/{n} — 형식·인코딩 확인. 이 파일의 관측은 불완전하다."})
   ```
   `observation_errors()`의 `codes`에 `"file-unparsed"` 추가 → `complete: false`, `db_verify` resolution·fix는 `unknown`("파서 관측 불완전"), `db_regress`는 그 fixture 오류. `stats["files"]`가 없는 site 백엔드(coverage 재구현)는 검사하지 않는다(문서화).
   - `base.py` `coverage()` 독스트링: `stats.files[]` 추가.

### R-12 — `plugin/scripts/platforms/android/bugreport.py` (~+20)
- `DEFAULT_BUFFER = "main"`(D3) — `-b` 없는 logcat 섹션은 logcat 기본 버퍼(main+system+crash)로 보고 이 이름으로 꺼낸다. `BugreportRules`에 필드 `default_buffer: str = DEFAULT_BUFFER`(site-defaults 키는 만들지 않음, D3).
- `extract()` 섹션 분기:
  ```python
  buf = BUFFER_RE.search(hit.group("cmd"))
  name = buf.group("buf") if buf else rules.default_buffer
  if name in rules.wanted_buffers: current = name; (writer 생성 그대로)
  else: skipped.append(f"{hit.groupdict().get('title') or line.strip('- ')}({name})")
  ```
  끝에 `skipped`가 있으면 경고 하나 `skipped-logcat-sections`(D8). 기존 `-b` 있는 경로·출력 순서는 그대로.
- 헤더의 `== dumpstate: <시각>`(`DUMPSTATE_RE = ^== dumpstate:\s*(?P<v>.+?)\s*$`)을 `build.json`의 `dumpstate_at`로만(결과 JSON의 `build`에는 넣지 않음 → analysis.json 크기·스키마 영향 없음). 연도 판단에 쓰는 것은 범위 밖(§6).
- 모의(`tests/mocks/logcat_gen.py:37`)는 그대로(D4 권장 a), 테스트에 AOSP 형식 인라인 텍스트.

### R-13 — `tools/offline_eval.py` `evaluate_item`·`summarize`·`render` (~+15)
```python
tz = item.get("tz", doc.get("tz"))
year = item.get("year") or doc.get("year") or datetime.fromisoformat(str(item["occurred_at"])).year   # D5
args += ["--year", str(year)] (+ tz 있으면 --tz)
...
logs = analysis.get("logs") or {}
if logs.get("in_range") is False or not logs.get("events"):
    result["error"] = f"로그 범위 밖 또는 이벤트 0 (in_range=…, events=…) — year·tz 확인"; return result
```
- `occurred_at` ISO 파싱 실패는 그 항목 `error`.
- `summarize`에 `"evaluated": len(scored)`, `render`에 `평가 {evaluated}/전체 {total}` 한 줄.
- 독스트링: 항목별 `year`·`tz`, 기본 연도 = `occurred_at` 연도(문서 `year`는 모든 항목이 같은 해일 때만), 범위 밖·이벤트 0 항목은 오류(분모 제외).
- 시험본(`exp/oe/offline_eval.py`)으로 확인: 샘플 그대로 85.7%·오류 0, year 제거본 0.0% → 85.7%, 항목 `year: 2025` → 그 항목만 오류(분모 제외).

### R-14 — `docs/design/04-parser-matching.md §5.11 (1)` (문서 ~+2)
"원인 평가 범위" 분석 모드 항목 뒤에 한 줄:
> 분석 모드의 후보는 증상 시그니처 충족과 원인 시그니처 충족이 **결합 가능**할 때만 C=1이다: 둘 다 `same_phone`이면 근거의 `phone_id` 집합이 겹치거나 한쪽이 비어 있어야 하고(`null`은 와일드카드), 두 근거 전체의 시각 폭이 `max(두 window_sec)` 이내여야 한다(`match_signatures._compatible`). 결합 쌍이 없으면 "유형 일치, 원인 미확인"(S=1, C=0). **회귀·검증 모드는 결합을 보지 않는다**(C 독립 평가).

## 3. 테스트 (R마다 회귀 1개 이상, 모두 현재 코드에서 실패)

| R | 파일 | 테스트 | 수정 전 |
|---|---|---|---|
| R-9 | `tests/test_s0_stats.py` | `test_uncollected_tags_are_parsed_lines_and_listed`: tmp 로그 3줄(RILJ 1 + FooService·BarTag) → `시각 파싱: 3/3 (100%)`, `수집 태그 비율: 1/3 (33%)`, `FooService` 출력 | `1/3 (33%)`, FooService 없음 |
| R-10 | `tests/test_parse_logcat.py` | `test_reboot_new_year_line_does_not_shift_later_lines`: `09-22 12:00` / `01-01 00:00:05` / `09-22 12:05` 3줄, `--around 2026-09-22T12:05:00+09:00 --minutes 1 --year 2026 --tz Asia/Seoul` → 마지막 줄 ts `2026-09-22T03:05:00.000Z`가 events에 있음 + 12월 재부팅 변형(`12-20`/`01-01`/`12-20`, UTC) → 셋째 줄 `2026-12-20…` | events 0 / `2027-…` |
| R-10 | 같은 파일 | `test_multi_file_year_rollover_warns`: 파일1 `12-31 23:59`, 파일2 `01-01 00:01`, `--full --year 2026` → 경고 `year_rollover_ambiguous` | 경고 없음 |
| R-11 | 같은 파일 | `test_utf16_and_bom_logs_parse_like_utf8`: `dual-sim-ril.log`의 UTF-16LE+BOM·UTF-8 BOM 사본 → `(ts, tag)` 목록이 원본과 같음 | UTF-16 0개, BOM 1줄 손실 |
| R-11 | 같은 파일 | `test_zero_lines_is_not_out_of_range`: 형식 없는 텍스트 2줄, `--around` → `window_in_range is None`, 경고 `no-lines-parsed`·`file-unparsed`, `complete is False` | `False`, `complete: True` |
| R-11 | `tests/test_db_verify.py` | `test_fix_unknown_when_one_log_file_is_unreadable`: `fix --cause CALL-001-01 call-fixed.log <call-recurrence.log 각 줄 앞에 "X " 붙인 사본>` → `judgement == "unknown"`, reason에 "관측 불완전"; 같은 recurrence의 UTF-16 사본이면 `failed`(BOM 처리로 읽힘) | 둘 다 `passed`(실측) |
| R-12 | `tests/test_platform_profile.py` | `test_aosp_system_log_without_b_goes_to_default_buffer`: 인라인 `== dumpstate: 2026-09-22 12:10:00` + SYSTEM LOG(‑b 없음) + EVENT LOG(-b events) + RADIO LOG(-b radio) + LAST LOGCAT(`-L -b all`) → files `[("radio",1),("main",1)]`, 경고 `skipped-logcat-sections`에 "EVENT LOG", `build.json` `dumpstate_at == "2026-09-22 12:10:00"` (주석: 헤더 형식 추정, S21) | `[("radio",1)]`, 경고 없음 |
| R-13 | `tests/test_commands.py` | `test_offline_eval_defaults_year_from_occurred_at`: `year` 없는 라벨셋(tz만, EVAL-1 항목 하나) → verdict `1위` | `미스` |
| R-13 | 같은 파일 | `test_offline_eval_out_of_range_item_is_error_not_scored`: 항목 `year: 2025` + occurred_at 2026 → `errors == 1`, `evaluated == 0`, top1 `None`; 텍스트에 `평가 0/전체 1` | 오류 0, `미스`로 집계 |
| R-14 | — | 문서만. 테스트 없음 | — |

- 최소 픽스처: 새 파일 없음(모두 tmp에 인라인 생성 또는 기존 `tests/fixtures/logs/dual-sim-ril.log`·`verify-logs/call-*.log` 재가공). Windows: 쓰기는 `newline="\n"`(LF 테스트).
- 기존 테스트 영향 예상: `test_s0_stats` 두 테스트는 문자열 그대로 통과 예상(모든 줄이 수집 태그이거나 형식 실패). `test_extract_bugreport_txt_and_zip`·`test_platform_profile` bugreport 4개는 `-b` 있는 헤더라 동작 같음. `test_commands` offline_eval 기존 4개 그대로(새 키 추가만).

## 4. 동기화 문서
- `docs/development/S0_PROBE_CHECKLIST.md`: 표 39행(시각 파싱 = 형식만, 태그와 무관), 새 행 "수집 태그 비율"(낮으면 `tags.yaml` 매핑 부족 → S-4, 형식 문제 아님), 41행(RIL 0건 → 먼저 `tags.yaml`에 RIL 태그가 있는지, 형식이 RILJ와 같으면 `platform.ril.tags`, 다르면 `ril.py` 정규식 포팅 S-4a — "`ril.yaml` 보정" 삭제: ril.yaml은 이름·timeout만), 43행·54행(phone_id → `site-defaults.yaml` `platform.log.phone_id` 설정, "코드 상수" 삭제), 44행(태그 상위(전체)·미수집 태그 상위), 판정표 51~52행 문구.
- `docs/design/contracts.md:58`(parse `coverage.window_in_range: true|partial|false|null` — `null` = 해석한 줄 없음; 경고 `file-unparsed`(관측 불완전)·`year_rollover_ambiguous`), `:59`(extract-bugreport: `-b` 없는 섹션은 `main`, 꺼내지 않은 logcat 섹션은 경고 `skipped-logcat-sections`, `build.json`에 `dumpstate_at`), `:403` 근처 백엔드 인터페이스에 `coverage().stats.files[]`(없으면 파일 단위 검사 생략) — 한 구절씩.
- `docs/design/07-workflow.md:131`: `window_in_range: null`이면 "로그 범위 밖"으로 묻지 않고 형식·인코딩 확인 안내.
- `docs/design/04-parser-matching.md`: §5.11 (1) 결합 규칙(R-14), §5.8 (1) 엔진 줄에 "입력 인코딩 UTF-8(BOM 허용)·UTF-16(BOM)" 한 구절.
- `docs/design/05-verification.md:79,114`: unknown 조건에 "파서 관측 불완전(외부 파서 실패·해석 못 한 파일)".
- 코드 독스트링: `s0_stats.py`, `offline_eval.py`, `logcat.py` 머리말, `base.py` coverage, `bugreport.py` 머리말(헤더 형식 추정·S21).
- `gen_contracts.py --check`: argparse 변경 없음 → 영향 없음(확인만).

## 5. 완료 기준
- §1 표의 시나리오가 모두 더는 재현되지 않음(§3 테스트 9개 통과, 수정 전 실패를 실행 에이전트가 한 번 확인).
- `test_golden` 통과, `tests/fixtures/logs/*.events.json` **변경 0**(바뀌면 멈추고 보고 → D11).
- `python3 tools/related_tests.py --run` 통과(환경 실패 4건 제외), `gen_contracts.py --check` 0.
- 문서 §4 반영, R-14 문장이 `_compatible` 코드와 일치.
- `git status`: 바뀐 파일이 §2·§3·§4 목록 안.

## 6. 위험·범위 밖
- 위험
  - R-11 `file-unparsed`가 `db_regress`의 fixture 오류가 됨 → 현재 레포 fixture 0개 해당(스캔). 사내 fixture에 헤더 섞인 파일이 있으면 회귀 오류로 드러남(의도된 방향, 50% 기준이 완충).
  - R-11 `window_in_range: null`은 계약 값 추가 — 읽는 곳은 드라이버(`is False`)·`analysis.logs.in_range`(스키마 `{}`) 뿐(grep 확인).
  - R-12 `-b` 없는 SYSTEM LOG가 `logcat-main.txt`로 나감 — 사내 bugreport에 별도 `-b main` 섹션도 있으면 같은 파일에 합쳐진다(같은 writer). 헤더 형식은 추정이므로 S21에서 확인 필요(`SITE_PROFILE` TODO 유지).
  - R-10 12월 재부팅 되돌림 규칙: 1월 로그에 NITZ가 12월로 되감는 드문 경우는 앞 해가 맞으므로 오히려 맞다. 다중 파일 경고는 12월 재부팅 다중 파일에서 거짓 경고 가능(경고뿐).
  - site 백엔드가 `parse`/`coverage`를 재구현했으면 BOM·월 규칙·파일 단위 검사가 적용 안 됨(사외엔 없음).
- 범위 밖
  - `ERROR_RE` 미일치 `"NONE"` → `None`(D9): events 스냅샷 `ril.error` 값 변경 → 반입 뒤.
  - `dumpstate_at`을 드라이버 연도 판단에 쓰기: S21 헤더 확인 뒤.
  - "C=1이나 결합 불가" 리포트 이름(R-14 후반) — 리뷰가 반입 뒤로 정함.
  - R-39(`cut`이 백엔드 우회)·R-41(offline_eval 지표 정의)은 별도 항목.

## 7. 결정 (D)
| D | 질문 | 선택지 | 권장·근거 |
|---|---|---|---|
| D1 | R-11 파일 단위 부분 실패 기준 | (a) 0줄 또는 unparsed > 50% (b) 0줄만 (c) unparsed > 0 | **(a)** 리뷰 제안. (b)는 부분 형식 불일치를 못 잡고 (c)는 헤더 줄 한두 개로 회귀가 깨진다 |
| D2 | R-10 다중 파일 해 넘김 | (a) 경고 `year_rollover_ambiguous`만 (b) 1월로 시작하고 12월이 없는 파일을 다른 파일에 12월이 있으면 +1(재읽기) | **(a)** 입력 순서가 시간 순이 아닐 수 있고(`x.1`이 더 오래됨) `--year`의 다중 파일 의미가 정의돼 있지 않다. 연 1회 경우라 경고로 충분, (b)는 설계 변경 |
| D3 | R-12 `-b` 없는 섹션의 버퍼 이름·설정 | (a) 코드 상수 `main`(BugreportRules 필드, site-defaults 키 없음) (b) `platform.bugreport.default_buffer` 키 (c) 이름 `system` | **(a)** logcat 기본 버퍼가 main+system+crash이고 기존 `wanted_buffers` 기본에 `main`이 있다. 키는 S21에서 필요가 보이면(YAGNI, 02-config·example 동기화 2곳 절약) |
| D4 | R-12 모의 | (a) 모의 그대로, 테스트에 AOSP 형식 인라인 (b) `logcat_gen` SYSTEM LOG 헤더에서 `-b` 제거 | **(a)** (b)는 `test_extract_bugreport_txt_and_zip` 기대 파일 목록과 eval `no-candidates-bugreport` 입력을 바꾸는데 막는 시나리오는 (a)와 같다 |
| D5 | R-13 연도 우선순위 | (a) 항목 `year` > 문서 `year` > `occurred_at` 연도 (b) 항목 > `occurred_at`(문서 `year` 무시) | **(a)** 기존 라벨셋 호환. 문서 `year`가 틀린 항목은 새 "범위 밖 → 오류"로 드러난다. 독스트링에 "문서 year는 모든 항목이 같은 해일 때만" |
| D6 | R-9 형식 파싱을 무엇으로 세나 | (a) reference `logcat.read_file` (b) 설정된 백엔드 `coverage().stats` | **(a)** S-0의 목적이 "사외 reference 파서 가정과 얼마나 다른가"(S-4a 백엔드 결정 전). 태그 빈도도 줄 목록이 필요해 (b)로는 안 된다 |
| D7 | R-11 0줄일 때 `window_in_range` | (a) `null`(계약 값 추가) (b) `false` 유지, 드라이버가 `first_ts` 없으면 묻지 않음 | **(a)** 리뷰 제안, "범위 밖"이라는 거짓 값을 계약에서 없앤다. 문서 2곳 |
| D8 | R-12 꺼내지 않은 logcat 섹션 보고 | (a) 경고 하나(섹션 이름 목록) (b) 결과에 `skipped` 필드 | **(a)** stderr 한 줄, 드라이버는 extract 경고를 쓰지 않아 analysis 영향 없음 |
| D9 | `ERROR_RE` `"NONE"`→`None` | (a) 범위 밖 (b) V5에서 | **(a)** 이벤트 스냅샷 `ril.error` 대량 변경 + 리뷰도 "검토" |
| D10 | bugreport txt도 `open_log` | (a) 포함(2곳) (b) 제외 | **(a)** 같은 원인(PowerShell `>`로 저장한 txt). `looks_like_bugreport`가 UTF-16에서 못 알아보면 logcat으로 오인 → 0줄 |
| D11 | 스냅샷이 바뀌면 | 실행 중단·보고 → 사용자에게 재생성 여부 | 예상 변경 0이라 재생성 계획 없음(바뀌면 계획 밖 동작) |

## 8. 실행 모델·테스트·eval
- 실행: **Sonnet 5.5**(§1 표, V5는 Opus 실행 VP 아님). 리뷰: Opus.
- `related_tests.py --json --files <§2·§3·§4 파일>` 결과: **`full: true`** (사유: `parse_logcat.py`·`platforms/android/{logcat,bugreport}.py` 공용 모듈 간접 importer 24 > 8, `parser_backends/base.py` 백엔드 인터페이스). 선택 테스트 29개(test_commands, test_db_verify, test_parse_logcat, test_platform_profile, test_s0_stats, test_golden, test_db_regress, test_improvement_regressions, test_triage* 등) → 오케스트레이터가 로컬 전체 테스트를 백그라운드로(§3-6).
- eval: **0** — 스킬·reference 변경 없음(결정 (i)). D4 (b)를 고르면 eval `no-candidates-bugreport` 입력이 바뀌므로 그 1건을 V 끝 후보로.
- 예상 크기: 코드 ~110, 테스트 ~90, 문서 ~20 → ~220줄(리뷰 추정 ~215).
