"""bugreport(zip·txt)에서 logcat 섹션과 빌드 정보를 꺼낸다 (parse_logcat.py extract-bugreport의 구현).

Android 전용 형식(dumpstate 헤더·섹션 문자열)이라 `platforms/android/`에 둔다 (RF-3).
섹션 헤더 형식은 추정이다(`DEFAULT_BUFFER` 주석, S21).
오류는 `BugreportError`로 올리고, CLI 래퍼(`parse_logcat.py`)가 사용 오류(종료 코드 2)로 바꾼다.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import logcat


class BugreportError(Exception):
    pass


# bugreport 섹션 헤더 기본값. 사내 값은 `platform.bugreport`로 덮어쓴다 (`platforms.load()`).
# 예: "------ RADIO LOG (logcat -b radio -v threadtime -d *:v) ------"
SECTION_RE = re.compile(r"^------ (?P<title>.+?) \((?P<cmd>logcat\b[^)]*)\) ------\s*$")
SECTION_BOUNDARY_RE = re.compile(r"^------ .* ------\s*$")
BUFFER_RE = re.compile(r"-b\s+(?P<buf>[a-z]+)")
LAST_RE = re.compile(r"\s-L\b")  # 이전 부팅 logcat(`-b`보다 먼저 판별) — 기본 wanted_buffers에서는 skip, `last`를 넣으면 추출
BUILD_RE = re.compile(r"^Build:\s*(?P<v>.+?)\s*$")
FINGERPRINT_RE = re.compile(r"^Build fingerprint:\s*'?(?P<v>[^']+?)'?\s*$")
DUMPSTATE_RE = re.compile(r"^== dumpstate:\s*(?P<v>.+?)\s*$")
WANTED_BUFFERS = ("system", "radio", "main")
# `-b` 없는 logcat 섹션은 logcat 기본 버퍼(main+system+crash)다 — 이 이름으로 꺼낸다.
# 헤더 형식은 AOSP dumpstate 기억 기준의 추정이다 — TODO(SITE:S21) 사내 bugreport로 확인.
DEFAULT_BUFFER = "main"


@dataclass(frozen=True)
class BugreportRules:
    """섹션 헤더 규칙. `section_re`는 이름 그룹 `cmd`(logcat 명령줄)를 가진다."""

    section_re: re.Pattern = SECTION_RE
    boundary_re: re.Pattern = SECTION_BOUNDARY_RE
    wanted_buffers: tuple[str, ...] = WANTED_BUFFERS
    default_buffer: str = DEFAULT_BUFFER


DEFAULT_RULES = BugreportRules()


def open_bugreport(path: Path) -> tuple[io.TextIOBase, list]:
    if path.suffix.lower() == ".zip" or zipfile.is_zipfile(path):
        zf = zipfile.ZipFile(path)
        members = [
            info for info in zf.infolist()
            if info.filename.lower().endswith(".txt")
            and Path(info.filename).name.lower().startswith("bugreport")
        ]
        if not members:
            zf.close()
            raise BugreportError(f"{path.name}: bugreport 본문(bugreport-*.txt)이 zip 안에 없습니다.")
        member = max(members, key=lambda i: i.file_size)
        return io.TextIOWrapper(zf.open(member), encoding="utf-8", errors="replace"), [zf]
    return logcat.open_log(path), []


def looks_like_bugreport(path: Path) -> bool:
    if path.suffix.lower() == ".zip":
        return True
    try:
        with logcat.open_log(path) as fh:
            head = [fh.readline() for _ in range(5)]
    except OSError:
        return False
    return any(line.startswith("== dumpstate") for line in head)


def extract(src: Path, out_dir: Path, rules: BugreportRules | None = None) -> dict:
    rules = rules or DEFAULT_RULES
    if not src.is_file():
        raise BugreportError(f"bugreport 파일이 없습니다: {src}")
    out_dir.mkdir(parents=True, exist_ok=True)

    build = {"build": None, "fingerprint": None}
    dumpstate_at = None
    skipped: list[str] = []
    writers: dict[str, io.TextIOBase] = {}
    counts: dict[str, int] = {}
    current = None
    in_header = True
    stream, closers = open_bugreport(src)
    try:
        for raw in stream:
            line = raw.rstrip("\r\n")
            if rules.boundary_re.match(line):
                in_header = False
                current = None
                hit = rules.section_re.match(line)
                if hit:
                    cmd = hit.group("cmd")
                    buf = BUFFER_RE.search(cmd)
                    name = "last" if LAST_RE.search(cmd) else buf.group("buf") if buf else rules.default_buffer
                    if name in rules.wanted_buffers:
                        current = name
                        if current not in writers:
                            writers[current] = (out_dir / f"logcat-{current}.txt").open(
                                "w", encoding="utf-8", newline="\n"
                            )
                            counts[current] = 0
                    else:
                        skipped.append(f"{hit.groupdict().get('title') or line.strip('- ')}({name})")
                continue
            if in_header:
                hit = DUMPSTATE_RE.match(line)
                if hit and dumpstate_at is None:
                    dumpstate_at = hit.group("v")
                hit = BUILD_RE.match(line)
                if hit and build["build"] is None:
                    build["build"] = hit.group("v")
                hit = FINGERPRINT_RE.match(line)
                if hit and build["fingerprint"] is None:
                    build["fingerprint"] = hit.group("v")
                continue
            if current is not None:
                writers[current].write(line + "\n")
                counts[current] += 1
    finally:
        stream.close()
        for closer in closers:
            closer.close()
        for writer in writers.values():
            writer.close()

    if not writers:
        names = "/".join(rules.wanted_buffers)
        raise BugreportError(
            f"{src.name}: logcat 섹션({names})을 찾지 못했습니다. "
            "섹션 헤더 형식이 다를 수 있습니다 (S21)."
        )
    warnings = []
    if build["fingerprint"] is None:
        warnings.append({"code": "no-fingerprint", "message": "헤더에 Build fingerprint가 없습니다."})
    if skipped:
        warnings.append({"code": "skipped-logcat-sections",
                         "message": "꺼내지 않은 logcat 섹션: " + ", ".join(skipped)})
    build_json = out_dir / "build.json"
    build_json.write_text(
        json.dumps({**build, "dumpstate_at": dumpstate_at, "source": src.name}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "files": [
            {"buffer": name, "path": str(out_dir / f"logcat-{name}.txt"), "lines": counts[name]}
            for name in rules.wanted_buffers
            if name in writers
        ],
        "build_json": str(build_json),
        "build": build,
        "warnings": warnings,
    }
