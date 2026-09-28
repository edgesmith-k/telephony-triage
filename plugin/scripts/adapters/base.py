"""어댑터 계약 (16-existing-assets.md §16.3 "대안: 어댑터 방식").

기존 파서를 포팅하지 않고 그대로 실행하고, 출력만 이벤트 형식으로 바꾼다.
어댑터 모듈(`adapters/<adapter>.py`)은 아래 세 가지를 제공한다.

    ADAPTER_NAME: str          # 파일 이름과 같다. site-defaults의 external_parsers.<cat>.adapter
    VERSION: str               # 어댑터 버전 (골든·회귀 기준 고정)
    convert(raw, meta) -> list[dict]

- `raw`: 기존 파서 출력(`output: json`이면 JSON으로 읽은 값).
- `meta`: `{"log": <로그 경로>, "category": <카테고리>, "tz": <IANA|None>, "year": <int|None>}`.
- 반환 이벤트: `{ts, tag, msg, event, fields, phone_id}` (+ 선택 `pid`, `tid`, `level`).
  - `event`는 `ext.<category>.<이름>`이거나 `None`(줄 레코드, `mode: replace`에서만 쓴다).
  - `ts`는 ISO 시각(오프셋 있으면 그대로, 없으면 `meta.tz`로 해석) 또는 logcat 스탬프
    (`MM-DD HH:MM:SS.mmm`, 연도는 `meta.year`). `parse_logcat.py`가 UTC로 바꾼다.
  - `source`, `category_hint`는 `parse_logcat.py`가 채운다(`external:<adapter>`, 카테고리).
- 같은 입력이면 항상 같은 출력이어야 한다.

`site-defaults.yaml` 설정:

```yaml
external_parsers:
  <category>:
    command: ["python3", "${CLAUDE_PLUGIN_ROOT}/scripts/adapters/site_vendor/<기존 파서>.py", "{log}"]
    output: json
    adapter: <adapter>
    version: <기존 파서 버전 또는 파일 해시>   # 이슈 DB external_parsers.<cat>.min_version과 비교
    mode: merge          # merge | replace (replace면 백엔드의 그 카테고리 레코드를 뺀다)
    timeout_sec: 120
```
"""
