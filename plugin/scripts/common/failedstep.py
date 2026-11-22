"""실패 스텝(선택 입력) 추출·정규화 (07-workflow.md §Step 2, 02-config.md §tracker.failed_step_patterns).

이슈에는 시험 절차와 실패한 스텝이 있을 수 있다. Jira 필드나 설명에 있을 때도 있고, 첨부에만 있을 때도 있고,
읽을 수 없을 때도 있다. **실패 스텝은 선택 값이다.** 없거나 읽지 못해도 동작은 이 값이 없던 때와 같다
(질문 없음, 중단 없음, 출력 키 없음). 보조 정보일 뿐이며 S/C 점수·회귀·검증에는 쓰지 않는다.

순수 함수(표준 라이브러리만)다. 정규식 오류는 경고로 바꾸고 예외를 내지 않는다.
패턴 표기는 사내마다 다르다 — TODO(SITE:S22) (`plugin/site-defaults.yaml`의 `tracker.failed_step_patterns`).

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
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from collections.abc import Callable, Iterable

FAILED_STEP_MAX = 200
TEST_STEPS_MAX = 1000
MAX_LINES = 500            # 줄 단위 검색 상한 (정규식 비용 제한)
MAX_LINE_CHARS = 500
SPLIT_LINE_CHARS = 4000    # 표 칸 나누기의 줄 상한(정규식 검색이 아니라 길게 둔다 — 긴 IE 칸 뒤의 판정 칸이 잘리지 않게)
MAX_FILE_BYTES = 1024 * 1024
SOURCES = ("cli", "field", "description", "test_steps", "steps_file")
HTML_MAX_BYTES = 5 * 1024 * 1024    # html·zip 멤버 한 개의 상한
ZIP_MAX_BYTES = 20 * 1024 * 1024    # zip 파일 크기·읽는 총량 상한
ZIP_MAX_MEMBERS = 2000
MAX_STEPS = 500
MAX_SCAN_LINES = 5000
# INCONC(판정 불가, 3GPP 적합성 시험 장비의 세 판정 PASS·FAIL·INCONC)는 FAIL이 없을 때만 실패 스텝으로 쓴다(`_pick_failed`)
DEFAULT_STEPS_STATUS = {"pass": ["pass", "passed", "ok", "성공", "통과"], "fail": ["fail", "failed", "ng", "실패"],
                        "inconc": ["inconc", "inconclusive"]}
# `step`은 번호 열과 이름 열 둘 다의 후보다: 번호 열이 비어 있으면 번호(`Step | Time | … | Message / Action`), 이미 있으면
# 이름(`No | Step | Result`). 이름 열이 따로 없으면 이름 열로 본다(`_find_header`)
DEFAULT_STEPS_COLUMNS = {
    "number": ["no", "#", "step no", "번호", "step"],
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
            # 빈 칸도 자리로 남긴다(표 머리와 열 위치를 맞추게, HTML과 같다)
            return "\n".join(" | ".join(c.strip() for c in row) for row in rows if any(c.strip() for c in row)), None
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
            # 빈 칸도 자리로 남긴다 — 버리면 뒤 칸이 앞으로 당겨져 표 머리와 열 위치가 어긋난다(sim1121 TC 결과 HTML)
            self._row.append(" ".join("".join(self._cell).split()))
        self._cell = None

    def _end_row(self) -> None:
        self._end_cell()
        if self._row and any(self._row):
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


# 판정 단어 뒤 사유 표시: `Fail (사유)`·`Fail [코드]`(괄호는 끝에서 닫혀야 한다 — `OK (popup) button`은 아님)·`FAIL: 사유`·
# `Fail - 사유`. `Fail-safe`·`Failover`·`Passive`는 판정이 아니다.
_REASON_RE = re.compile(r"\s*(?:\(.*\)|\[.*\])$|\s*:|\s+-\s")
# 번호 없이 이름이 이 단어 그대로인 줄은 합계 줄이다(`Total | FAIL`) — 스텝이 아니다.
_SUMMARY_NAMES = {"total", "overall", "overall result", "overall verdict", "final result", "final verdict", "result", "summary",
                  "verdict", "합계", "종합", "최종 결과", "종합 판정", "최종 판정"}


def _verdicts(conf) -> dict[str, set[str]]:
    """판정 단어 `{fail, inconc, pass}`(이 순서로 본다, `cfg.steps_status`)."""
    return {k: _words(conf.get("steps_status") if isinstance(conf, dict) else None, DEFAULT_STEPS_STATUS, k)
            for k in ("fail", "inconc", "pass")}


def _status_of(cell: str, verdicts: dict, reason: bool = False) -> str | None:
    """칸 전체가 판정 단어면 그 판정(fail|inconc|pass). `reason`이면 판정 단어 뒤에 사유 표시(`_REASON_RE`)가 붙은 칸도 맞춘다."""
    key = cell.strip(_STATUS_STRIP).casefold()
    for status, words in verdicts.items():
        if key in words:
            return status
    if reason:
        low = " ".join(cell.split()).casefold()
        for status, words in verdicts.items():
            for w in words:
                if low.startswith(w) and _REASON_RE.match(low, len(w)):
                    return status
    return None


def _split_cells(text) -> list[list[str]]:
    """줄마다 칸 목록. 빈 칸(`a |  | b`)은 자리로 남긴다 — 표 머리와 칸 수를 맞출 때만 쓰고, 맞지 않는 줄은 `_step_row`가 뺀다."""
    return [[c.strip() for c in _CELL_SPLIT.split(line[:SPLIT_LINE_CHARS].strip())]
            for line in str(text or "").splitlines()[:MAX_SCAN_LINES]]


HEAD_CELL_MAX = 30      # 낱말 포함으로 열 이름을 볼 칸의 최대 길이(표 머리 칸은 짧다 — 데이터 칸이 머리로 잡히지 않게)


def _contains_kind(c: str, cols: dict, kinds) -> str | None:
    """열 이름이 낱말로 들어 있는 짧은 칸(`Message / Action`·`Test Result`)의 열 종류(`kinds` 중). 숫자가 든 칸(`Step 3`)은 보지
    않는다(데이터 줄이 표 머리로 잡히지 않게)."""
    if not c or len(c) > HEAD_CELL_MAX or any(ch.isdigit() for ch in c):
        return None
    return next((k for k in kinds if any(re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", c) for w in cols[k])), None)


def _find_header(split, cols, verdicts=None) -> tuple[dict | None, int, int]:
    """표 머리(상태 열을 포함해 열 이름이 2개 이상 맞는 첫 줄) → `(열 위치, 칸 수, 머리 다음 줄 위치)`. 없으면 `(None, 0, 0)`.

    한 줄 안에서 ① 한 종류에만 있는 열 이름과 칸 전체가 같은 칸 ② 여러 종류에 있는 이름(`step`, 번호 열이 비었으면 번호, 아니면
    이름) ③ 아직 못 정한 열만 낱말 포함 — 그래서 뒤의 `Result`가 앞의 `Expected Result`보다 먼저 판정 열이 된다. 번호 열로 본
    칸이 이름 열 이름이기도 하고(`Step`) 이름 열이 따로 없으면 그 칸을 이름 열로 본다. 판정 값(`FAIL`)이 칸 전체인 줄은 머리가
    아니다(한 줄 요약 표 `Failed Step | Step 3 | Verdict | FAIL`)."""
    stop = set().union(*verdicts.values()) if verdicts else set()
    for pos, cells in enumerate(split):
        norm = [" ".join(c.split()).casefold() for c in cells]
        if any(c.strip(_STATUS_STRIP) in stop for c in norm if c):
            continue
        exact = [[k for k in cols if c in cols[k]] for c in norm]
        found: dict[str, int] = {}
        for many in (False, True):
            for idx, kinds in enumerate(exact):
                if kinds and (len(kinds) > 1) == many and idx not in found.values():
                    kind = next((k for k in kinds if k not in found), None)
                    if kind:
                        found[kind] = idx
        for idx, c in enumerate(norm):
            if not exact[idx] and idx not in found.values():
                kind = _contains_kind(c, cols, [k for k in cols if k not in found])
                if kind:
                    found[kind] = idx
        if len(found) >= 2 and "status" in found:
            num = norm[found["number"]] if "number" in found else None
            if num is not None and "name" not in found and (num in cols["name"] or _contains_kind(num, cols, ["name"])):
                found["name"] = found.pop("number")
            return found, len(cells), pos + 1
    return None, 0, 0


def _cols(cfg) -> dict:
    conf = cfg if isinstance(cfg, dict) else {}
    return {k: _words(conf.get("steps_columns"), DEFAULT_STEPS_COLUMNS, k) for k in DEFAULT_STEPS_COLUMNS}


def _header(split, cfg) -> tuple[dict | None, int, int]:
    return _find_header(split, _cols(cfg), _verdicts(cfg if isinstance(cfg, dict) else {}))


def header_line(text, cfg=None) -> str | None:
    """표의 첫 줄(열 이름, 빈 칸 뺌) | None(못 찾음). TC 원문이다 — 밖으로 낼 때는 가린다."""
    split = _split_cells(text)
    header, _, start = _header(split, cfg)
    return " | ".join(c for c in split[start - 1] if c) if header else None


# TC 머리(스텝 표 앞 줄)의 날짜: `2026/11/13`·`2026-11-13`·`2026.11.13`·`2026년 11월 13일`, 뒤에 시각(`10:20:41`)이 있으면 같이.
# 구분자가 없는 숫자(`RPT-20261113-0021` 같은 ID)는 날짜로 보지 않는다
_HEAD_DATE_RE = re.compile(r"(?<![\d.\-/])(\d{4})(?:[-/.]|\s*년\s*)(\d{1,2})(?:[-/.]|\s*월\s*)(\d{1,2})(?:\s*일)?(?!\d)"
                           r"(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?")
_HEAD_START_RE = re.compile(r"(?i)\b(?:start|begin)|시작")


def head_date(text, cfg=None) -> tuple[tuple[int, int, int], tuple[int, int, int] | None] | None:
    """TC 머리(스텝 표 머리 줄 앞)의 날짜 → `((년, 월, 일), (시, 분, 초) | None)` | None(표 머리 없음·날짜 없음·잘못된 날짜).
    시작(Start·Begin·시작) 낱말이 있는 줄의 날짜를 먼저, 없으면 첫 날짜(sim1122 F5 — 스텝 칸이 시각만이면 이 날짜를 붙인다)."""
    header, _, start = _header(_split_cells(text), cfg)
    if header is None:
        return None
    head = str(text or "").splitlines()[: start - 1]
    hits = [(bool(_HEAD_START_RE.search(line)), m) for line in head for m in _HEAD_DATE_RE.finditer(line)]
    for _, m in sorted(hits, key=lambda h: not h[0]):
        y, mo, d = (int(m.group(i)) for i in (1, 2, 3))
        try:
            datetime(y, mo, d)
        except ValueError:
            continue
        clock = (int(m.group(4)), int(m.group(5)), int(m.group(6) or 0)) if m.group(4) else None
        if clock and not (clock[0] < 24 and clock[1] < 60 and clock[2] < 60):
            clock = None
        return (y, mo, d), clock
    return None


def _after_header(text, cfg=None) -> str:
    """표 머리가 있으면 그 다음 줄부터의 텍스트(요약 표의 `Overall result | FAIL` 같은 줄을 패턴이 먼저 잡지 않도록), 없으면 그대로."""
    header, _, start = _header(_split_cells(text), cfg)
    if header is None:
        return str(text or "")
    return "\n".join(str(text).splitlines()[start:])


def parse_steps(text, cfg=None) -> list[dict]:
    """시험 절차 줄 텍스트 → 스텝 목록(≤ 500개) `{index, number, name_raw, status: pass|fail, time_raw}` (`index`는 0부터).

    표 머리(스텝·결과 열 이름이 2개 이상 맞는 첫 줄, `cfg.steps_columns`)가 있으면 그 뒤 줄만 스텝으로 보고(번호 열이 있으면
    첫 칸이 번호인 줄만) 칸 수가 머리와 같을 때 열 위치를 쓴다. 없으면 `|`·탭·공백 2칸 이상으로 나누고 상태는 마지막
    PASS/FAIL 칸(또는 마지막 칸의 끝 낱말)이다. 칸 전체 일치가 없으면 사유 붙은 판정(`Fail (사유)`)을 본다.
    PASS/FAIL이 없거나 이름이 빈 줄, 번호 없는 합계 줄(`Total | FAIL`), 바로 앞 스텝과 번호·판정이 같은 줄(실패 요약)은 스텝이 아니다.
    `time_raw`는 줄의 시각 표기(최대 2개, 공백으로 이은 원문)다 — 밖으로 내보내지 말고 시각을 뽑는 데만 쓴다.
    첫 FAIL 뒤의 줄은 호출자(`read_steps`)가 버린다."""
    from . import stepanchor

    conf = cfg if isinstance(cfg, dict) else {}
    verdicts = _verdicts(conf)
    split = _split_cells(text)
    header, header_n, start = _header(split, conf)      # 표 머리: 이 줄 앞(요약 표 등)은 스텝으로 보지 않는다
    cols = _cols(conf)

    def compact_of(h):      # 빈 칸을 뺀 머리(Jira 위키 표 `||No||Step||` — 머리와 줄의 빈 칸 수가 다르다)
        kept = [i for i, c in enumerate(split[start - 1]) if c]
        return {k: kept.index(v) for k, v in h.items()}, len(kept)

    compact = compact_of(header) if header else None

    def align(cells):       # (칸, 열 위치 | None): 칸 수가 머리와 같으면 그대로, 빈 칸을 뺀 수가 같으면 뺀 칸으로
        if header and len(cells) == header_n:
            return cells, header
        kept = [c for c in cells if c]
        if compact and len(kept) == compact[1]:
            return kept, compact[0]
        return kept, None

    if header:      # 열 이름만으로 번호·이름 열을 잘못 정했으면 데이터로 바로잡는다
        lined = [(c, h) for c, h in map(align, split[start:]) if h and any(c)]

        def col(kind):
            return [c[h[kind]] for c, h in lined if c[h[kind]]]
        if "number" in header and lined and not any(stepanchor.step_number(v) is not None for v in col("number")):
            # 번호 열로 본 칸에 번호가 든 줄이 하나도 없다(`Step | Description | Result`의 Step 열에 Init·Attach) — 번호 열이 아니다.
            # 이름 열이 따로 없을 때만 그 칸을 이름 열로 본다(있으면 `Message / Action`을 `P`·`1.2`로 덮지 않는다)
            header = {**{k: v for k, v in header.items() if k != "number"},
                      **({} if "name" in header else {"name": header["number"]})}
        elif "number" not in header and "name" in header and _bare_numbers(col("name"), stepanchor):
            # 이름 열로 본 칸이 번호뿐이다(설정 열 이름에 `step`이 이름 쪽에만 있는 `Step | … | Message / Action`) — 번호 열로 보고
            # 남은 칸에서 이름 열을 낱말 포함으로 다시 찾는다
            norm = [" ".join(c.split()).casefold() for c in split[start - 1]]
            name = next((i for i, c in enumerate(norm) if i not in header.values() and _contains_kind(c, cols, ["name"])), None)
            # 이름 열로 쓸 칸이 없으면 다른 칸(`Remark`·`횟수`)을 이름으로 고르지 않는다 — 번호 칸을 이름 자리로 두어 이름이 빈다(표시는 번호만)
            header = {**header, "number": header["name"], **({"name": name} if name is not None else {})}
        compact = compact_of(header)
    rows: list[dict] = []
    for cells in split[start:]:
        if not any(cells):
            continue
        cells, at = align(cells)
        row = _step_row(cells, header, at, verdicts, stepanchor)
        if row is None:
            continue
        # 바로 앞 스텝과 번호·판정이 같은 줄은 같은 스텝의 요약이다(결과 HTML 끝 `Failure detail`의 "Step 2: … verdict: FAIL", sim1120
        # P2-2) — 하나로 센다. 떨어져 다시 나온 같은 번호(재시도 회차 `1P 2P 1P 2F`)는 따로 둔다
        if rows and row["number"] is not None and (row["number"], row["status"]) == (rows[-1]["number"], rows[-1]["status"]):
            continue
        row["index"] = len(rows)
        rows.append(row)
        if len(rows) >= MAX_STEPS:
            break
    return rows


def _step_row(cells, header, at, verdicts, stepanchor) -> dict | None:
    """줄 하나 → 스텝 | None. `at`은 열 위치가 맞을 때의 열 위치(`align`), 아니면 None(빈 칸은 이미 뺐다)."""
    if not cells:
        return None
    aligned = at is not None
    full = header
    if aligned:
        header = at
    status = None
    st_idx = None
    if aligned and "status" in header:
        st_idx = header["status"]
        status = _status_of(cells[st_idx], verdicts, reason=True)
        if status is None:
            st_idx = None
    # 오른쪽부터: 모든 칸에서 전체 일치를 먼저, 없을 때만 사유 붙은 판정(이름 칸 `Fail (timeout) 재현`이 먼저 잡히지 않게).
    # 판정 열을 아는 표에서는 다른 칸의 사유 붙은 모양을 판정으로 보지 않는다(`NG (no grant) 확인 | Skip`). 그 밖에는
    # 이름 자리(첫 칸이 번호면 둘째 칸, 아니면 첫 칸)를 사유 붙은 판정으로 보지 않는다(`3 | NG: 거절 확인 | N/A`).
    name_idx = 1 if stepanchor.step_number(cells[0]) is not None else 0
    for reason in (False,) if aligned and "status" in header else (False, True):
        if status is not None:
            break
        for idx in range(len(cells) - 1, -1, -1):
            if reason and idx == name_idx:
                continue
            status = _status_of(cells[idx], verdicts, reason)
            if status:
                st_idx = idx
                break
    off = aligned and st_idx is not None and "status" in header and st_idx != header["status"]
    if off and cells[header["status"]].strip(_STATUS_STRIP):
        # 판정이 판정 열 밖에 있고 판정 열에는 다른 값(`데이터 켜기 | FAIL | 시각`) — 머리를 따르지 않는 줄이라 열 위치를 쓰지 않는다
        return _step_row([c for c in cells if c], full, None, verdicts, stepanchor)
    body = list(cells)
    if status is None:      # 칸이 나뉘지 않은 한 줄: "Step 5: 데이터 켜기 FAIL", 번호가 있으면 "Step 5: 데이터 켜기 Fail (timeout)"도
        tokens = cells[-1].split()
        cut = len(tokens) - 1
        status = _status_of(tokens[-1], verdicts) if len(tokens) > 1 else None
        if status is None and stepanchor.step_number(cells[0]) is not None:
            for cut in range(len(tokens) - 1, 0, -1):
                status = _status_of(" ".join(tokens[cut:]), verdicts, reason=True)
                if status:
                    break
        if status is None:
            return None
        body[-1] = " ".join(tokens[:cut]).rstrip(_STATUS_STRIP + "|")
        st_idx = None
    if (header and "number" in header and status == "pass"
            and stepanchor.step_number(cells[header["number"] if aligned else 0]) is None):
        return None         # 요약 표 등: 번호 열이 있는 표에서 번호를 못 읽은 PASS 줄은 스텝이 아니다
    # FAIL·INCONC 줄은 번호를 못 읽어도(`2.1`·`4a`·`TC-01`·`PA`) 번호 없음으로 받는다 — 실패 자리를 버리지 않는다(합계 줄은 아래 이름으로 거른다)
    time_cells = []
    if aligned and ("start" in header or "end" in header):
        time_cells = [cells[header[k]] for k in ("start", "end") if k in header]
    times = _times(" ".join(time_cells) if time_cells else " ".join(cells), stepanchor)
    if aligned and "name" in header and st_idx is not None:
        number = stepanchor.step_number(cells[header["number"]]) if "number" in header else None
        name = cells[header["name"]]
        if number is not None and header.get("number") == header["name"]:      # 번호 칸이 이름 자리도 맡았다 — 이름은 빈다
            name = stepanchor._LEAD_RE.sub("", name, count=1)
        elif number is None:
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
    if (not name and number is None) or (number is None and name.strip(_STATUS_STRIP).casefold() in _SUMMARY_NAMES):
        return None         # 이름도 번호도 없는 줄, 합계 줄. 번호만 있는 줄(`Step | Result`의 `2 | FAIL`)은 받는다
    return {"number": number, "name_raw": name, "status": status, "time_raw": times}


def _bare_numbers(values: list[str], stepanchor) -> bool:
    """칸들이 번호뿐인가: 번호만 든 칸(`4`, `Step 4`)이 하나 이상이고 나머지는 3자 이하(프리앰블 `P`·`PA`). ponytail: 3자 기준은
    TC 결과 표의 P·PA 표기 하나만 본 것 — 다른 표기가 나오면 늘린다."""
    bare = [stepanchor.step_number(v) is not None and not stepanchor._LEAD_RE.sub("", v, count=1).strip() for v in values]
    return any(bare) and all(b or len(v) <= 3 for b, v in zip(bare, values))


# 날짜만(또는 날짜+시각) 있는 칸: `2026.09.21`, `2026-09-21 10:00:01`. 스텝 이름에 넣지 않는다.
_DATE_CELL = re.compile(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}\.?(?:[ T]+\d{1,2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?)?")


def _time_cell(cell: str, stepanchor) -> bool:
    return bool(stepanchor._TS_RE.fullmatch(cell) or _DATE_CELL.fullmatch(cell))


def _times(text: str, stepanchor) -> str | None:
    spans = [m.group(0) for m in stepanchor._TS_RE.finditer(text)][:2]
    return " ".join(spans) or None


def label(row: dict, masker: Callable[[str], str]) -> str:
    """스텝 한 줄의 표시 이름(마스킹·정규화 ≤ 80자): `5 | 데이터 켜기` 형식(번호 없으면 이름만)."""
    return normalize(masker(_row_text(row)), 80)


def _row_text(row: dict) -> str:
    """`번호 | 이름`(번호 없으면 이름, 이름 없으면 번호)."""
    number, name = row.get("number"), str(row.get("name_raw") or "")
    return name if number is None else f"{number} | {name}" if name else str(number)


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
    failed, verdict = _pick_failed(rows)
    if failed is not None:
        word = verdict.upper()
        extra = sum(1 for r in rows[failed + 1:] if r["status"] == verdict)
        if verdict == "inconc":
            warnings.append(INCONC_USED)
        elif any(r["status"] == "inconc" for r in rows[:failed]):
            warnings.append("steps-file의 첫 FAIL 앞에 INCONC 스텝이 있다 — 첫 FAIL을 실패 스텝으로 썼다")
        if extra:
            warnings.append(f"steps-file에 {word} 스텝이 {extra + 1}개 있다 — 첫 번째를 실패 스텝으로 썼다")
        rows = rows[: failed + 1]
    else:       # 읽었는데 FAIL이 없으면 늘 알린다(PASS 줄이 하나도 없어도) — 조용히 실패 스텝 없음이 되지 않게
        warnings.append(not_found_warning(text, rows, cfg))
    return rows, failed, warnings, member


NOT_FOUND = "steps-file에서 FAIL 스텝을 찾지 못했다"     # 포털이 이 머리로 알아본다(screener `steps_missing`) — 바꾸면 포털도
# 포털 경고 표(web.WARN_NOTE)가 이 머리로 알아본다
INCONC_USED = "steps-file에 FAIL 스텝이 없어 INCONC(판정 불가) 스텝을 실패 스텝으로 썼다"


def _pick_failed(rows: list[dict]) -> tuple[int | None, str | None]:
    """실패 스텝 위치와 그 판정: 첫 FAIL, FAIL이 없을 때만 첫 INCONC(`1 PASS / 2 INCONC / 3 FAIL`이면 3)."""
    for verdict in ("fail", "inconc"):
        idx = next((i for i, r in enumerate(rows) if r["status"] == verdict), None)
        if idx is not None:
            return idx, verdict
    return None, None


def not_found_warning(text, rows: list[dict], cfg=None) -> str:
    """FAIL 스텝을 못 찾았을 때의 경고: 읽은 표의 첫 줄(열 이름만, ≤ 80자)과 판정을 읽은 스텝 수 — 양식이 다른지 사람이 볼 수 있게."""
    head = header_line(text, cfg)
    head = f"읽은 표의 첫 줄(열 이름): {normalize(head, 80)}" if head else "열 이름 줄(번호·이름·판정 열)을 찾지 못함"
    split = _split_cells(text)
    _, _, start = _header(split, cfg)
    verdicts = _verdicts(cfg if isinstance(cfg, dict) else {})
    lost = sum(1 for cells in split[start:] if any(_status_of(c, verdicts) in ("fail", "inconc") for c in cells if c))
    # 포털 경고 표가 "스텝으로 못 읽은 FAIL 줄"로 PASS 안내와 가른다
    return f"{NOT_FOUND} — {head}, 판정을 읽은 스텝 {len(rows)}줄" + (f", 스텝으로 못 읽은 FAIL·INCONC 줄 {lost}개" if lost else "")


def read_steps_file(path, patterns: Iterable[str] | None, cfg=None) -> tuple[str | None, str | None]:
    """`(실패 스텝 원문 | None, 경고 | None)`. 읽지 못하면 `(None, "steps-file을 읽지 못했다(<사유>) — …")`.

    분석 앵커(`triagelib.anchor.steps_file_span`)와 같은 줄을 고른다: 표의 실패 스텝(`번호 | 이름`, `_pick_failed`)이 먼저, 표(열 이름
    줄)가 없을 때만 `patterns`에 맞는 줄. 표를 읽었는데 실패 스텝이 없으면 None(요약 표·프리앰블 줄을 패턴으로 잡지 않는다)."""
    text, why, _ = read_source(path)
    if text is None:
        return None, _unreadable(why)
    rows = parse_steps(text, cfg)
    failed, _ = _pick_failed(rows)
    if failed is not None:
        return _row_text(rows[failed]), None
    if header_line(text, cfg) is not None:
        return None, None
    step, warns = from_text(text, patterns)
    return step or None, (warns[0] if warns else None)


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
