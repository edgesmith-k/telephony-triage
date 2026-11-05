#!/usr/bin/env python3
"""fixture_residual.py — fixture·case 파일의 남은 식별자 점검 (B2 §4.8, B2-12, 결정 기록 11/05).

    python3 tools/fixture_residual.py <file|dir>... [--against <원본 로그 dir>] [--json]

- (a) 줄마다 로그 마스커의 `masking.residual()`(M1~M11 포함). 걸리면 `file:line kind`.
- (b) `--against`: 원본 로그에서 아직 가리지 않는 값의 거부 목록을 **메모리에서만** 만들고, fixture에 그 값이 있으면
  `file:line kind (원본 줄 n)`. 종류: APN 값, PLMN(MCC-MNC), AID 꼬리, base64(M2b 모양), 제품·모뎀·부품 코드와 빌드 ID,
  빌드 시각, 사업자 이름, 벤더 경로 장치 노드, syslog 호스트 칸 값.
- 디렉토리를 주면 그 아래 `.log`·`.txt`·`.json`과 case `files/*.md`를 본다(문서·`modules.yaml`의 정규식 글은 보지 않는다).
- syslog 호스트 칸이 `dut`·`localhost`·`(none)`·`host<n>`이 아니면 `host`로 보인다(원본 없이도).
- 모양 규칙 `SHAPE_RX`(덤프의 `MobileCountryCode`·`MobileNetworkCode` 2~3자리 값)는 원본 없이도 `plmn`으로 보인다.
- oFono `dump_dmsg_w_re()` 덤프의 이어진 조각(시각 뺀 앞머리가 같고 1초 안, 사이 줄 건너뜀)은 이은 글에서도 거부 목록·모양 규칙을 본다
  (키·값이 두 줄에 갈린 경우, 걸친 줄마다 지적).

출력은 파일·줄·종류(와 원본 줄 번호)뿐이며 맞은 글자는 내지 않는다. 마스킹한 실제 발췌는 허용한다(LM의 원문 금지
규칙은 쓰지 않는다). 종료 코드: 0 깨끗함, 1 지적 있음, 2 사용 오류.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import masking

TEXT_SUFFIXES = (".log", ".txt", ".json")          # 디렉토리를 줄 때 보는 파일(로그·이벤트), 그리고 case `files/*.md`
HOST_HEAD = re.compile(r"^(?:" + "|".join(masking._M11_STAMPS) + r") (?P<v>\S+) ")
HOST_OK = re.compile(r"dut|localhost|\(none\)|host\d+")
GENERIC = frozenset(("internet", "ims", "default", "null", "none", "true", "false", "unknown", "mms", "supl", "xcap",
                     "emergency", "fota", "hipri", "dun", "ia", "cbs"))
DEV_GENERIC = frozenset(("null", "zero", "random", "urandom", "tty", "console", "ptmx", "kmsg", "ashmem", "binder",
                         "hwbinder", "vndbinder", "pts", "shm", "socket", "full", "fuse", "uinput", "input", "log",
                         "mem", "cpuset", "stune", "blkio", "memcg", "block", "char", "bus", "properties"))
DENY_RX = (
    ("apn", re.compile(r"(?i)\bapn\s*[=:]\s*\"?(?P<v>[A-Za-z0-9][A-Za-z0-9._-]{2,62})")),
    ("apn", re.compile(r"(?i)\bapn (?P<v>[a-z0-9-]+(?:\.[a-z0-9-]+)+)")),            # 공백 뒤는 도메인 모양만
    ("plmn", re.compile(r"(?i)\b(?:plmn|mccmnc|mcc_mnc|numeric|operatorNumeric)\s*[=:]\s*\"?(?P<v>\d{5,6})\b")),
    ("plmn", re.compile(r"(?i)\bmnc(?P<v>\d{2,3}\.mcc\d{3})\b")),
    ("aid", re.compile(r"(?i)(?<![0-9A-F])(?P<v>A000000[0-9A-F]{10,})")),
    ("build_time", re.compile(r"(?i)(?:build|date|time)\D{0,12}(?P<v>\d{8}[._-]?\d{6})")),
    ("carrier", re.compile(r"(?i)(?:mOperatorAlphaLong|mOperatorAlphaShort|spn|carrier)\s*[=:]\s*\"?(?P<v>[^\s\",;}{)]{3,40})")),
    ("carrier", re.compile(r"\"(?:ServiceProviderName|Name)\",\s*variant\(\"(?P<v>[^\"]{3,40})\"")),
    ("device_node", re.compile(r"/dev/(?P<v>[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)")),
)
# 모양 규칙(값 거부 목록은 4자 이상만 넣으므로 2~3자리 MCC·MNC는 모양으로 본다, C1+D 보정 §1.2 ②). `make_excerpt`가
# `<PLMN#n>`으로 바꾸고, `check`는 `--against` 없이도 가리지 않은 값을 지적한다.
SHAPE_RX = (
    ("plmn", re.compile(r"\"Mobile(?:Country|Network)Code\",\s*variant\(\"(?P<v>\d{2,3})\"")),
)
# oFono `dump_dmsg_w_re()` 덤프는 한 메시지가 여러 줄에 잘린다(같은 ident·pid, 시각은 ms가 바뀌고 사이에 다른 줄이 낀다). 줄 단위 규칙은 키와 값이
# 갈린 조각을 놓치므로 이어진 조각을 이은 글에서 다시 본다(§1.2 ③).
DUMP_MARK = "dump_dmsg_w_re() "
_IDENT = re.compile(r"[A-Za-z]*[a-z][A-Z]\w*|[a-z]+")    # CamelCase 식별자·소문자 낱말(키 이름이지 값이 아니다)


def _value_ok(kind: str, value: str) -> bool:
    """거부 목록에 넣을 값인가: 사업자 이름은 키 이름·식별자 모양(`SubId`·`value`)과 `=`·`:`가 든 조각을 뺀다."""
    if kind == "carrier":
        return not (re.search(r"[=:]", value) or _IDENT.fullmatch(value))
    return True


SPAN_KINDS = {"PRODUCT": "product", "BUILD": "build", "HASH": "build", "B64": "base64"}


_DUMP_IDENT = re.compile(r"\S+\[\d+\]:")                 # ident[pid]: (앞머리에서 시각 뒤)
_DUMP_TIME = re.compile(r"(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)")
DUMP_GAP = 1.0                                         # 같은 메시지 조각으로 볼 시각 차(초) 상한(미만)


def dump_groups(lines: list[str]) -> list[list[tuple[int, int]]]:
    """이어진 `dump_dmsg_w_re()` 조각 묶음 `[[(줄 순번, 조각 시작 열), ...], ...]`(두 줄 이상).
    시각을 뺀 앞머리(ident[pid] 이후)가 같고 앞 조각과 시각 차가 `DUMP_GAP` 미만이면 잇는다. 사이의 덤프 아닌 줄·다른
    앞머리 줄은 건너뛰고(실제 로그는 조각 사이에 다른 줄이 끼고 ms가 바뀐다), 순번은 원래 줄 순번이다. 시각을 못 읽으면
    앞머리 전체가 같은 다음 덤프 줄을 잇는다."""
    groups, open_ = [], {}                             # 앞머리 키 -> (묶음, 마지막 시각)
    for i, line in enumerate(lines):
        at = line.find(DUMP_MARK)
        if at < 0:
            continue
        col = at + len(DUMP_MARK)
        head = line[:at]
        m, t = _DUMP_IDENT.search(head), _DUMP_TIME.search(head)
        if m and t:
            key, sec = head[m.start():], int(t[1]) * 3600 + int(t[2]) * 60 + float(t[3])
        else:
            key, sec = ("", head), None
            for k in [k for k in open_ if isinstance(k, tuple)]:
                if k != key:
                    groups.append(open_.pop(k)[0])
        prev = open_.get(key)
        if prev and (sec is None or 0 <= sec - prev[1] < DUMP_GAP):
            prev[0].append((i, col))
            open_[key] = (prev[0], sec)
            continue
        if prev:
            groups.append(prev[0])
        open_[key] = ([(i, col)], sec)
    groups += [g for g, _s in open_.values()]
    return sorted((g for g in groups if len(g) > 1), key=lambda g: g[0][0])


def cross_hits(lines: list[str], rules) -> list[tuple[str, str, list[tuple[int, int, int]]]]:
    """조각을 이은 글에서 `rules`(`[(종류, 정규식)]`)가 맞고 그 맞은 글이 **두 줄 이상에 걸친** 것만(키·값이 갈림, 값이 갈림)
    `[(종류, 값, [(줄 순번, 시작 열, 끝 열), ...])]`. 값은 이름 그룹 `v`(없으면 맞은 글 전체), 조각은 값이 든 줄만이다.
    한 줄 안에서 끝나는 맞음은 줄 단위 규칙이 이미 본다."""
    out = []
    for group in dump_groups(lines):
        text, starts = "", []
        for i, col in group:
            starts.append((len(text), i, col))
            text += lines[i][col:]
        bounds = [off for off, _i, _c in starts[1:]]
        for kind, rx in rules:
            for m in rx.finditer(text):
                if not any(m.start() < x < m.end() for x in bounds):
                    continue
                a, b = m.span("v") if "v" in rx.groupindex else m.span()
                pieces = []
                for k, (off, i, col) in enumerate(starts):
                    end = starts[k + 1][0] if k + 1 < len(starts) else len(text)
                    lo, hi = max(a, off), min(b, end)
                    if lo < hi:
                        pieces.append((i, col + lo - off, col + hi - off))
                if pieces:
                    out.append((kind, text[a:b], pieces))
    return out


def _files(args: list[str]) -> list[Path]:
    out = []
    for name in args:
        p = Path(name)
        if p.is_dir():
            out += [f for f in sorted(p.rglob("*")) if f.is_file()
                    and (f.suffix in TEXT_SUFFIXES or (f.suffix == ".md" and f.parent.name == "files"))]
        elif p.is_file():
            out.append(p)
        else:
            raise FileNotFoundError(name)
    return out


def _lines(path: Path) -> list[str]:
    return [ln.rstrip("\r") for ln in path.read_bytes().decode("utf-8", "replace").split("\n")]


def deny_list(raw_dir: Path) -> dict[str, tuple[str, str, int]]:
    """원본 로그의 거부 값 `{값: (종류, 원본 파일 이름, 줄)}` (처음 나온 곳). 메모리에만 있다."""
    deny: dict[str, tuple[str, str, int]] = {}
    masker = masking.new_masker(log_lines=True)

    def add(value: str, kind: str, src: str, no: int) -> None:
        value = value.strip()
        if len(value) < 4 or value.lower() in GENERIC or value in deny:
            return
        deny[value] = (kind, src, no)

    for path in _files([str(raw_dir)]):
        lines = _lines(path)
        for kind, value, pieces in cross_hits(lines, DENY_RX):     # 키·값이 갈린 덤프 조각(§1.2 ③)
            if not (kind == "device_node" and value.split("/")[0] in DEV_GENERIC) and _value_ok(kind, value):
                add(("/dev/" + value) if kind == "device_node" else value, kind, path.name, pieces[0][0] + 1)
        for no, line in enumerate(lines, 1):
            m = HOST_HEAD.match(line)
            if m and not HOST_OK.fullmatch(m.group("v")):
                add(m.group("v"), "host", path.name, no)
            for kind, rx in DENY_RX:
                for hit in rx.finditer(line):
                    v = hit.group("v")
                    if (kind == "device_node" and v.split("/")[0] in DEV_GENERIC) or not _value_ok(kind, v):
                        continue
                    add(("/dev/" + v) if kind == "device_node" else v, kind, path.name, no)
            for _s, _e, kind, value in masker._spans(line):
                if kind in SPAN_KINDS:
                    add(value, SPAN_KINDS[kind], path.name, no)
    return deny


def _deny_regex(deny: dict) -> re.Pattern | None:
    if not deny:
        return None
    alt = "|".join(re.escape(v) for v in sorted(deny, key=lambda v: (-len(v), v)))
    return re.compile(r"(?<![A-Za-z0-9])(?:" + alt + r")(?![A-Za-z0-9])")


def check(paths: list[Path], deny: dict | None = None) -> list[dict]:
    """지적 `[{file, line, kind, raw_line?}]` (값 없음)."""
    rx = _deny_regex(deny or {})
    found = []
    for path in paths:
        lines = _lines(path)
        rules = list(SHAPE_RX) + ([("deny", rx)] if rx is not None else [])
        for kind, value, pieces in cross_hits(lines, rules):             # 갈린 조각: 걸친 줄마다 한 번
            extra = {"kind": deny[value][0], "raw_line": deny[value][2]} if kind == "deny" else {"kind": kind}
            found += [{"file": str(path), "line": i + 1, **extra} for i in sorted({p[0] for p in pieces})]
        for no, line in enumerate(lines, 1):
            for kind, srx in SHAPE_RX:
                found += [{"file": str(path), "line": no, "kind": kind} for _ in srx.finditer(line)]
            for kind, n in masking.residual(line).items():
                found += [{"file": str(path), "line": no, "kind": kind}] * n
            m = HOST_HEAD.match(line)
            if m and not HOST_OK.fullmatch(m.group("v")) and not (deny and m.group("v") in deny):
                found.append({"file": str(path), "line": no, "kind": "host"})
            if rx is not None:
                for hit in rx.finditer(line):
                    kind, _src, raw_no = deny[hit.group(0)]
                    found.append({"file": str(path), "line": no, "kind": kind, "raw_line": raw_no})
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fixture_residual.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--against", help="원본 로그 디렉토리(거부 목록을 메모리에서 만든다)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        paths = _files(args.paths)
    except FileNotFoundError as exc:
        print(f"파일·디렉토리가 없습니다: {Path(str(exc)).name}", file=sys.stderr)
        return 2
    deny = None
    if args.against:
        raw = Path(args.against)
        if not raw.is_dir():
            print("--against는 디렉토리여야 합니다", file=sys.stderr)
            return 2
        deny = deny_list(raw)
    found = check(paths, deny)
    if args.json:
        print(json.dumps({"checked": len(paths), "findings": found, "deny_values": len(deny or {})}, ensure_ascii=False))
    else:
        for f in found:
            extra = f" (원본 줄 {f['raw_line']})" if "raw_line" in f else ""
            print(f"{f['file']}:{f['line']} {f['kind']}{extra}")
        print(f"파일 {len(paths)}개, 지적 {len(found)}건")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
