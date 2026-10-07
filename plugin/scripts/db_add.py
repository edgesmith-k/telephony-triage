#!/usr/bin/env python3
"""db_add.py — 작업 계획 적용·drift 검사·ID 도구 (contracts.md §작업 계획, §renumber 참조, 01-architecture.md §3.1).

    db_add.py apply <plan.json> --db <path> [--pending <file>...] [--user <GHE 아이디>]
    db_add.py drift <plan.json> --onto <ref> [--db <path>]
    db_add.py renumber <옛 ID> [--base <ref>] [--db <path>]
    db_add.py check-ids [--base <ref>] [--db <path>]
    db_add.py similar <title> [--category <key>] [--symptom-json <file>] [--db <path>]

`apply` (db_pr stage가 `<wt>`에서 부른다)
- 계획 형식은 이슈 DB `schema/plan.schema.json`으로 검사한다. `source`가 허용 값 밖이면 거부(종료 코드 2).
  `schema_version`이 이슈 DB와 다르면 종료 코드 2 (`db_migrate upgrade-plan` 안내).
- 임시 ID(`NEW-TYPE-<n>`, `NEW-CAUSE-<n>`)는 **적용 대상 트리 기준 다음 번호**(최댓값 + 1)로 할당하고, 계획 안의
  모든 참조(op 필드, fixture 경로, 피드백, 커밋 메시지)를 치환한다. fixture 번호도 적용 시점에 정한다.
- 계획에서 fixture를 가리키는 값(`verify-resolution`의 evidence, `verify-fix`·`update-fix` history의 fixture,
  `allow-cause`의 fixture)이 같은 계획 `add-fixture`의 `path`와 같으면 할당된 `fixtures/<이름>`으로 바꾼다.
- op는 순서대로 메모리에서 적용하고, 거부가 없을 때만 파일에 쓴다. 거부는 종료 코드 1과 `rejected`.
- type.md와 parser-rules는 엔티티 단위로 다시 쓴다(`common/typedoc.py`, `common/yamldoc.py`).
- fixture와 Jira `note`는 마스킹 함수를 거쳐 쓴다(멱등).
- 피드백은 계획 `feedback`으로 `feedback/<YYYY-MM>/<KEY>-<YYYYMMDDTHHMM>.yaml`(시각은 `feedback.date`).
  `--pending`(pending 피드백)은 `source: analyze`일 때만 받는다.

`drift`: 계획의 `base_sha` 트리와 `<ref>` 트리를 비교해 계획 대상이 바뀐 목록을 낸다(contracts.md §작업 계획
drift 표). 항목은 `{op_index, op, target, field, plan_value(op가 쓰는 값), plan_base_value(계획 당시 main), current_value}`,
출력에 `ids_at_base`(계획 당시 트리 기준 임시 ID 할당, 새 유형·원인이 없으면 null)도 낸다. 계획에 `base_sha`가 없으면 종료 코드 2.
아무것도 바꾸지 않는다. drift가 있으면 종료 코드 1.

`renumber`: 직접 편집한 브랜치에서 "내 ID"(merge-base에 없던 ID)만 다음 빈 번호로 옮긴다(§renumber 참조).
  현재 브랜치가 base·`tt/*`·detached이거나 워킹 트리가 더러우면 종료 코드 2.
`check-ids`: 트리 안 ID 중복과, `--base`면 내 ID가 그 ref에 이미 있는지. 있으면 종료 코드 1.
`similar`: 전체 카테고리에서 제목·증상 시그니처가 비슷한 유형 상위 3개.

사용자 아이디(`analyzed_by`, `by`)는 `--user` 또는 사용자 config `user.ghe_id`.

이 파일은 CLI만 둔다. 구현은 `dbadd/`: `core`(상수·오류·계획 검사·`Tree`), `applier`(apply), `ops/<묶음>.py`
(op 메서드 믹스인: jira·entities·fix·resolution·signature·fixture·parser_rules), `drift`, `ids`, `similar`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import site_defaults  # noqa: E402
from common.exitcodes import USAGE  # noqa: E402
from dbadd.applier import cmd_apply  # noqa: E402
from dbadd.core import UsageError  # noqa: E402
from dbadd.drift import cmd_drift  # noqa: E402
from dbadd.ids import cmd_check_ids, cmd_renumber  # noqa: E402
from dbadd.similar import cmd_similar, similarity  # noqa: E402,F401 — db_review가 쓴다


# -- main ----------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="JSON 출력 (항상 JSON)")
    common.add_argument("--plugin-root", default=argparse.SUPPRESS)
    parser = argparse.ArgumentParser(prog="db_add.py", description=__doc__, parents=[common],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("apply", parents=[common])
    p.add_argument("plan", metavar="plan.json")
    p.add_argument("--pending", action="append", metavar="FILE")
    p.add_argument("--user")
    p = sub.add_parser("drift", parents=[common])
    p.add_argument("plan", metavar="plan.json")
    p.add_argument("--onto", metavar="ref", required=True)
    p = sub.add_parser("renumber", parents=[common])
    p.add_argument("old_id", metavar="옛 ID")
    p.add_argument("--base", default="origin/main")
    p = sub.add_parser("check-ids", parents=[common])
    p.add_argument("--base", metavar="ref")
    p = sub.add_parser("similar", parents=[common])
    p.add_argument("title")
    p.add_argument("--category")
    p.add_argument("--symptom-json")
    return parser


COMMANDS = {"apply": cmd_apply, "drift": cmd_drift, "renumber": cmd_renumber, "check-ids": cmd_check_ids,
            "similar": cmd_similar}


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    for name, default in (("db", None), ("plugin_root", None)):
        if not hasattr(args, name):
            setattr(args, name, default)
    defaults = site_defaults.load_or_exit(args.plugin_root)
    try:
        result, code = COMMANDS[args.cmd](args, defaults)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=1))
        return USAGE
    for item in result.get("rejected") or []:
        print(f"거부[{item['code']}] op {item['op_index']}: {item['message']}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
