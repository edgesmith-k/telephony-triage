"""실패 스텝(선택 입력) 추출·정규화 (07-workflow.md §Step 2, 02-config.md §jira.failed_step_patterns).

이슈에는 시험 절차와 실패한 스텝이 있을 수 있다. Jira 필드나 설명에 있을 때도 있고, 첨부에만 있을 때도 있고,
읽을 수 없을 때도 있다. **실패 스텝은 선택 값이다.** 없거나 읽지 못해도 동작은 이 값이 없던 때와 같다
(질문 없음, 중단 없음, 출력 키 없음). 보조 정보일 뿐이며 S/C 점수·회귀·검증에는 쓰지 않는다.

순수 함수(표준 라이브러리만)다. 정규식 오류는 경고로 바꾸고 예외를 내지 않는다.
패턴 표기는 사내마다 다르다 — TODO(SITE:S22) (`plugin/site-defaults.yaml`의 `jira.failed_step_patterns`).

시험 절차(steps-file)는 txt/csv/tsv, html(`report.html` 등), zip(안의 파일 하나)이다. 시험은 **첫 FAIL 스텝에서 멈추므로**
FAIL 스텝이 마지막으로 실행된 스텝이다. `read_source`가 텍스트로 바꾸고 `parse_steps`가 스텝 목록으로 만든다.
zip은 메모리에서만 읽고 풀지 않는다.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
import zlib
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable

FAILED_STEP_MAX = 200
TEST_STEPS_MAX = 1000
MAX_LINES = 500            # 줄 단위 검색 상한 (정규식 비용 제한)
MAX_LINE_CHARS = 500
MAX_FILE_BYTES = 1024 * 1024
SOURCES = ("cli", "field", "description", "test_steps", "steps_file")
HTML_MAX_BYTES = 5 * 1024 * 1024    # html·zip 멤버 한 개의 상한
ZIP_MAX_BYTES = 20 * 1024 * 1024    # zip 파일 크기·읽는 총량 상한
ZIP_MAX_MEMBERS = 2000
MAX_STEPS = 500
MAX_SCAN_LINES = 5000
DEFAULT_STEPS_STATUS = {"pass": ["pass", "passed", "ok", "성공", "통과"], "fail": ["fail", "failed", "ng", "실패"]}
DEFAULT_STEPS_COLUMNS = {
    "number": ["no", "#", "step no", "번호"],
    "name": ["step", "action", "name", "description", "절차", "내용", "항목"],
    "status": ["result", "status", "verdict", "결과", "판정"],
    "start": ["start", "start time", "시작"],
    "end": ["end", "end time", "종료", "time", "시각"],
}


def normalize(text, limit: int = FAILED_STEP_MAX) -> str:
    """한 줄로 합치고(공백 압축) `limit`자로 자른다(넘으면 끝을 `…`로)."""
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def _compile(patterns: Iterable[str] | None) -> tuple[list[re.Pattern], list[str]]:
    warnings: list[str] = []
    compiled: list[re.Pattern] = []
    for p in patterns or []:
        try:
            compiled.append(re.compile(str(p)))
        except (re.error, TypeError, ValueError) as exc:
            warnings.append(f"failed_step_patterns 정규식 오류({p!s:.60}): {exc} — 건너뜀")
    return compiled, warnings


def _scan(text, compiled: list[re.Pattern]) -> tuple[str | None, str | None]:
    if not compiled or not text:
        return None, None
    for line in str(text).splitlines()[:MAX_LINES]:
        line = line[:MAX_LINE_CHARS]
        if not line.strip():
            continue
        for rx in compiled:
            m = rx.search(line)
            if not m:
                continue
            step = m.groupdict().get("step") if "step" in rx.groupindex else None
            return (step if step and step.strip() else line), line
    return None, None


def find_line(text, patterns: Iterable[str] | None) -> tuple[str | None, str | None]:
    """여러 줄 텍스트에서 실패 스텝 한 줄을 찾는다. `(step|None, 맞은 줄|None)`.

    줄 순서대로 보고, 한 줄에서는 패턴 순서대로 보아 처음 맞는 것이 이긴다. `(?P<step>…)` 그룹이 있으면 그 값,
    없으면 줄 전체. 맞은 줄(원문)은 호출자가 시각 같은 보조 값을 뽑을 때만 쓴다 — 밖으로 내보내지 않는다.
    잘못된 정규식은 건너뛴다(경고는 `from_text`가 낸다)."""
    return _scan(text, _compile(patterns)[0])


# 번호로 보는 것: `Step 7`·`스텝 7`·`단계 7`, `7 |`(표 행), `7.`·`7)` 뒤에 공백과 숫자가 아닌 글자(`7. Attach`).
# 시각·날짜(`12:03:44`, `2026.09.21`, `2026-09-21`)·`10.5`·`3G`는 번호가 아니다.
_NO_BODY = r"(?:(?:step|스텝|단계)\s*(\d+)\b|(\d+)\s*\||(\d+)[.)]\s+(?=[^\d\s]))"
_STEP_NO_RE = re.compile(r"(?i)^\s*" + _NO_BODY)
_STEP_PREFIX_RE = re.compile(r"(?i)^\s*" + _NO_BODY + r"[\s:.\-)|]*")
_NUMBERED_RE = re.compile(r"^\s*\d+\s*\|")


def numbered(step: str | None, line: str | None) -> str | None:
    """패턴이 이름만 뽑았어도 맞은 줄이 `Step 7 …`·`7 | …`·`7. …`처럼 번호로 시작하면 `7 | 이름`으로 맞춘다.
    뽑은 이름이 이미 `7. 이름`·`Step 7 이름`·`7) 이름`처럼 번호로 시작하면 그 번호를 떼고 `7 | 이름`으로 쓴다.
    표의 FAIL 행·Jira 필드와 같은 표기라 README "자주 실패한 스텝"이 한 줄로 묶인다."""
    if not step or _NUMBERED_RE.match(step):
        return step
    own = _STEP_PREFIX_RE.match(step)
    if own:
        rest = step[own.end():].strip()
        number = next(g for g in own.groups() if g is not None)
        return f"{number} | {rest}" if rest else step
    if not line:
        return step
    m = _STEP_NO_RE.match(line)
    if m and step.strip() != line.strip():
        return f"{next(g for g in m.groups() if g is not None)} | {step.strip()}"
    return step


_numbered = numbered


def from_text(text, patterns: Iterable[str] | None) -> tuple[str | None, list[str]]:
    """여러 줄 텍스트에서 실패 스텝 한 줄을 뽑는다. `(step|None, warnings)`.

    `find_line`과 같은 규칙이고, 잘못된 정규식은 경고만 내고 건너뛴다. 맞은 줄이 스텝 번호로 시작하면
    `번호 | 이름`으로 낸다(`_numbered`)."""
    compiled, warnings = _compile(patterns)
    step, line = _scan(text, compiled)
    return _numbered(step, line), warnings


def group_key(text) -> str:
    """실패 스텝을 묶는 키: 공백 압축 + casefold (README 집계와 스텝 이름 비교가 같은 키를 쓴다)."""
    return " ".join(str(text or "").split()).casefold()


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp949")


def _lines_from_bytes(data: bytes, suffix: str) -> tuple[str | None, str | None]:
    """txt/csv/tsv 바이트 → 줄 텍스트(CSV·TSV는 셀을 ` | `로 합친다). 실패하면 `(None, 사유)`."""
    try:
        text = _decode(data)
        if "\x00" in text:
            return None, "텍스트 파일이 아님"
        if suffix in (".csv", ".tsv"):
            delim = "\t" if suffix == ".tsv" else ","
            rows = csv.reader(io.StringIO(text, newline=""), delimiter=delim)
            return "\n".join(" | ".join(c.strip() for c in row if c.strip()) for row in rows), None
        return text, None
    except UnicodeDecodeError:
        return None, "인코딩을 알 수 없음"
    except csv.Error as exc:
        return None, f"CSV 오류: {exc}"


def _read_lines(path) -> tuple[str | None, str | None]:
    """steps-file(txt/csv/tsv)을 줄 텍스트로. 실패하면 `(None, 사유)`. 파일은 복사·삭제하지 않는다."""
    p = Path(path)
    try:
        if p.stat().st_size > MAX_FILE_BYTES:
            return None, "1 MiB 초과"
        return _lines_from_bytes(p.read_bytes(), p.suffix.lower())
    except OSError as exc:
        return None, exc.strerror or type(exc).__name__


class _HtmlLines(HTMLParser):
    """HTML → 줄 텍스트. `<tr>` 한 줄(`<td>/<th>` 셀을 ` | `로 합침, 빈 셀 제외), 블록 태그는 줄바꿈, script·style은 버린다."""

    _BLOCK = {"p", "div", "br", "li", "ul", "ol", "table", "tbody", "thead", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._text: list[str] = []
        self._skip = 0

    def _end_text(self) -> None:
        line = " ".join("".join(self._text).split())
        self._text = []
        if line:
            self.lines.append(line)

    def _end_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            cell = " ".join("".join(self._cell).split())
            if cell:
                self._row.append(cell)
        self._cell = None

    def _end_row(self) -> None:
        self._end_cell()
        if self._row:
            self.lines.append(" | ".join(self._row))
        self._row = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif self._skip:
            return
        elif tag == "tr":
            self._end_text()
            self._end_row()
            self._row = []
        elif tag in ("td", "th"):
            self._end_cell()
            if self._row is None:
                self._end_text()
                self._row = []
            self._cell = []
        elif tag in self._BLOCK:
            if self._cell is not None:
                self._cell.append(" ")
            else:
                self._end_text()

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif self._skip:
            return
        elif tag in ("td", "th"):
            self._end_cell()
        elif tag == "tr":
            self._end_row()
        elif tag == "table":
            self._end_row()
            self._end_text()
        elif tag in self._BLOCK:
            if self._cell is not None:
                self._cell.append(" ")
            else:
                self._end_text()

    def handle_data(self, data):
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data)
        elif self._row is None:
            self._text.append(data)

    def close(self):
        super().close()
        self._end_row()
        self._end_text()


def html_to_lines(data: bytes) -> tuple[str | None, str | None]:
    """HTML 바이트 → 줄 텍스트. 실패하면 `(None, 사유)`."""
    if len(data) > HTML_MAX_BYTES:
        return None, "5 MiB 초과"
    try:
        raw = _decode(data)
    except UnicodeDecodeError:
        return None, "인코딩을 알 수 없음"
    if "\x00" in raw:
        return None, "텍스트 파일이 아님"
    parser = _HtmlLines()
    try:
        parser.feed(raw)
        parser.close()
    except Exception as exc:    # noqa: BLE001 — 깨진 HTML도 예외 대신 사유로
        return None, f"HTML 오류: {type(exc).__name__}"
    return "\n".join(parser.lines), None


def _text_from_bytes(data: bytes, suffix: str) -> tuple[str | None, str | None]:
    if suffix in (".html", ".htm"):
        return html_to_lines(data)
    return _lines_from_bytes(data, suffix)


_ZIP_TEXT = (".csv", ".tsv", ".txt")


def _zip_tier(name: str) -> int | None:
    base = name.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if base == "report.html":
        return 0
    suffix = Path(base).suffix
    if suffix in (".html", ".htm"):
        return 1
    if suffix in _ZIP_TEXT:
        return 2
    return None


def _unsafe_member(name: str) -> bool:
    norm = name.replace("\\", "/")
    return norm.startswith("/") or bool(re.match(r"^[A-Za-z]:", norm)) or ".." in norm.split("/")


def _read_zip(p: Path) -> tuple[str | None, str | None, str | None]:
    """zip을 풀지 않고 메모리에서 읽는다. 후보 하나(report.html > 다른 html > csv/tsv/txt)만 고른다."""
    if p.stat().st_size > ZIP_MAX_BYTES:
        return None, "20 MiB 초과", None
    try:
        with zipfile.ZipFile(p) as zf:
            cands = []
            for info in zf.infolist()[:ZIP_MAX_MEMBERS]:
                if info.is_dir() or _unsafe_member(info.filename):
                    continue
                tier = _zip_tier(info.filename)
                if tier is None:
                    continue
                name = info.filename.replace("\\", "/")
                cands.append(((tier, name.count("/"), name.casefold(), name), info))
            if not cands:
                return None, "zip에서 시험 절차 파일(report.html 등)을 찾지 못함", None
            cands.sort(key=lambda it: it[0])
            info = cands[0][1]
            if info.flag_bits & 0x1:
                return None, "암호화된 zip 항목은 읽지 않음", None
            if info.file_size > HTML_MAX_BYTES:
                return None, "5 MiB 초과", None
            with zf.open(info) as fh:
                data = fh.read(HTML_MAX_BYTES + 1)
            if len(data) > HTML_MAX_BYTES:
                return None, "5 MiB 초과", None
            text, why = _text_from_bytes(data, Path(info.filename).suffix.lower())
            return text, why, info.filename if text is not None else None
    except (zipfile.BadZipFile, RuntimeError, zlib.error, NotImplementedError, EOFError, ValueError):
        return None, "zip을 열 수 없음", None
    except OSError as exc:
        return None, exc.strerror or type(exc).__name__, None


def read_source(path) -> tuple[str | None, str | None, str | None]:
    """steps-file(txt/csv/tsv/html/htm/zip) → `(줄 텍스트 | None, 읽지 못한 사유 | None, zip 멤버 경로 | None)`.

    zip은 메모리에서만 읽는다(풀지 않는다). 멤버 경로는 zip일 때만 있다(리포트에 마스킹해서 쓴다)."""
    p = Path(path)
    suffix = p.suffix.lower()
    try:
        if suffix == ".zip":
            return _read_zip(p)
        if suffix in (".html", ".htm"):
            if p.stat().st_size > HTML_MAX_BYTES:
                return None, "5 MiB 초과", None
            text, why = html_to_lines(p.read_bytes())
            return text, why, None
        text, why = _read_lines(p)
        return text, why, None
    except OSError as exc:
        return None, exc.strerror or type(exc).__name__, None


def read_lines(path) -> tuple[str | None, str | None]:
    """steps-file을 줄 텍스트로(CSV는 셀을 ` | `로 합친다). html·zip도 읽는다. 시각을 뽑는 호출자용."""
    text, why, _ = read_source(path)
    return text, why


# -- 스텝 목록 ---------------------------------------------------------------------------------------

_CELL_SPLIT = re.compile(r"\s*\|\s*|\t+|\s{2,}")
_STATUS_STRIP = " .:;,-()[]<>*"


def _words(mapping, defaults: dict, key: str) -> set[str]:
    words = mapping.get(key) if isinstance(mapping, dict) else None
    if not isinstance(words, (list, tuple)) or not words:
        words = defaults[key]
    # YAML 1.1은 따옴표 없는 no를 False로 읽는다 — 열 이름 `no`로 되돌린다
    return {" ".join(("no" if w is False else str(w)).split()).casefold() for w in words}


def _status_of(cell: str, pass_w: set[str], fail_w: set[str]) -> str | None:
    key = cell.strip(_STATUS_STRIP).casefold()
    if key in fail_w:
        return "fail"
    if key in pass_w:
        return "pass"
    return None


def _split_cells(text) -> list[list[str]]:
    return [[c.strip() for c in _CELL_SPLIT.split(line[:MAX_LINE_CHARS]) if c.strip()]
            for line in str(text or "").splitlines()[:MAX_SCAN_LINES]]


def _find_header(split, cols) -> tuple[dict | None, int, int]:
    """표 머리(상태 열을 포함해 열 이름이 2개 이상 맞는 첫 줄) → `(열 위치, 칸 수, 머리 다음 줄 위치)`. 없으면 `(None, 0, 0)`."""
    for pos, cells in enumerate(split):
        found: dict[str, int] = {}
        for idx, cell in enumerate(cells):
            for kind, words in cols.items():
                if kind not in found and cell.casefold() in words:
                    found[kind] = idx
                    break
        if len(found) >= 2 and "status" in found:
            return found, len(cells), pos + 1
    return None, 0, 0


def _after_header(text, cfg=None) -> str:
    """표 머리가 있으면 그 다음 줄부터의 텍스트(요약 표의 `Overall result | FAIL` 같은 줄을 패턴이 먼저 잡지 않도록), 없으면 그대로."""
    conf = cfg if isinstance(cfg, dict) else {}
    cols = {k: _words(conf.get("steps_columns"), DEFAULT_STEPS_COLUMNS, k) for k in DEFAULT_STEPS_COLUMNS}
    header, _, start = _find_header(_split_cells(text), cols)
    if header is None:
        return str(text or "")
    return "\n".join(str(text).splitlines()[start:])


def parse_steps(text, cfg=None) -> list[dict]:
    """시험 절차 줄 텍스트 → 스텝 목록(≤ 500개) `{index, number, name_raw, status: pass|fail, time_raw}` (`index`는 0부터).

    표 머리(스텝·결과 열 이름이 2개 이상 맞는 첫 줄, `cfg.steps_columns`)가 있으면 그 뒤 줄만 스텝으로 보고(번호 열이 있으면
    첫 칸이 번호인 줄만) 칸 수가 머리와 같을 때 열 위치를 쓴다. 없으면 `|`·탭·공백 2칸 이상으로 나누고 상태는 마지막
    PASS/FAIL 칸(또는 마지막 칸의 끝 낱말)이다. PASS/FAIL이 없거나 이름이 빈 줄은 스텝이 아니다.
    `time_raw`는 줄의 시각 표기(최대 2개, 공백으로 이은 원문)다 — 밖으로 내보내지 말고 시각을 뽑는 데만 쓴다.
    첫 FAIL 뒤의 줄은 호출자(`read_steps`)가 버린다."""
    from . import stepanchor

    conf = cfg if isinstance(cfg, dict) else {}
    pass_w = _words(conf.get("steps_status"), DEFAULT_STEPS_STATUS, "pass")
    fail_w = _words(conf.get("steps_status"), DEFAULT_STEPS_STATUS, "fail")
    cols = {k: _words(conf.get("steps_columns"), DEFAULT_STEPS_COLUMNS, k) for k in DEFAULT_STEPS_COLUMNS}
    split = _split_cells(text)
    header, header_n, start = _find_header(split, cols)      # 표 머리: 이 줄 앞(요약 표 등)은 스텝으로 보지 않는다
    rows: list[dict] = []
    for cells in split[start:]:
        if not cells:
            continue
        row = _step_row(cells, header, header_n, pass_w, fail_w, stepanchor)
        if row is None:
            continue
        row["index"] = len(rows)
        rows.append(row)
        if len(rows) >= MAX_STEPS:
            break
    return rows


def _step_row(cells, header, header_n, pass_w, fail_w, stepanchor) -> dict | None:
    aligned = bool(header) and len(cells) == header_n
    status = None
    st_idx = None
    if aligned and "status" in header:
        st_idx = header["status"]
        status = _status_of(cells[st_idx], pass_w, fail_w)
        if status is None:
            st_idx = None
    if status is None:
        for idx in range(len(cells) - 1, -1, -1):
            status = _status_of(cells[idx], pass_w, fail_w)
            if status:
                st_idx = idx
                break
    body = list(cells)
    if status is None:      # 칸이 나뉘지 않은 한 줄: "Step 5: 데이터 켜기 FAIL"
        tokens = cells[-1].split()
        status = _status_of(tokens[-1], pass_w, fail_w) if len(tokens) > 1 else None
        if status is None:
            return None
        body[-1] = " ".join(tokens[:-1]).rstrip(_STATUS_STRIP + "|")
        st_idx = None
    if header and "number" in header and stepanchor.step_number(cells[0]) is None:
        return None         # 요약 표 등: 번호 열이 있는 표에서는 번호가 있는 줄만 스텝
    time_cells = []
    if aligned and ("start" in header or "end" in header):
        time_cells = [cells[header[k]] for k in ("start", "end") if k in header]
    times = _times(" ".join(time_cells) if time_cells else " ".join(cells), stepanchor)
    if aligned and "name" in header and st_idx is not None:
        number = stepanchor.step_number(cells[header["number"]]) if "number" in header else None
        name = cells[header["name"]]
        if number is None:
            number = stepanchor.step_number(name)
            name = stepanchor._LEAD_RE.sub("", name, count=1) if number is not None else name
    else:
        if st_idx is not None:
            before = body[:st_idx]
            after = body[st_idx + 1:]
            body = before if any(not _time_cell(c, stepanchor) for c in before) else after
        body = [c for c in body if not _time_cell(c, stepanchor)]
        number = stepanchor.step_number(body[0]) if body else None
        if number is not None:
            body[0] = stepanchor._LEAD_RE.sub("", body[0], count=1)
        name = " | ".join(c for c in body if c)
    name = " ".join(str(name).split())
    if not name:
        return None
    return {"number": number, "name_raw": name, "status": status, "time_raw": times}


# 날짜만(또는 날짜+시각) 있는 칸: `2026.09.21`, `2026-09-21 10:00:01`. 스텝 이름에 넣지 않는다.
_DATE_CELL = re.compile(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}\.?(?:[ T]+\d{1,2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?)?")


def _time_cell(cell: str, stepanchor) -> bool:
    return bool(stepanchor._TS_RE.fullmatch(cell) or _DATE_CELL.fullmatch(cell))


def _times(text: str, stepanchor) -> str | None:
    spans = [m.group(0) for m in stepanchor._TS_RE.finditer(text)][:2]
    return " ".join(spans) or None


def label(row: dict, masker: Callable[[str], str]) -> str:
    """스텝 한 줄의 표시 이름(마스킹·정규화 ≤ 80자): `5 | 데이터 켜기` 형식(번호 없으면 이름만)."""
    number = row.get("number")
    raw = f"{number} | {row.get('name_raw')}" if number is not None else str(row.get("name_raw") or "")
    return normalize(masker(raw), 80)


def _unreadable(why) -> str:
    return f"steps-file을 읽지 못했다({why}) — 실패 스텝 없이 진행"


def read_steps(path, cfg=None) -> tuple[list[dict], int | None, list[str], str | None]:
    """steps-file → `(스텝 목록, 실패 스텝 위치 | None, 경고, zip 멤버 경로 | None)`.

    시험은 첫 FAIL에서 멈추므로 실패 스텝 = 첫 FAIL 줄이고 그 뒤 줄은 버린다(FAIL이 더 있으면 경고).
    읽지 못하면 `([], None, [경고], None)`."""
    text, why, member = read_source(path)
    if text is None:
        return [], None, [_unreadable(why)], None
    rows = parse_steps(text, cfg)
    warnings: list[str] = []
    failed = next((i for i, r in enumerate(rows) if r["status"] == "fail"), None)
    if failed is not None:
        extra = sum(1 for r in rows[failed + 1:] if r["status"] == "fail")
        if extra:
            warnings.append(f"steps-file에 FAIL 스텝이 {extra + 1}개 있다 — 시험은 첫 FAIL에서 멈추므로 첫 번째만 썼다")
        rows = rows[: failed + 1]
    elif rows:
        warnings.append("steps-file에서 FAIL 스텝을 찾지 못했다")
    return rows, failed, warnings, member


def read_steps_file(path, patterns: Iterable[str] | None, cfg=None) -> tuple[str | None, str | None]:
    """`(실패 스텝 원문 | None, 경고 | None)`. 읽지 못하면 `(None, "steps-file을 읽지 못했다(<사유>) — …")`.

    `patterns`가 먼저이고, 맞는 줄이 없으면 표의 FAIL 스텝(`번호 | 이름`)으로 대신한다."""
    text, why, _ = read_source(path)
    if text is None:
        return None, _unreadable(why)
    step, warns = from_text(_after_header(text, cfg), patterns)
    if step:
        return step, (warns[0] if warns else None)
    fail = next((r for r in parse_steps(text, cfg) if r["status"] == "fail"), None)
    if fail is not None:
        number = fail.get("number")
        return (f"{number} | {fail['name_raw']}" if number is not None else fail["name_raw"]), (warns[0] if warns else None)
    return None, (warns[0] if warns else None)


def auto_from(field_value, description, test_steps, patterns, masker: Callable[[str], str]):
    """Jira에서 자동으로 얻은 값. 우선순위 필드 > 설명 > 시험 절차 텍스트. `({text, source} | None, warnings)`.

    `description`·`test_steps`는 이미 마스킹된 텍스트여도 된다(마스킹은 멱등)."""
    warnings: list[str] = []
    if field_value not in (None, "", []):
        t = normalize(masker(str(field_value)))
        if t:
            return {"text": t, "source": "field"}, warnings
    for source, body in (("description", description), ("test_steps", test_steps)):
        step, w = from_text(body, patterns)
        warnings += [x for x in w if x not in warnings]
        if step:
            t = normalize(masker(step))
            if t:
                return {"text": t, "source": source}, warnings
    return None, warnings


def resolve(cli, auto, steps_file, patterns, masker: Callable[[str], str], cfg=None):
    """우선순위 cli > auto(필드 > 설명 > 시험 절차) > steps_file. `({text, source} | None, warnings)`.

    `auto`는 `{text, source}`(이미 마스킹) 또는 None. 모든 값은 마스킹 후 정규화한다. steps_file은 `patterns`로 먼저
    찾고, 없으면 표의 FAIL 스텝으로 대신한다(`cfg`는 `failed_step` 설정: steps_status·steps_columns)."""
    warnings: list[str] = []
    if cli and str(cli).strip():
        t = normalize(masker(str(cli)))
        if t:
            return {"text": t, "source": "cli"}, warnings
    if auto and auto.get("text"):
        return {"text": normalize(masker(str(auto["text"]))), "source": auto.get("source") or "field"}, warnings
    if steps_file:
        step, warn = read_steps_file(steps_file, patterns, cfg)
        if warn:
            warnings.append(warn)
        if step:
            t = normalize(masker(step))
            if t:
                return {"text": t, "source": "steps_file"}, warnings
    return None, warnings
