#!/usr/bin/env python3
"""사외/사내 경계 검사 (ARCHITECTURE_REVIEW_2026-10.md RF-2, 15-local-draft.md §15.6).

사람의 주의 대신 도구로 경계를 지킨다. 1차 장치는 `SITE_PATHS` 허용 목록이고,
아래 패턴 검사는 보조다. 검사 대상은 `SITE_PATHS`·`.git`·무시 파일을 뺀 파일이다
(git 레포면 `git ls-files -co --exclude-standard`, 아니면 디렉토리 전체).

규칙
    pattern:<id>   사내 표식 패턴 — 비밀 키, 토큰, 공인 IP, 15자리 숫자(IMEI·IMSI),
                   허용 목록 밖 이메일·URL 호스트. 사내는 `docs/site/boundary-patterns.txt`
                   (SITE_PATHS)에 실제 회사·서버·팀 이름 패턴을 더한다.
    site-import    `plugin/scripts/**`가 SITE_PATHS 모듈(`parser_backends.site`,
                   `adapters.site_*`)을 정적으로 import함. 사내 모듈은 동적 로드만 쓴다.
    fixture-origin `tests/` 아래 로그 fixture에 합성 표시가 없음. 이슈 DB fixture는 짝
                   `.expect.yaml`에 `origin: synthetic`, 그 밖의 로그는 같은 디렉토리
                   README.md(또는 상위 README)나 `tests/mocks/log_fixtures.yaml`에 이름이 있어야 한다.
    site-path      (`--mode external`만) SITE_PATHS 경로에 파일이 있음.

예외는 `tools/boundary-allow.txt`(사외)와 `docs/site/boundary-allow.txt`(사내)에
`<규칙> <경로 glob> [<맞은 문자열 정규식>]` 한 줄씩 둔다.

CLI:
    python3 tools/check_boundary.py [--root <레포>] [--mode external|site] [--json]

종료 코드 (contracts.md §종료 코드)
    0  위반 없음
    1  위반 있음 (커밋·반입 차단)
    2  사용 오류·환경 오류
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_draft import ALWAYS_SKIP, is_site_path  # noqa: E402

OK, VIOLATION, USAGE = 0, 1, 2

SITE_PATHS_FILE = "SITE_PATHS"
SITE_PATTERNS_FILE = "docs/site/boundary-patterns.txt"
ALLOW_FILES = ("tools/boundary-allow.txt", "docs/site/boundary-allow.txt")
SCRIPTS_ROOT = "plugin/scripts"
LOG_REGISTRY = "tests/mocks/log_fixtures.yaml"

# 문서·예시용으로 쓰는 공개 도메인과 예약 도메인.
PUBLIC_HOSTS = (
    "github.com", "raw.githubusercontent.com", "docs.github.com",
    "anthropic.com", "claude.com", "claude.ai",
    "python.org", "pypi.org", "json-schema.org", "yaml.org",
    "source.android.com", "developer.android.com", "android.googlesource.com", "cs.android.com",
    "3gppnetwork.org",  # IMS 표준 도메인 (TS 23.003)
    "semver.org", "keepachangelog.com", "spdx.org", "w3.org",
)
RESERVED_SUFFIXES = (".invalid", ".example", ".test", ".localhost", "example.com", "example.org", "example.net")
SAFE_IPS = {"0.0.0.0", "127.0.0.1", "255.255.255.255"}
DOC_NETS = ("192.0.2.", "198.51.100.", "203.0.113.", "10.", "192.168.", "127.")

TEXT_LIMIT = 2 * 1024 * 1024


@dataclass
class Finding:
    rule: str
    path: str
    line: int
    text: str
    detail: str = ""


def _host_ok(host: str) -> bool:
    host = host.lower().rstrip(".")
    if host in ("localhost",) or host.startswith("mock-") or ".mock-" in host:
        return True
    if host.endswith(RESERVED_SUFFIXES):
        return True
    return any(host == h or host.endswith("." + h) for h in PUBLIC_HOSTS)


def _ip_ok(ip: str) -> bool:
    parts = ip.split(".")
    if any(int(p) > 255 for p in parts):
        return True  # 버전 문자열 등, IP가 아니다
    return ip in SAFE_IPS or ip.startswith(DOC_NETS)


# (id, 정규식, 맞은 문자열이 괜찮은지 판정 — None이면 언제나 위반)
DEFAULT_PATTERNS: list[tuple[str, re.Pattern, object]] = [
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"), None),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), None),
    ("secret-assign", re.compile(
        r"(?i)\b(?:token|secret|passwd|password|api[_-]?key)\s*[:=]\s*['\"]?([A-Za-z0-9_\-+/]{20,})"), None),
    ("ip-address", re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.])"),
     lambda m: _ip_ok(m.group(1))),
    ("long-number", re.compile(r"(?<![\w.])\d{15}(?![\w.])"), None),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)\b"),
     lambda m: _host_ok(m.group(1))),
    ("url-host", re.compile(r"\b(?:https?|ssh|git)://(?:[^@/\s]+@)?([A-Za-z0-9.-]+)"),
     lambda m: _host_ok(m.group(1)) or "<" in m.group(0)),
]


def _read_lines(path: Path | None) -> list[str]:
    if path is None or not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def load_site_paths(root: Path) -> list[str]:
    return _read_lines(root / SITE_PATHS_FILE)


def _rule_file(root: Path, files: dict[str, Path], rel: str) -> Path:
    """규칙 파일 위치. 검사 목록(반입 미리보기면 staging 사본)에 있으면 그것, 없으면 `root` 것."""
    return files.get(rel) or root / rel


def load_patterns(root: Path, files: dict[str, Path]) -> list[tuple[str, re.Pattern, object]]:
    patterns = list(DEFAULT_PATTERNS)
    for i, raw in enumerate(_read_lines(_rule_file(root, files, SITE_PATTERNS_FILE)), 1):
        name, sep, expr = raw.partition(" ")
        if not sep or not name.startswith("id:"):
            name, expr = f"site-{i}", raw
        else:
            name = name[3:]
        try:
            patterns.append((name, re.compile(expr.strip()), None))
        except re.error as exc:
            raise ValueError(f"{SITE_PATTERNS_FILE}:{i} 정규식 오류: {exc}") from exc
    return patterns


def load_allow(root: Path, files: dict[str, Path]) -> list[tuple[str, str, re.Pattern | None]]:
    out = []
    for rel in ALLOW_FILES:
        for raw in _read_lines(_rule_file(root, files, rel)):
            parts = raw.split(None, 2)
            if len(parts) < 2:
                raise ValueError(f"{rel}: '<규칙> <경로 glob> [<정규식>]' 형식이 아닙니다: {raw}")
            out.append((parts[0], parts[1], re.compile(parts[2]) if len(parts) == 3 else None))
    return out


def _allowed(finding: Finding, allow) -> bool:
    for rule, glob, expr in allow:
        if not fnmatch.fnmatch(finding.rule, rule):
            continue
        if not fnmatch.fnmatch(finding.path, glob):
            continue
        if expr is None or expr.search(finding.text):
            return True
    return False


def list_files(root: Path, site_patterns: list[str]) -> dict[str, Path]:
    """검사 대상 {상대경로: 절대경로}. SITE_PATHS·무시 파일 제외."""
    rels: list[str]
    if (root / ".git").exists():
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
            capture_output=True, check=True, timeout=60,
        ).stdout.decode("utf-8")
        rels = [r for r in out.split("\0") if r]
    else:
        rels = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    files = {}
    for rel in sorted(rels):
        if any(part in ALWAYS_SKIP for part in rel.split("/")):
            continue
        if is_site_path(rel, site_patterns):
            continue
        path = root / rel
        if path.is_file():
            files[rel] = path
    return files


def _text(path: Path) -> str | None:
    data = path.read_bytes()[:TEXT_LIMIT]
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")


def check_patterns(files: dict[str, Path], patterns) -> list[Finding]:
    findings = []
    for rel, path in files.items():
        if rel in ALLOW_FILES:
            continue
        text = _text(path)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, regex, ok in patterns:
                for match in regex.finditer(line):
                    if ok is not None and ok(match):
                        continue
                    findings.append(Finding(f"pattern:{name}", rel, lineno, match.group(0)))
    return findings


def _module_targets(module: str) -> list[str]:
    base = f"{SCRIPTS_ROOT}/{module.replace('.', '/')}"
    return [base + "/", base + ".py", base + "/__init__.py"]


def check_site_imports(files: dict[str, Path], site_patterns: list[str]) -> list[Finding]:
    findings = []
    for rel, path in files.items():
        if not (rel.startswith(SCRIPTS_ROOT + "/") and rel.endswith(".py")):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, UnicodeDecodeError) as exc:
            findings.append(Finding("site-import", rel, getattr(exc, "lineno", 0) or 0, "", f"파싱 실패: {exc}"))
            continue
        inner = rel[len(SCRIPTS_ROOT) + 1:]
        package = inner.rsplit("/", 1)[0].replace("/", ".") if "/" in inner else ""
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parts = package.split(".") if package else []
                    parts = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
                    base = ".".join([*parts, base] if base else parts)
                modules = [base] + [f"{base}.{alias.name}" if base else alias.name for alias in node.names]
            for module in modules:
                if module and any(is_site_path(t, site_patterns) for t in _module_targets(module)):
                    findings.append(Finding("site-import", rel, node.lineno, module,
                                            "SITE_PATHS 모듈은 동적 로드만 쓴다"))
                    break
    return findings


def check_fixture_origin(root: Path, files: dict[str, Path]) -> list[Finding]:
    findings = []
    registry = (root / LOG_REGISTRY).read_text(encoding="utf-8") if (root / LOG_REGISTRY).is_file() else ""
    readmes: dict[str, str] = {}
    for rel, path in files.items():
        if not (rel.startswith("tests/") and rel.endswith(".log")):
            continue
        parent, name = rel.rsplit("/", 1)
        stem = name[: -len(".log")]
        if parent.endswith("/fixtures") and "/issue-db-" in "/" + parent:
            expect = files.get(f"{parent}/{stem}.expect.yaml")
            text = expect.read_text(encoding="utf-8") if expect else ""
            if not re.search(r"(?m)^origin:\s*synthetic\s*$", text):
                findings.append(Finding("fixture-origin", rel, 0, name,
                                        "짝 .expect.yaml에 origin: synthetic이 없다"))
            continue
        if parent not in readmes:
            # 같은 디렉토리나 그 위(`tests/`까지)의 README.md
            texts, cur = [], parent
            while cur.startswith("tests"):
                readme = files.get(f"{cur}/README.md")
                if readme:
                    texts.append(readme.read_text(encoding="utf-8"))
                cur = cur.rsplit("/", 1)[0] if "/" in cur else ""
            readmes[parent] = "\n".join(texts)
        if name in readmes[parent] or (rel.startswith("tests/fixtures/logs/") and re.search(
                rf"\bname:\s*['\"]?{re.escape(stem)}['\"]?\s*[,}}\n]", registry)):
            continue
        findings.append(Finding("fixture-origin", rel, 0, name,
                                "합성 로그 목록(README.md·log_fixtures.yaml)에 이름이 없다"))
    return findings


def check_site_paths_absent(root: Path, site_patterns: list[str]) -> list[Finding]:
    findings = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if any(part in ALWAYS_SKIP for part in rel.split("/")) or not path.is_file():
            continue
        if is_site_path(rel, site_patterns):
            findings.append(Finding("site-path", rel, 0, "", "사외 레포에 사내 전용 경로가 있다"))
    return findings


def scan(root: Path, mode: str, files: dict[str, Path] | None = None) -> list[Finding]:
    """`files`를 주면 그 목록(반입 staging 미리보기 등)만 본다. 규칙 파일은 `root`에서 읽는다."""
    site_patterns = load_site_paths(root)
    if files is None:
        files = list_files(root, site_patterns)
    patterns = load_patterns(root, files)
    allow = load_allow(root, files)
    findings = (
        check_patterns(files, patterns)
        + check_site_imports(files, site_patterns)
        + check_fixture_origin(root, files)
    )
    if mode == "external":
        findings += check_site_paths_absent(root, site_patterns)
    return [f for f in findings if not _allowed(f, allow)]


def format_findings(findings: list[Finding]) -> str:
    lines = []
    for f in findings:
        where = f"{f.path}:{f.line}" if f.line else f.path
        detail = f" — {f.detail}" if f.detail else ""
        lines.append(f"  {f.rule:<24} {where}  {f.text[:80]}{detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_boundary.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="검사할 레포 (기본: 현재 디렉토리)")
    parser.add_argument("--mode", choices=("external", "site"), default="external",
                        help="external: 사외 레포(SITE_PATHS 경로가 비어 있어야 함) / site: 사내 레포")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"레포 경로가 없습니다: {root}", file=sys.stderr)
        return USAGE
    try:
        findings = scan(root, args.mode)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return USAGE

    if args.json:
        print(json.dumps({"mode": args.mode, "violations": [asdict(f) for f in findings]},
                         ensure_ascii=False, indent=2))
    elif findings:
        print(f"경계 위반 {len(findings)}건 ({args.mode}):", file=sys.stderr)
        print(format_findings(findings), file=sys.stderr)
        print("예외가 맞으면 tools/boundary-allow.txt(사내는 docs/site/boundary-allow.txt)에 적는다.",
              file=sys.stderr)
    else:
        print(f"경계 위반 없음 ({args.mode})")
    return VIOLATION if findings else OK


if __name__ == "__main__":
    raise SystemExit(main())
