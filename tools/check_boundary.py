#!/usr/bin/env python3
"""사외/사내 경계 검사 (ARCHITECTURE_REVIEW_2026-10.md RF-2, 15-local-draft.md §15.6).

사람의 주의 대신 도구로 경계를 지킨다. 1차 장치는 `SITE_PATHS` 허용 목록이고,
아래 패턴 검사는 보조다. 검사 대상은 `SITE_PATHS`·`.git`·무시 파일을 뺀 파일이다
(git 레포면 `git ls-files -co --exclude-standard`, 아니면 `.gitignore`만 적용한 디렉토리 전체).

규칙
    pattern:<id>   사내 표식 패턴 — 비밀 키(PEM·OPENSSH·PGP), 비밀값(GitHub·AWS·Slack·Google·
                   Atlassian·npm/PyPI·LLM API 토큰, JWT, `Authorization` 헤더 값, URL·netrc
                   자격증명, `*token*`·`*secret*`·`*password*`·`*api_key*` 대입 — 자리표시 값
                   `<…>`·`${…}`·`xxxx`·`REDACTED`·`EXAMPLE`은 제외, 대입 값은 숫자 포함 20자
                   이상), 공인 IP, 15자리 숫자(IMEI·IMSI), 허용 목록 밖 이메일·URL 호스트,
                   로그 출처 흔적 문구(`trace-wording`: 발췌·첨부 표시·로그 id·마스커 해시·점검 날짜).
                   비밀값은 출력에서 앞부분만 보인다. 사내는 `docs/site/boundary-patterns.txt`
                   (SITE_PATHS)에 실제 회사·서버·팀 이름 패턴을 더한다(모드와 무관).
    site-import    `plugin/scripts/**`가 SITE_PATHS 모듈(`parser_backends.site`,
                   `adapters.site_*`)을 정적으로 import함. 사내 모듈은 동적 로드만 쓴다.
    fixture-origin `tests/` 아래 로그 fixture에 합성 표시가 없음. 이슈 DB fixture는 짝
                   `.expect.yaml`에 `origin: synthetic`, 그 밖의 로그는 같은 디렉토리
                   README.md(또는 상위 README)나 `tests/mocks/log_fixtures.yaml`에 이름이 있어야 한다.
                   모듈 스킬 템플릿 case 로그(`templates/module-skills/**/evals/<case>/files/*.log`)는
                   합성만: case.yaml `synthetic: true`, `origin:` 키 없음, 1줄 `-- [합성]` (H C1+D R6).
                   형식 전체는 `skillcheck.origin_problems`가 본다.
    dbus-name      oFono 모듈 문서(`templates/module-skills/ofono/**/*.md`, evals 제외), modules.yaml의
                   `platforms.ofono` 블록, `tests/helpers/make_variant_dbs.py`의 `OFONO_*`·`MODULES_*` 문자열
                   상수에 허용 밖 D-Bus 이름(`skillcheck.dbus_allowed`: `org.ofono.*`·`org.freedesktop.DBus.*`·
                   modules.yaml ofono `dbus` 합집합). modules.yaml을 못 읽으면 한 건(닫힘). case 로그·Android
                   템플릿·`tests/fixtures/**`·`docs/**`는 범위 밖.
    site-path      (external 모드만) SITE_PATHS 경로에 파일이 있음.

예외는 `tools/boundary-allow.txt`(사외)와 `docs/site/boundary-allow.txt`(사내)에
`<규칙> <경로 glob> [<맞은 문자열 정규식>]` 한 줄씩 둔다.

CLI:
    python3 tools/check_boundary.py [--root <레포>] [--mode external|site] [--json]

모드 기본은 자동 판별이다: `.local-draft`가 있으면 external, 없고 `.draft-manifest.json`이나
`SITE_PROFILE.md`가 있으면 site(사내 레포), 둘 다 없으면 external.

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
from import_draft import ALWAYS_SKIP, is_site_path, walk  # noqa: E402

OK, VIOLATION, USAGE = 0, 1, 2

SITE_PATHS_FILE = "SITE_PATHS"
SITE_PATTERNS_FILE = "docs/site/boundary-patterns.txt"
ALLOW_FILES = ("tools/boundary-allow.txt", "docs/site/boundary-allow.txt")
SCRIPTS_ROOT = "plugin/scripts"
LOG_REGISTRY = "tests/mocks/log_fixtures.yaml"
SITE_MARKERS = (".draft-manifest.json", "SITE_PROFILE.md")

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


# 문서·테스트의 자리표시 값: <token>, ${GH_TOKEN}, $TOKEN, {{ secrets.X }}, ***, xxxx, REDACTED, …EXAMPLE
_PLACEHOLDER = re.compile(r"(?i)example|sample|dummy|placeholder|redacted|changeme|your|xxxx|fake|[<>${}*]")


def _placeholder(value: str) -> bool:
    """자리표시 값인가 (위 단어·기호, 또는 서로 다른 문자 6개 미만 — `aaaa…`, `0000…`)."""
    return bool(_PLACEHOLDER.search(value)) or len(set(value)) < 6


def _not_secret(value: str) -> bool:
    """`키=값` 문맥의 값이 비밀값이 아닌가. masking.py `_secretish`처럼 숫자가 있어야 비밀값으로 본다."""
    return _placeholder(value) or not (any(c.isdigit() for c in value) and any(c.isalpha() for c in value))


# (id, 정규식, 맞은 문자열이 괜찮은지 판정 — None이면 언제나 위반)
DEFAULT_PATTERNS: list[tuple[str, re.Pattern, object]] = [
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"), None),
    # 값 경계(`\b`·`\w`·`\d`)는 ASCII다(`re.ASCII`): 값에 붙은 한글 조사(`203.0.113.7은`)도 경계로 본다
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b", re.ASCII),
     lambda m: _placeholder(m.group(0))),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", re.ASCII), lambda m: _placeholder(m.group(0))),
    ("slack-token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}", re.ASCII), lambda m: _placeholder(m.group(0))),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}(?![\w-])", re.ASCII), lambda m: _placeholder(m.group(0))),
    ("atlassian-token", re.compile(r"\bATATT[A-Za-z0-9_=-]{40,}", re.ASCII), lambda m: _placeholder(m.group(0))),
    ("package-token", re.compile(r"\b(?:npm_[A-Za-z0-9]{36}|pypi-AgE[A-Za-z0-9_-]{50,})", re.ASCII),
     lambda m: _placeholder(m.group(0))),
    ("llm-api-key", re.compile(
        r"\bsk-ant-[A-Za-z0-9_-]{20,}|\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]*T3BlbkFJ[A-Za-z0-9_-]+", re.ASCII),
     lambda m: _placeholder(m.group(0))),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", re.ASCII),
     lambda m: _placeholder(m.group(0))),
    ("auth-header", re.compile(
        r"(?:(?i:\bauthorization)\s*[:=]\s*['\"]?(?:Bearer|Basic|token)\s+|\bBearer\s+)([A-Za-z0-9._~+/-]{16,}=*)", re.ASCII),
     lambda m: _not_secret(m.group(1))),
    ("url-credential", re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s:/@<>'\"]+:([^\s/@<>'\"]+)@", re.ASCII),
     lambda m: _placeholder(m.group(1))),
    ("netrc", re.compile(r"(?i)\blogin\s+\S+\s+password\s+(\S+)"), lambda m: _placeholder(m.group(1))),
    # 키 이름 앞뒤를 {0,30}으로 묶어 긴 줄에서 제곱 시간이 되지 않게 한다.
    ("secret-assign", re.compile(
        r"(?i)(?<![A-Za-z0-9])[\w.-]{0,30}?"
        r"(?:token|secret|passw(?:or)?d|pwd|api[_-]?key|access[_-]?key|private[_-]?key|credentials?)"
        r"[\w.-]{0,30}?['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_\-+/=]{20,})"),
     lambda m: _not_secret(m.group(1))),
    ("ip-address", re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.])", re.ASCII),
     lambda m: _ip_ok(m.group(1))),
    ("long-number", re.compile(r"(?<![\w.])\d{15}(?![\w.])", re.ASCII), None),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)\b", re.ASCII),
     lambda m: _host_ok(m.group(1))),
    ("url-host", re.compile(r"\b(?:https?|ssh|git)://(?:[^@/\s]+@)?([A-Za-z0-9.-]+)", re.ASCII),
     lambda m: _host_ok(m.group(1)) or "<" in m.group(0)),
    # 로그 출처 흔적 문구(발췌·첨부 표시·로그 id·마스커 해시·점검 날짜)의 재유입. 정규식 글자는 자기 자신에 맞지 않게 쓴다
    # (`\s`·`[-]`·`\[` — 이 파일은 예외 없이 검사를 통과한다). case 로그는 합성뿐이다(`-- [합성]`).
    ("trace-wording", re.compile(
        r"마스킹\s발췌|첨부\s로그|masked[-]excerpt|-- \[마스킹|\bmasker:\s*['\"]?[0-9a-f]{12}\b|\bresidual:\s*['\"]?\d{4}-\d{2}-\d{2}"
        r"|\bO[12]\s+E\d+[a-z]?\b|\bA-E\d+[a-z]?\b|\bE\d+[a-z]?\s+줄\s+\d+-\d+"), None),
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
    """검사 대상 {상대경로: 절대경로}. SITE_PATHS·무시 파일 제외 (반입 목록과 같은 기준)."""
    return walk(root, site_patterns)


def _text(path: Path) -> str | None:
    data = path.read_bytes()[:TEXT_LIMIT]
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")


def check_patterns(files: dict[str, Path], patterns) -> list[Finding]:
    _skillcheck()                                # plugin/scripts를 경로에 넣는다
    from common.masking import fold_ascii        # 패턴이 `re.ASCII`라 마스킹과 같은 규칙으로 접어서 본다(글자 수 같음)

    findings = []
    for rel, path in files.items():
        if rel in ALLOW_FILES:
            continue
        text = _text(path)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            folded = fold_ascii(line)
            for name, regex, ok in patterns:
                # ASCII 아닌 패턴(사내 패턴, 기본 private-key·secret-assign 등)은 원문과 접은 글을 둘 다 본다 — 접은 글만 보면
                # 비ASCII가 든 사내 패턴이, 원문만 보면 전각·NBSP로 쓴 비밀값이 빠진다(재리뷰 P1). 원문을 먼저 보고,
                # 접은 글 match는 이미 알린 자리와 겹치면 뺀다(같은 값을 두 번 알리지 않는다). 접은 글이 먼저면 전각 글자로
                # 이어진 두 값이 한 건으로 합쳐져 allow 한 줄에 둘 다 가려진다.
                texts = (folded,) if regex.flags & re.ASCII or folded == line else (line, folded)
                seen: list[tuple[int, int]] = []
                for match in (m for t in texts for m in regex.finditer(t)):
                    if ok is not None and ok(match):
                        continue
                    if any(match.start() < e and s < match.end() for s, e in seen):
                        continue
                    seen.append(match.span())
                    findings.append(Finding(f"pattern:{name}", rel, lineno, line[match.start():match.end()]))
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
        if rel.startswith("templates/module-skills/") and rel.endswith(".log"):
            # 모듈 스킬 템플릿 case 로그(MODULE_SKILLS_PLAN_IMPL §5.1, H C1+D R6): evals/<case>/files/ 아래,
            # 합성만(synthetic: true + `-- [합성]`, origin 키 없음)
            name = rel.rsplit("/", 1)[1]
            m = re.fullmatch(r"(templates/module-skills/.+/evals/[^/]+)/files/[^/]+\.log", rel)
            case = files.get(f"{m.group(1)}/case.yaml") if m else None
            text = case.read_text(encoding="utf-8") if case else ""
            first = (_text(path) or "").split("\n", 1)[0]
            if not m or not _template_origin_ok(text, first):
                findings.append(Finding("fixture-origin", rel, 0, name,
                                        "모듈 템플릿 로그: evals/<case>/files/ 아래, case.yaml synthetic: true(origin "
                                        "키 없음) + 1줄 '-- [합성]'"))
            continue
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


def _template_origin_ok(case_text: str, first_line: str) -> bool:
    """case.yaml 글(정규식으로만 본다)과 로그 1줄: 합성 표시(`synthetic: true`, `origin:` 없음, `-- [합성]`)."""
    return (bool(re.search(r"(?m)^synthetic:\s*true\s*$", case_text)) and not re.search(r"(?m)^origin:", case_text)
            and first_line.startswith("-- [합성]"))


DBUS_DOCS = re.compile(r"templates/module-skills/ofono/(?!.*/evals/).+\.md")
DBUS_MODULES = "templates/module-skills/modules.yaml"
DBUS_CONSTS = "tests/helpers/make_variant_dbs.py"


def _skillcheck():
    scripts = str(Path(__file__).resolve().parents[1] / SCRIPTS_ROOT)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from common import skillcheck

    return skillcheck


def _ofono_template():
    """D-Bus 이름 규칙은 oFono 고유 자료다(`platforms/ofono/template.py`, 17-platforms §10-3). 이 도구는 핵심이 아니라 플랫폼
    모듈을 바로 불러도 된다(핵심의 금지 검사는 plugin/scripts만 본다)."""
    _skillcheck()
    import importlib

    return importlib.import_module("platforms.ofono.template")


def _ofono_block(text: str) -> list[tuple[int, str]]:
    """modules.yaml의 `platforms.ofono` 블록 줄(번호, 글) — 들여쓰기로 자른다."""
    out, inside, indent = [], False, 0
    for no, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^( *)ofono:\s*(?:#.*)?$", line)
        if not inside and m:
            inside, indent = True, len(m.group(1))
            continue
        if inside:
            if line.strip() and not line.lstrip().startswith("#") and len(line) - len(line.lstrip()) <= indent:
                break
            out.append((no, line))
    return out


def _const_strings(text: str, rel: str) -> list[tuple[int, str]]:
    """`OFONO_*`·`MODULES_*` 이름에 대입한 문자열 상수(줄 번호는 상수 시작 줄 + 상수 안 줄)."""
    out = []
    for node in ast.walk(ast.parse(text, filename=rel)):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant) \
                or not isinstance(node.value.value, str):
            continue
        if any(isinstance(t, ast.Name) and t.id.startswith(("OFONO_", "MODULES_")) for t in node.targets):
            for i, line in enumerate(node.value.value.split("\n")):
                out.append((node.value.lineno + i, line))
    return out


def check_dbus_names(files: dict[str, Path]) -> list[Finding]:
    """dbus-name 규칙(H C1+D R23, C1D §3.3). 범위 파일이 없으면 아무것도 하지 않는다."""
    docs = sorted(rel for rel in files if DBUS_DOCS.fullmatch(rel))
    scoped = docs + [r for r in (DBUS_MODULES, DBUS_CONSTS) if r in files]
    if not scoped:
        return []
    sc = _skillcheck()
    try:
        modules_text = files[DBUS_MODULES].read_bytes() if DBUS_MODULES in files else None
        if modules_text is None:
            raise ValueError("없음")
        doc = sc.load_modules_yaml(modules_text)
    except Exception as exc:  # noqa: BLE001 - 크기·UTF-8·YAML·앵커 → 닫힘
        return [Finding("dbus-name", DBUS_MODULES, 0, "", f"modules.yaml을 읽지 못해 D-Bus 허용 목록이 없다({type(exc).__name__})")]
    tpl = _ofono_template()
    plats = doc.get("platforms") if isinstance(doc, dict) else None
    allowed = tpl.dbus_allowed(plats.get("ofono") if isinstance(plats, dict) else None)
    findings = []

    def scan_lines(rel: str, lines) -> None:
        for no, line in lines:
            for _, name in tpl.dbus_violations(line, allowed):
                findings.append(Finding("dbus-name", rel, no, name, "허용 밖 D-Bus 이름(modules.yaml dbus에 없다)"))
    for rel in docs:
        text = _text(files[rel]) or ""
        scan_lines(rel, enumerate(text.splitlines(), 1))
    scan_lines(DBUS_MODULES, _ofono_block(modules_text.decode("utf-8")))
    if DBUS_CONSTS in files:
        try:
            scan_lines(DBUS_CONSTS, _const_strings(files[DBUS_CONSTS].read_text(encoding="utf-8"), DBUS_CONSTS))
        except (SyntaxError, UnicodeDecodeError) as exc:
            findings.append(Finding("dbus-name", DBUS_CONSTS, getattr(exc, "lineno", 0) or 0, "", f"파싱 실패: {exc}"))
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


SECRET_RULES = {"github-token", "aws-access-key", "slack-token", "google-api-key", "atlassian-token",
                "package-token", "llm-api-key", "jwt", "auth-header", "url-credential", "netrc", "secret-assign"}


def _redact(f: Finding) -> Finding:
    """비밀값은 출력(stderr·--json·CI 로그)에 앞부분과 길이만 남긴다. 예외 대조는 원문으로 끝난 뒤다."""
    if f.rule.removeprefix("pattern:") in SECRET_RULES:
        f.text = f.text[: min(12, len(f.text) // 3)] + f"…({len(f.text)}자)"
    return f


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
        + check_dbus_names(files)
    )
    if mode == "external":
        findings += check_site_paths_absent(root, site_patterns)
    return [_redact(f) for f in findings if not _allowed(f, allow)]


def detect_mode(root: Path) -> str:
    """`CLAUDE.md` 머리말의 표식을 쓰되 `.local-draft`(사외 PC 전용)를 먼저 본다. 틀려도 엄격한 쪽이다."""
    if (root / ".local-draft").exists():
        return "external"
    return "site" if any((root / m).exists() for m in SITE_MARKERS) else "external"


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
    parser.add_argument("--mode", choices=("external", "site"), default=None,
                        help="external: 사외 레포(SITE_PATHS 경로가 비어 있어야 함) / site: 사내 레포 "
                             "(기본: 자동 판별)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"레포 경로가 없습니다: {root}", file=sys.stderr)
        return USAGE
    mode = args.mode or detect_mode(root)
    label = mode if args.mode else f"{mode}, 자동"
    try:
        findings = scan(root, mode)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return USAGE

    if args.json:
        print(json.dumps({"mode": mode, "violations": [asdict(f) for f in findings]},
                         ensure_ascii=False, indent=2))
    elif findings:
        print(f"경계 위반 {len(findings)}건 ({label}):", file=sys.stderr)
        print(format_findings(findings), file=sys.stderr)
        print("예외가 맞으면 tools/boundary-allow.txt(사내는 docs/site/boundary-allow.txt)에 적는다.",
              file=sys.stderr)
    else:
        print(f"경계 위반 없음 ({label})")
    return VIOLATION if findings else OK


if __name__ == "__main__":
    raise SystemExit(main())
