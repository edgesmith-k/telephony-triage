"""실패 스텝(선택 입력) 추출·정규화 (07-workflow.md §Step 2, 02-config.md §jira.failed_step_patterns).

이슈에는 시험 절차와 실패한 스텝이 있을 수 있다. Jira 필드나 설명에 있을 때도 있고, 첨부에만 있을 때도 있고,
읽을 수 없을 때도 있다. **실패 스텝은 선택 값이다.** 없거나 읽지 못해도 동작은 이 값이 없던 때와 같다
(질문 없음, 중단 없음, 출력 키 없음). 보조 정보일 뿐이며 S/C 점수·회귀·검증에는 쓰지 않는다.

순수 함수(표준 라이브러리만)다. 정규식 오류는 경고로 바꾸고 예외를 내지 않는다.
패턴 표기는 사내마다 다르다 — TODO(SITE:S22) (`plugin/site-defaults.yaml`의 `jira.failed_step_patterns`).
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Callable, Iterable

FAILED_STEP_MAX = 200
TEST_STEPS_MAX = 1000
MAX_LINES = 500            # 줄 단위 검색 상한 (정규식 비용 제한)
MAX_LINE_CHARS = 500
MAX_FILE_BYTES = 1024 * 1024
SOURCES = ("cli", "field", "description", "test_steps", "steps_file")


def normalize(text, limit: int = FAILED_STEP_MAX) -> str:
    """한 줄로 합치고(공백 압축) `limit`자로 자른다(넘으면 끝을 `…`로)."""
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def from_text(text, patterns: Iterable[str] | None) -> tuple[str | None, list[str]]:
    """여러 줄 텍스트에서 실패 스텝 한 줄을 뽑는다. `(step|None, warnings)`.

    줄 순서대로 보고, 한 줄에서는 패턴 순서대로 보아 처음 맞는 것이 이긴다. `(?P<step>…)` 그룹이 있으면 그 값,
    없으면 줄 전체. 잘못된 정규식은 경고만 내고 건너뛴다.
    """
    warnings: list[str] = []
    compiled: list[re.Pattern] = []
    for p in patterns or []:
        try:
            compiled.append(re.compile(str(p)))
        except (re.error, TypeError, ValueError) as exc:
            warnings.append(f"failed_step_patterns 정규식 오류({p!s:.60}): {exc} — 건너뜀")
    if not compiled or not text:
        return None, warnings
    for line in str(text).splitlines()[:MAX_LINES]:
        line = line[:MAX_LINE_CHARS]
        if not line.strip():
            continue
        for rx in compiled:
            m = rx.search(line)
            if not m:
                continue
            step = m.groupdict().get("step") if "step" in rx.groupindex else None
            return (step if step and step.strip() else line), warnings
    return None, warnings


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp949")


def _read_lines(path) -> tuple[str | None, str | None]:
    """steps-file을 줄 텍스트로. 실패하면 `(None, 사유)`. 파일은 복사·삭제하지 않는다."""
    p = Path(path)
    try:
        if p.stat().st_size > MAX_FILE_BYTES:
            return None, "1 MiB 초과"
        text = _decode(p.read_bytes())
        if "\x00" in text:
            return None, "텍스트 파일이 아님"
        if p.suffix.lower() in (".csv", ".tsv"):
            delim = "\t" if p.suffix.lower() == ".tsv" else ","
            rows = csv.reader(io.StringIO(text, newline=""), delimiter=delim)
            return "\n".join(" | ".join(c.strip() for c in row if c.strip()) for row in rows), None
        return text, None
    except UnicodeDecodeError:
        return None, "인코딩을 알 수 없음"
    except csv.Error as exc:
        return None, f"CSV 오류: {exc}"
    except OSError as exc:
        return None, exc.strerror or type(exc).__name__


def read_steps_file(path, patterns: Iterable[str] | None) -> tuple[str | None, str | None]:
    """`(실패 스텝 원문 | None, 경고 | None)`. 읽지 못하면 `(None, "steps-file을 읽지 못했다(<사유>) — …")`."""
    text, why = _read_lines(path)
    if text is None:
        return None, f"steps-file을 읽지 못했다({why}) — 실패 스텝 없이 진행"
    step, warns = from_text(text, patterns)
    return step, (warns[0] if warns else None)


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


def resolve(cli, auto, steps_file, patterns, masker: Callable[[str], str]):
    """우선순위 cli > auto(필드 > 설명 > 시험 절차) > steps_file. `({text, source} | None, warnings)`.

    `auto`는 `{text, source}`(이미 마스킹) 또는 None. 모든 값은 마스킹 후 정규화한다."""
    warnings: list[str] = []
    if cli and str(cli).strip():
        t = normalize(masker(str(cli)))
        if t:
            return {"text": t, "source": "cli"}, warnings
    if auto and auto.get("text"):
        return {"text": normalize(masker(str(auto["text"]))), "source": auto.get("source") or "field"}, warnings
    if steps_file:
        step, warn = read_steps_file(steps_file, patterns)
        if warn:
            warnings.append(warn)
        if step:
            t = normalize(masker(step))
            if t:
                return {"text": t, "source": "steps_file"}, warnings
    return None, warnings
