#!/usr/bin/env python3
"""묶음 1(형식 이름 변경) 바이트 동일 검증 (설계 W/design-tracker.md §5). 일회성, 커밋하지 않는다.

    python3 rename_compare.py [--run]      # --run이면 rc_driver.py를 두 트리에 먼저 돌린다

기준 트리 W/base-tracker(fdf3ced, 옛 CLI·옛 샘플·`jira:`)와 작업 트리(새 CLI·변환된 샘플·`tracker:`)의 출력을 사례별로
비교한다. 정규화는 **옛 출력에만** 적용하고, 허용 차이는 아래 표(NORMALIZATION)뿐이다. 표를 출력해 §1과 같은지 사람이 본다.
역검사: 새 출력 JSON 안에 `jira`가 든 키가 남으면 실패(허용 목록 없음). 결과는 사례별 PASS/FAIL과 diff 앞 40줄.
"""
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

W = Path(__file__).resolve().parent
OLD, NEW = W / "rc-old", W / "rc-new"
REPO = Path("/home/user/telephony-triage")
# 묶음 2 모드(--b2): 기준 = 묶음 1 결과(49cb249, W/base-tracker-b1), 새 = 작업 트리. 둘 다 새 CLI라 정규화 없이 비교(휘발 값만 가림)
B3 = "--b3" in sys.argv      # 묶음 3 모드: 기준 = 묶음 2 결과(50124da, W/base-tracker-b2). B2와 같이 정규화 없음 + 허용 목록(ALLOW_B3)
B2 = "--b2" in sys.argv or B3
BASE_TREE, GOLDEN_REF = (W / "base-tracker-b1", "49cb249") if B2 else (W / "base-tracker", "fdf3ced")
if B2:
    OLD, NEW = W / "rc-b1", W / "rc-b2"
if B3:
    BASE_TREE, GOLDEN_REF = W / "base-tracker-b2", "50124da"
    OLD, NEW = W / "rc-b2base", W / "rc-b3"
# 묶음 3 허용 차이(새 출력에서만 지우고 보고): (사례, 파일) → 지울 최상위 키
ALLOW_B3 = {("C11", "approved_record.json"): ["kind"]}     # P2-5: 승인 기록 post.approved.json에 트래커 kind

# 1. JSON 키 재귀 개명 (§5-1)
KEY_RENAME = {"jira": "issue", "jira_count": "issue_count", "jira_recent": "issue_recent", "jira_latest": "issue_latest",
              "jira_gap_min": "issue_gap_min", "jira_in_main": "issue_in_main", "jira_done": "issue_done",
              "jira_origin": "issue_origin", "android_version": "platform_version", "android_versions": "platform_versions",
              "open-with-jira": "open-with-issues",      # db_review summary 키(항목 id)
              "android_versions_supported": "platform_versions_supported"}   # db_review thresholds(리뷰 반영 P2-2)
# 2. 열거 값 개명 — 키 이름으로만 (§5-2)
ENUM_BY_KEY = {"source": {"jira": "issue"},           # step_anchor.source
               "kind": {"jira": "issue"},             # needs_input.kind, db_search kind·results[].kind
               "year_source": {"jira": "tracker"},    # logcat.year_source
               "check": {"jira": "tracker", "jira_post": "tracker_post"},   # doctor 행 이름
               "code": {"duplicate-jira": "duplicate-issue", "jira-key": "issue-key", "jira-cause": "issue-cause",
                        "jira-missing": "issue-missing", "jira-exists": "issue-exists", "jira-fields": "issue-fields"},
               "id": {"open-with-jira": "open-with-issues"}, "key": {"open-with-jira": "open-with-issues"},
               "answer": {"--answer jira=<값>": "--answer issue=<값>"},
               "inputs": {"jira_summary": "issue_summary"},                 # analyzers.*.inputs
               "logcat.year_source": {"jira": "tracker"}}                   # config show --keys   # needs_input.answer(= kind에서 만든 문구)
QUALITY_PREFIX = (re.compile(r"^jira:"), "issue:")    # quality 출처 `jira:<KEY>`
# 3. 경로 문자열 (`/` 포함 또는 .json·.yaml로 끝나는 값, Markdown 링크 대상) (§5-3)
PATH_SUBS = [(re.compile(r"/jira/"), "/issues/"), (re.compile(r"\bjira_raw\.json\b", re.A), "issue_raw.json"),
             (re.compile(r"\bjira_meta\.json\b", re.A), "issue_meta.json"),
             (re.compile(r"(?<![\w.])jira\.json\b", re.A), "issue.json"),
             (re.compile(r"\bjira\.schema\.json\b", re.A), "issue.schema.json")]
# 4. 휘발 값 (§5-4): 키 이름으로 가린다
VOLATILE_KEYS = {"request_hash", "parts", "generated_at", "run", "lock_owner", "started_at", "ms", "elapsed_ms",
                 "acquired_at", "at", "expires_at", "approved_at", "sha", "snapshot_sha", "base_sha", "head_sha",
                 "fetched_at", "age_sec", "post_sha256", "body_sha256"}
if B2:
    VOLATILE_KEYS = VOLATILE_KEYS | {"created_at"}     # post.render.json 생성 시각(두 실행 사이 시각 차)
TMP_RE = re.compile("(" + re.escape(str(W / "base-tracker-b2")) + "|" + re.escape(str(W / "base-tracker-b1")) + "|" + re.escape(str(W / "base-tracker")) + "|" + re.escape(str(REPO)) + r"|/tmp/[^/\s\"'`|)]+)")
HEX40 = re.compile(r"\b[0-9a-f]{40}\b")
# 추가 정규화(설계 §5 표 밖 — 보고 대상): 사람용 문구 안의 설정 키 이름·출력 키 이름 표기, Markdown 헤더의 kind
EXTRA_TEXT_SUBS = [
    (re.compile(r"\bjira\.(mcp_server|tools|read_tools|write_tools|timezone|field_map|exclude_servers|failed_step_patterns)\b", re.A),
     r"tracker.\1", ),
    (re.compile(r"\bjira_latest\b", re.A), "issue_latest"), (re.compile(r"\bjira_count\b", re.A), "issue_count"),
    (re.compile(r"\(jira\)$", re.M), "(issue)"),
    (re.compile(r"events/jira_raw/match\.json"), "events/issue_raw/match.json"),
    # C13: 사람용 문구 안의 lint 코드·필드 이름·quality 출처 표기(§1-F 개명 그대로)
    (re.compile(r"\[(duplicate-jira|jira-key|jira-cause)\]"), lambda m: "[" + {"duplicate-jira": "duplicate-issue",
     "jira-key": "issue-key", "jira-cause": "issue-cause"}[m.group(1)] + "]"),
    (re.compile(r"\bandroid_versions_supported\b", re.A), "platform_versions_supported"),
    (re.compile(r"\bandroid_version(s?)\b", re.A), r"platform_version\1"),
    (re.compile(r"\(jira:"), "(issue:"),
]
# 추가(설계 밖): C14·C16의 YAML 본문(기록·피드백·type.md 내용, 확인 화면 diff 줄)의 줄 머리 키 개명 — §2-1 샘플 변환과 같은 규칙
YAML_KEY_SUBS = [(re.compile(r"^([+ -]?\s*(?:- )?)android_version(s?):", re.M), r"\1platform_version\2:"),
                 (re.compile(r"^([+ -]?\s*(?:- )?)jira:", re.M), r"\1issue:")]
NORMALIZATION = [
    ("1 키 개명(재귀)", ", ".join(f"{a}→{b}" for a, b in KEY_RENAME.items())),
    ("1 db_search", "결과 항목(type·cause)의 `jira` 목록 → `issues`"),
    ("1 config show", "최상위 `jira` → `tracker` + `kind: jira`"),
    ("2 열거 값(키 지정)", "; ".join(f"{k}: " + ", ".join(f"{a}→{b}" for a, b in v.items()) for k, v in ENUM_BY_KEY.items())
     + "; quality 출처 jira:→issue:"),
    ("3 경로 문자열", ", ".join(f"{p.pattern}→{r}" for p, r in PATH_SUBS)),
    ("4 휘발 값", ", ".join(sorted(VOLATILE_KEYS)) + ", 임시·트리 경로 → <TMP>, 40자리 SHA → <SHA>, 문구 안의 "
     "실행 시각·sha256(64·12자리)·스냅샷 짧은 SHA(7자리)"),
    ("추가(설계 밖, C14·C16)", "YAML 본문·diff 줄의 줄 머리 키 android_version(s):→platform_version(s):, jira:→issue: "
                               "(§2-1 샘플 변환과 같은 규칙, `content` 값과 확인 화면 텍스트에만)"),
    ("추가(설계 밖)", "사람용 문구의 설정 키 표기 jira.<키>→tracker.<키>, 텍스트 jira_latest/jira_count→issue_*, "
                     "Markdown 머리 (jira)→(issue), guard 규칙 10 문구 events/jira_raw/match.json, "
                     "C13 문구 안의 lint 코드 [duplicate-jira]·필드 이름 android_version(s)(_supported)·quality 출처 (jira:, "
                     "db_review 건수 키 jira(정수)→issues"),
]


def text_norm(s: str, old: bool) -> str:
    s = vol_text(s)
    if old:
        for pat, rep in PATH_SUBS + EXTRA_TEXT_SUBS:
            s = pat.sub(rep, s)
    return s


def is_pathish(v: str) -> bool:
    return "/" in v or v.endswith((".json", ".yaml"))


VOLATILE_TEXT = [(re.compile(r"(실행 \d+(?:, | \())\d{4}-\d\d-\d\dT[0-9:.]+(?:[+-]\d\d:\d\d|Z)"), r"\1<TS>"),
                 (re.compile(r"\b[0-9a-f]{64}\b"), "<SHA64>"), (re.compile(r"(sha256 )[0-9a-f]{12}\b"), r"\1<SHA12>"),
                 (re.compile(r"\((?:[0-9a-f]{7})(, [^)]*)?\)"), r"(<SHA7>\1)")]


def vol_text(v: str) -> str:
    v = TMP_RE.sub("<TMP>", v)
    v = HEX40.sub("<SHA>", v)
    for pat, rep in VOLATILE_TEXT:
        v = pat.sub(rep, v)
    return v


def norm(node, old: bool, key: str | None = None, parent: str | None = None):
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            nk = KEY_RENAME.get(k, k) if old else k
            if old and k == "jira" and isinstance(v, int) and not isinstance(v, bool):
                nk = "issues"          # db_review open-with-jira 행의 건수(§1-F `.jira` → `.issues`)
            if k in VOLATILE_KEYS:
                out[nk] = "<VOLATILE>"
                continue
            out[nk] = norm(v, old, k, key)
        return out
    if isinstance(node, list):
        if key == "results":
            return [norm_entry(x, old) for x in node]
        return [norm(x, old, key, parent) for x in node]
    if isinstance(node, str):
        v = node
        if old and key in ENUM_BY_KEY and v in ENUM_BY_KEY[key] and not (key == "kind" and parent == "tracker"):
            v = ENUM_BY_KEY[key][v]
        if old and (key == "sources" or parent == "sources"):
            v = QUALITY_PREFIX[0].sub(QUALITY_PREFIX[1], v)
        if old and is_pathish(v):
            for pat, rep in PATH_SUBS:
                v = pat.sub(rep, v)
        if old:
            for pat, rep in EXTRA_TEXT_SUBS[:1] + EXTRA_TEXT_SUBS[4:]:   # 문자열 값: 설정 키·규칙 10·C13 문구
                v = pat.sub(rep, v)
        return vol_text(v)
    return node


def norm_entry(x, old: bool):
    if isinstance(x, dict) and old and isinstance(x.get("jira"), list):
        x = {("issues" if k == "jira" else k): v for k, v in x.items()}
    return norm(x, old)


def config_fix(doc, old: bool):
    """C10 show: 옛 최상위 `jira` → `tracker` + kind."""
    if not old or not isinstance(doc, dict):
        return doc
    eff = (doc.get("stdout") or {}).get("effective") if isinstance(doc.get("stdout"), dict) else None
    if isinstance(eff, dict) and "jira" in eff:
        eff["tracker"] = {"kind": "jira", **eff.pop("jira")}
    vals = (doc.get("stdout") or {}).get("values") if isinstance(doc.get("stdout"), dict) else None
    if isinstance(vals, dict):
        for k in list(vals):
            if k.startswith("jira."):
                vals["tracker." + k[5:]] = vals.pop(k)
    return doc


def jira_keys(node, path="") -> list[str]:
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if "jira" in k.lower():
                out.append(f"{path}/{k}")
            out += jira_keys(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += jira_keys(v, f"{path}[{i}]")
    return out


def yaml_keys(node):
    if isinstance(node, dict):
        return {k: (yaml_text(v) if k == "content" and isinstance(v, str) else yaml_keys(v)) for k, v in node.items()}
    if isinstance(node, list):
        return [yaml_keys(x) for x in node]
    return node


def yaml_text(v: str) -> str:
    for pat, rep in YAML_KEY_SUBS:
        v = pat.sub(rep, v)
    return v


def load(p: Path, old: bool):
    if p.suffix != ".json" and old and p.parent.name in ("C14", "C16"):
        return text_norm(yaml_text(p.read_text(encoding="utf-8")), old), None
    if p.suffix == ".json":
        doc = json.loads(p.read_text(encoding="utf-8"))
        if old and p.parent.name in ("C14", "C16"):
            doc = yaml_keys(doc)
        if p.parent.name == "C10":
            doc = config_fix(doc, old)
        return json.dumps(norm(doc, old), ensure_ascii=False, indent=1, sort_keys=True), doc
    return text_norm(p.read_text(encoding="utf-8"), old), None


def golden() -> tuple[bool, str]:
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", "tests/test_golden.py"],
                          cwd=REPO, capture_output=True, text=True)
    diff = subprocess.run(["git", "diff", "--stat", GOLDEN_REF, "--", "tests/fixtures/golden"], cwd=REPO, capture_output=True,
                          text=True).stdout.strip()
    last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr[-200:]
    return proc.returncode == 0 and not diff, f"test_golden: {last}; golden 파일 diff: {diff or '없음'}"


ALLOWED: list[str] = []


def main() -> int:
    if "--run" in sys.argv:
        for tree, side, out in ((BASE_TREE, "new" if B2 else "old", OLD), (REPO, "new", NEW)):
            subprocess.run(["rm", "-rf", str(out)])
            subprocess.run([sys.executable, str(W / "rc_driver.py"), str(tree), side, str(out)], check=True)
    if B2:
        print(f"## 묶음 {'3' if B3 else '2'} 모드: 기준 {GOLDEN_REF}({BASE_TREE.name}) vs 작업 트리 — 정규화 없음(휘발 값만 가림: 4번 줄)"
              + (" + 허용 목록 ALLOW_B3" if B3 else "") + "\n")
        print("| 단계 | 내용 |\n|---|---|")
        print(f"| 4 휘발 값 | {NORMALIZATION[5][1]} |\n")
    else:
        print("## 정규화 표 (옛 출력에만 적용)\n")
        print("| 단계 | 내용 |\n|---|---|")
        for a, b in NORMALIZATION:
            print(f"| {a} | {b} |")
        print()
    cases = sorted({p.name for p in OLD.iterdir() if p.is_dir()} | {p.name for p in NEW.iterdir() if p.is_dir()} - (set() if B2 else {"LEGACY"}),
                   key=lambda c: (len(c), c))
    results = {}
    for case in cases:
        fails, notes, n = [], [], 0
        names = sorted({p.name for p in (OLD / case).glob("*")} | {p.name for p in (NEW / case).glob("*")})
        for name in names:
            po, pn = OLD / case / name, NEW / case / name
            if not po.exists() or not pn.exists():
                fails.append(f"{name}: 한쪽에만 있음 (old={po.exists()}, new={pn.exists()})")
                continue
            n += 1
            a, _ = load(po, not B2)
            b, raw_new = load(pn, False)
            drop = ALLOW_B3.get((case, name)) if B3 else None
            if drop and isinstance(raw_new, dict):
                present = [k for k in drop if k in raw_new]
                notes.append(f"{name}: 허용 차이 키 {present} = {[raw_new.get(k) for k in present]}")
                b = json.dumps({k: v for k, v in json.loads(b).items() if k not in drop}, ensure_ascii=False,
                               indent=1, sort_keys=True)
            if a != b:
                d = list(difflib.unified_diff(a.splitlines(), b.splitlines(), f"old/{name}", f"new/{name}", lineterm="", n=1))
                fails.append(f"{name}:\n" + "\n".join(d[:40]))
            if raw_new is not None and case != "LEGACY":   # LEGACY 키는 사례 이름(user_jira_block 등)
                left = jira_keys(raw_new)
                if left:
                    fails.append(f"{name}: 새 출력에 jira 키 남음 {left[:5]}")
        results[case] = (not fails, n, fails)
        ALLOWED.extend(f"{case} {x}" for x in notes)
    ok12, ev12 = golden()
    results["C12"] = (ok12, 1, [] if ok12 else [ev12])
    print("## 결과\n\n| 사례 | 결과 | 비교 파일 |\n|---|---|---|")
    for case, (ok, n, _) in sorted(results.items(), key=lambda kv: (len(kv[0]), kv[0])):
        print(f"| {case} | {'PASS' if ok else 'FAIL'} | {n if case != 'C12' else ev12} |")
    for case, (ok, _, fails) in sorted(results.items(), key=lambda kv: (len(kv[0]), kv[0])):
        if not ok:
            print(f"\n### {case} FAIL")
            for f in fails[:6]:
                print(f)
    if B3:
        print("\n## 허용 차이 (ALLOW_B3, 새 출력에서만 지움)\n")
        for line in ALLOWED or ["(없음 — 허용 목록 파일이 비교되지 않았다)"]:
            print(f"- {line}")
    legacy = NEW / "LEGACY" / "detect.json"
    if legacy.is_file():
        print("\n## 옛 설정 키 감지 (새 트리만, §2-2)\n")
        doc = json.loads(legacy.read_text(encoding="utf-8"))
        for name, row in doc.items():
            parts = []
            for k, v in row.items():
                if isinstance(v, dict) and "decision" in v:
                    parts.append(f"{k}={v['decision']}")
                elif isinstance(v, dict) and "code" in v:
                    extra = ""
                    if k == "bridge":
                        txt = json.dumps(v.get("stdout"), ensure_ascii=False)
                        extra = "(대체)" if "옛 설정 키" in txt else "(원문?)"
                    parts.append(f"{k}=exit{v['code']}{extra}")
                elif k == "doctor_tracker":
                    parts.append(f"doctor tracker={v and v.get('status')}")
                else:
                    parts.append(f"{k}={v}")
            print(f"- {name}: " + ", ".join(parts))
    return 0 if all(ok for ok, _, _ in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
