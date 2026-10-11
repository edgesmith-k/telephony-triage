#!/usr/bin/env python3
"""운영용 이슈 DB 뼈대를 만든다 (11-phases.md Phase 1, 15-local-draft.md §15.4).

합성 샘플 트리(`tests/fixtures/issue-db-sample/`)에서 **유형 디렉토리·Jira 기록·
fixture·피드백 기록을 뺀** 것이 뼈대다. 반입·사내 운영 레포는 이것으로 시작한다.

들어가는 것
    issue-db.config.yaml, schema/ (6), templates/ (3), parser-rules/ (placeholder),
    .github/ (CODEOWNERS, PR 템플릿), docs/ (3), .githooks/ (pre-commit·pre-push),
    CONTRIBUTING.md, GLOSSARY.md, .gitignore, .gitattributes,
    빈 카테고리 디렉토리(.gitkeep)와 feedback/(.gitkeep)

들어가지 않는 것
    유형 디렉토리(type.md, jira/, fixtures/), 피드백 파일,
    생성 파일(README.md, 카테고리 README.md, STATS.md, parser-rules/CHANGELOG.md)
    — 생성 파일은 첫 PR 때 `db_build.py --write`가 만든다 (Phase 5).

parser-rules의 `added_for`는 뼈대에 존재하지 않는 유형을 가리키면 안 되므로
모두 `-`로 바꾼다. 나머지 내용(주석, TODO(SITE) 표시)은 그대로 둔다.

`--platform <이름>`(17-platforms §4): 샘플은 기본 플랫폼(android, `platform` 키 없음) DB다. 다른 플랫폼이면
설정에 `platform: <이름>`을 넣고, 지원 버전 키를 `platform_versions_supported: []`로, `parser_backend`를 그 플랫폼
기본 백엔드(`SPEC.default_backend`와 그 버전)로, `code_root_keys`를 `SPEC.default_root_keys`로 바꾼다.
parser-rules는 샘플(android 문구)을 쓰지 않고 스키마 최소 placeholder 항목만 둔다(TODO(SITE)). 플랫폼 이름은
레지스트리(`plugin/scripts/platforms`)로 확인한다. 기본 플랫폼이면 결과는 옵션 없을 때와 같다.

CLI:
    python3 tools/make_db_skeleton.py <out_dir> [--platform NAME] [--force] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "tests" / "fixtures" / "issue-db-sample"
SCRIPTS = REPO / "plugin" / "scripts"

# 그대로 복사하는 파일·디렉토리 (샘플 트리 기준 상대 경로)
COPY_FILES = [
    "issue-db.config.yaml",
    "CONTRIBUTING.md",
    "GLOSSARY.md",
    ".gitignore",
    ".gitattributes",
    ".github/CODEOWNERS",
    ".github/pull_request_template.md",
    "docs/getting-started.md",
    "docs/review-guide.md",
    "docs/branch-protection.md",
    ".githooks/pre-commit",
    ".githooks/pre-push",
]
COPY_DIRS = ["schema", "templates"]

# added_for를 '-'로 바꿔서 복사하는 파일
PARSER_RULES = ["parser-rules/tags.yaml", "parser-rules/ril.yaml", "parser-rules/extractors.yaml"]

ADDED_FOR_RE = re.compile(r"added_for:\s*'?[A-Z][A-Z0-9]*-\d{3}(?:-\d{2})?'?")

SKELETON_NOTE = (
    "# [뼈대] 이 파일은 tools/make_db_skeleton.py가 합성 샘플에서 만든 것이다.\n"
    "# 유형이 없는 상태이므로 added_for는 모두 '-'다. 첫 유형을 추가할 때\n"
    "# add-parser-rule / update-parser-rule op로 실제 ID를 넣는다.\n"
)

# 카테고리 디렉토리는 issue-db.config.yaml의 categories에서 읽는다.
CATEGORY_RE = re.compile(r"^\s*-\s*\{key:\s*([a-z][a-z0-9_]*)\s*,", re.MULTILINE)


# 기본 아닌 플랫폼의 parser-rules (스키마가 파일마다 항목 1개 이상을 요구해서 둔 자리표시 항목)
PLACEHOLDER_RULES = {
    "parser-rules/tags.yaml": """# [뼈대·placeholder] {label} 플랫폼 태그. 실제 로그를 받은 뒤 바꾼다. TODO(SITE)
tags:
  - {{tag: PLACEHOLDER_TAG, category: common, added_for: '-', added_on: 2026-10-11, reason: placeholder (스키마 최소 항목)}}
""",
    "parser-rules/ril.yaml": """# [뼈대·placeholder] {label} 플랫폼 요청-응답 짝 이름. 실제 로그를 받은 뒤 바꾼다. TODO(SITE)
unsolicited:
  - {{name: PLACEHOLDER_UNSOL, category: common, added_for: '-', added_on: 2026-10-11, reason: placeholder (스키마 최소 항목)}}
""",
    "parser-rules/extractors.yaml": """# [뼈대·placeholder] {label} 플랫폼 이벤트 추출 규칙. 실제 로그 문구가 아니다. TODO(SITE)
extractors:
  - id: placeholder
    added_for: '-'
    added_on: 2026-10-11
    reason: placeholder (스키마 최소 항목)
    tag: PLACEHOLDER_TAG
    patterns:
      - '^PLACEHOLDER_MESSAGE$'
    event: placeholder_event
    fields: []
""",
}


def _platform(name: str):
    """레지스트리로 플랫폼 이름을 확인한다 → `(기본 플랫폼인가, SPEC, 백엔드 버전)`."""
    sys.path.insert(0, str(SCRIPTS))
    import parser_backends
    import platforms

    try:
        spec = platforms.get(name)
        backend = parser_backends.load(spec.default_backend)
    except (platforms.PlatformConfigError, parser_backends.BackendError) as exc:
        raise SystemExit(f"--platform: {exc}") from exc
    return name == platforms.DEFAULT_NAME, spec, backend.version()


def _platform_config(text: str, spec, version: str) -> str:
    """샘플(기본 플랫폼) 설정을 다른 플랫폼 설정으로 바꾼다. 바꿀 줄이 없으면 멈춘다(샘플이 바뀐 것)."""
    edits = [
        (r"(?m)^schema_version:", lambda m: f"platform: {spec.name}                      # 17-platforms §4\n{m[0]}"),
        (r"(?m)^android_versions_supported:.*$",
         lambda m: "platform_versions_supported: []      # TODO(SITE) 이 플랫폼에서 지원하는 버전"),
        (r"(?m)^(parser_backend:[^\n]*\n  name: )\S+[^\n]*\n  min_version: \S+",
         lambda m: f"{m[1]}{spec.default_backend}\n  min_version: {version}"),
        (r"(?m)^code_root_keys: \[.*\]", lambda m: f"code_root_keys: [{', '.join(spec.default_root_keys)}]"),
    ]
    for pattern, new in edits:
        text, n = re.subn(pattern, new, text, count=1)
        if not n:
            raise SystemExit(f"issue-db.config.yaml에서 바꿀 줄을 찾지 못했습니다: {pattern}")
    return text


def _read_categories(config_text: str) -> list[str]:
    keys = CATEGORY_RE.findall(config_text)
    if not keys:
        raise SystemExit("issue-db.config.yaml에서 categories를 읽지 못했습니다.")
    return keys


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def make(out: Path, force: bool = False, platform: str | None = None) -> dict:
    is_default, spec, version = _platform(platform) if platform else (True, None, None)
    if not SAMPLE.exists():
        raise SystemExit(f"샘플 트리가 없습니다: {SAMPLE}")
    if out.exists():
        if not force:
            raise SystemExit(f"이미 있습니다: {out} (--force로 덮어쓰기)")
        shutil.rmtree(out)

    created: list[str] = []

    for rel in COPY_FILES:
        src = SAMPLE / rel
        if not src.exists():
            raise SystemExit(f"샘플에 없습니다: {rel}")
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel == "issue-db.config.yaml" and not is_default:
            _write(dst, _platform_config(src.read_text(encoding="utf-8"), spec, version))
        else:
            shutil.copy2(src, dst)
        created.append(rel)

    for rel in COPY_DIRS:
        src = SAMPLE / rel
        if not src.is_dir():
            raise SystemExit(f"샘플에 없습니다: {rel}/")
        shutil.copytree(src, out / rel)
        created.extend(sorted(str(p.relative_to(SAMPLE)).replace("\\", "/") for p in src.rglob("*") if p.is_file()))

    for rel in PARSER_RULES:
        src = SAMPLE / rel
        if not src.exists():
            raise SystemExit(f"샘플에 없습니다: {rel}")
        if is_default:
            text = ADDED_FOR_RE.sub("added_for: '-'", src.read_text(encoding="utf-8"))
        else:
            text = PLACEHOLDER_RULES[rel].format(label=spec.label)
        _write(out / rel, SKELETON_NOTE + text)
        created.append(rel)

    categories = _read_categories((SAMPLE / "issue-db.config.yaml").read_text(encoding="utf-8"))
    for key in categories:
        _write(out / key / ".gitkeep", "")
        created.append(f"{key}/.gitkeep")
    _write(out / "feedback" / ".gitkeep", "")
    created.append("feedback/.gitkeep")

    info = {"out": str(out), "categories": categories, "files": sorted(created)}
    if not is_default:
        info["platform"] = spec.name
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_db_skeleton.py", description=__doc__)
    parser.add_argument("out_dir", help="뼈대를 만들 디렉토리")
    parser.add_argument("--platform", metavar="NAME", help="플랫폼 (기본: 샘플과 같은 기본 플랫폼, 17-platforms §4)")
    parser.add_argument("--force", action="store_true", help="이미 있으면 지우고 다시 만든다")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    info = make(Path(args.out_dir), force=args.force, platform=args.platform)
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(f"이슈 DB 뼈대를 만들었습니다: {info['out']}" + (f" (플랫폼 {info['platform']})" if "platform" in info else ""))
        print(f"카테고리 {len(info['categories'])}개: {', '.join(info['categories'])}")
        print(f"파일 {len(info['files'])}개 (유형·Jira·fixture·피드백 없음)")
        print("생성 파일(README.md, STATS.md 등)은 첫 PR 때 db_build.py --write가 만든다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
