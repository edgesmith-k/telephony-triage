"""로그 파일 형식으로 플랫폼 고르기 (17-platforms §11, K18). 레지스트리 수준 — 플랫폼 이름을 모른다.

`sniff(paths, names)`는 켠 플랫폼(`names`)마다 그 SPEC의 판별만 쓴다:
- 묶음 입력: `spec.capture.looks_like(path)`가 참이면 그 플랫폼(zip은 줄을 읽지 않는다).
- 그 밖: `common.logtime.open_log`로 비지 않은 줄 앞 `SAMPLE_LINES`줄·`SAMPLE_BYTES`까지(줄 하나도 그 상한까지만) 읽어 `spec.log.raw_line(줄)` 개수를 센다.
  `hits >= max(1, min(MIN_HITS, 표본)) and hits / 표본 >= MIN_RATIO`면 그 파일이 그 플랫폼에 맞는다.
  상수(설정 아님): 형식 판별은 guard 규칙 10과 같은 `raw_line`이다 — 사내 형식이 다르면 `raw_line`을 고친다(S24).

결과 `{"files": [{"index": i, "match": [이름…]}], "platforms": [...], "unknown": N}`. `platforms`는 맞은 파일이 모두 같은
한 플랫폼이면 `[p]`, 파일끼리 다르거나 한 파일이 둘 이상에 맞으면 여러 개(모호), 맞은 파일이 없으면 `[]`. 형식을 모르는 파일
(읽기 오류 포함)은 `unknown`으로만 센다. 원문 줄은 결과에 담지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from common.logtime import open_log

from . import get

SAMPLE_LINES = 200
SAMPLE_BYTES = 256 * 1024
MIN_HITS = 3
MIN_RATIO = 0.5


def _sample(path: Path) -> list[str]:
    lines, size = [], 0
    with open_log(path) as fh:
        while True:
            raw = fh.readline(SAMPLE_BYTES)    # 줄 하나도 상한까지만 — 개행 없는 큰 파일(바이너리·pcap)을 통째로 읽지 않는다
            if not raw:
                break
            size += len(raw)
            line = raw.rstrip("\r\n")
            if line.strip():
                lines.append(line)
            if len(lines) >= SAMPLE_LINES or size >= SAMPLE_BYTES:
                break
    return lines


def file_match(path: Path, names: list[str]) -> list[str]:
    """한 파일이 맞는 플랫폼(`names` 순서). 읽지 못하면 빈 목록."""
    path = Path(path)
    specs = [(n, get(n)) for n in names]
    bundle = [n for n, spec in specs if spec.capture is not None and _safe(spec.capture.looks_like, path)]
    if bundle:
        return bundle
    try:
        lines = _sample(path)
    except (OSError, UnicodeError):
        return []
    if not lines:
        return []
    need = max(1, min(MIN_HITS, len(lines)))
    out = []
    for name, spec in specs:
        hits = sum(1 for line in lines if _safe(spec.log.raw_line, line))
        if hits >= need and hits / len(lines) >= MIN_RATIO:
            out.append(name)
    return out


def _safe(fn, value) -> bool:
    try:
        return bool(fn(value))
    except Exception:  # noqa: BLE001 — 판별 예외는 "맞지 않음"(형식 미확인)으로 센다
        return False


def sniff(paths, names: list[str]) -> dict:
    files = [{"index": i, "match": file_match(Path(p), names)} for i, p in enumerate(paths)]
    seen: list[str] = []
    for f in files:
        for name in f["match"]:
            if name not in seen:
                seen.append(name)
    order = [n for n in names if n in seen]
    return {"files": files, "platforms": order, "unknown": sum(1 for f in files if not f["match"])}
