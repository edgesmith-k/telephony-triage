#!/usr/bin/env python3
"""스킬 eval 채점 보조 (tests/skill_evals/README.md).

    python3 tests/skill_evals/grade.py <iteration 디렉토리> [--eval <id>...]

`evals.json`의 assertion 가운데 기계적으로 확인할 수 있는 것(원격 브랜치·파일, gh PR, 세션 lock, 사용자 clone 상태,
원문 PII 노출, Jira 쓰기 도구 호출, 계획 내용)은 여기서 판정한다. 나머지는 `passed: null`(사람·LLM이 transcript로 채점)로 남긴다.
결과는 각 run 디렉토리의 `grading.json` — skill-creator viewer 형식 `{expectations: [{text, passed, evidence}], summary}`.
수동 채점만 보존하고, 스크립트 판정은 다시 계산한다. 실행 기록이 없으면 미실행으로 남긴다.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent


def git(repo, *args) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return p.stdout if p.returncode == 0 else ""


_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?^\s*\2\s*$", re.S | re.M)


def _strip_heredocs(cmd: str) -> str:
    """heredoc 본문(실행자가 transcript·commands.md를 쓰는 글)은 실행한 명령이 아니다."""
    return _HEREDOC_RE.sub("<<heredoc", cmd)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


class Ctx:
    def __init__(self, env_dir: Path, run_dir: Path):
        self.env = json.loads((env_dir / "env.json").read_text(encoding="utf-8"))
        self.before = json.loads((env_dir / "before.json").read_text(encoding="utf-8"))
        self.env_dir, self.run = env_dir, run_dir
        self.remote = Path(self.env["remote"])
        self.work = Path(self.env["work_dir"])
        try:
            self.execution = json.loads(_read(run_dir / "execution.json") or "{}")
        except ValueError:
            self.execution = {}
        out = run_dir / "outputs"
        self.transcript = (out / "transcript.md").read_text(encoding="utf-8") if (out / "transcript.md").is_file() else ""
        self.commands = (out / "commands.md").read_text(encoding="utf-8") if (out / "commands.md").is_file() else ""
        # 실행한 명령만: commands.md 표의 명령 칸(설명 문장 제외)과 triage.py 드라이버 trace(내부 호출)
        cells = [row.split("|")[2] for row in self.commands.splitlines()
                 if row.lstrip().startswith("|") and row.count("|") >= 3]
        self.invoked = "\n".join(cells or [self.commands]) + "\n" + self.trace()
        # 실행 기록(events.jsonl)의 실제 Bash 명령도 본다 — commands.md는 실행자가 쓴 요약이라 빠질 수 있다
        self.invoked += "\n" + "\n".join(_strip_heredocs(str(i.get("command", ""))) for n, i in (self.tool_uses() or []) if n == "Bash")
        # 실제로 실행한 것(R13): 실행 기록의 Bash 명령 + MCP 도구 호출(이름·인자) + 드라이버 trace. 실행자가 쓴 commands.md는
        # 빠지거나 지어낼 수 있으므로 실행 기록이 있으면 보지 않는다. 기록이 없을 때(옛 결과)만 commands.md로 대신한다.
        uses = self.tool_uses()
        if uses is None:
            self.ran = self.invoked
        else:
            self.ran = "\n".join([*(_strip_heredocs(str(i.get("command", ""))) for n, i in uses if n == "Bash"),
                                  *(f"{n} {json.dumps(i, ensure_ascii=False)}" for n, i in uses if n.startswith("mcp__")),
                                  self.trace()])

    def trace(self) -> str:
        lines = []
        for path in sorted(self.work.glob("*/trace.jsonl")) if self.work.is_dir() else []:
            for raw in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                if row.get("script"):
                    lines.append(" ".join([row["script"], *map(str, row.get("args") or [])]))
        return "\n".join(lines)

    def tool_uses(self):
        """events.jsonl의 assistant tool_use를 [(이름, 입력)]으로. 기록이 없으면 None."""
        p = self.run / "events.jsonl"
        if not p.is_file():
            return None
        out = []
        for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if ev.get("type") == "assistant":
                out += [(c.get("name") or "", c.get("input") or {}) for c in (ev.get("message") or {}).get("content") or []
                        if isinstance(c, dict) and c.get("type") == "tool_use"]
        return out

    def opened(self, *names):
        """Read나 Bash 읽기(cat·head·tail·less·sed·awk·jq·grep·python)로 연 파일 중 basename이 names에 있는 것.
        triage·parse_logcat 호출 인자는 제외한다. events.jsonl이 없으면 commands.md의 읽기 명령으로 본다."""
        uses = self.tool_uses()
        if uses is None:
            return [n for n in names if re.search(r"\b(cat|head|tail|less|sed|awk|jq|grep)\b[^|\n]*" + re.escape(n), self.invoked)]
        hits = []
        for name, inp in uses:
            if name == "Read" and Path(str(inp.get("file_path", ""))).name in names:
                hits.append(Path(inp["file_path"]).name)
            elif name == "Bash":
                cmd = str(inp.get("command", ""))
                if re.search(r"\b(cat|head|tail|less|sed|awk|jq|grep|python3?)\b", cmd) \
                        and "triage.py" not in cmd and "parse_logcat.py" not in cmd:
                    hits += [n for n in names if re.search(r"(?<![\w.-])" + re.escape(n) + r"\b", cmd)]
        return hits

    _RAW_READ_CMD = re.compile(r"(?<![\w./-])(cat|head|less|strings|unzip)\b([^|;&\n]*)")

    def _is_raw_target(self, token: str) -> bool:
        t = token.strip("\"'")
        name = Path(t).name
        if "/fixtures/" in t.replace("\\", "/"):
            return False     # 판별 근거 주변만 잘라 마스킹한 fixture(`cut` 출력)는 원문이 아니다
        if name in ("events.json", "jira_raw.json") or name.endswith((".log", ".zip")):
            return True
        logs = self.env_dir / "logs"
        return "/logs/" in t.replace("\\", "/") or t.startswith("logs/") or str(logs) in t

    def raw_full_reads(self) -> list[str]:
        """원문 통독 의심(지표): 로그·zip·events.json·jira_raw.json을 Bash cat/head -c/less/strings/unzip -p 로 열거나
        limit 없는 Read로 읽은 호출. 채점 항목은 아니다. 실행 기록이 없으면 빈 목록."""
        hits = []
        for name, inp in self.tool_uses() or []:
            if name == "Read":
                fp = str(inp.get("file_path", ""))
                if fp and not inp.get("limit") and self._is_raw_target(fp):
                    hits.append(f"Read {fp}")
            elif name == "Bash":
                cmd = _strip_heredocs(str(inp.get("command", "")))
                for m in self._RAW_READ_CMD.finditer(cmd):
                    verb, rest = m.group(1), m.group(2)
                    if verb == "head" and not re.search(r"(^|\s)-c\b", rest):
                        continue
                    if verb == "unzip" and not re.search(r"(^|\s)-\w*p", rest):
                        continue
                    if any(self._is_raw_target(t) for t in rest.split() if not t.startswith("-")):
                        hits.append(f"{verb}{rest}".strip()[:200])
        return hits

    # 원격 ---------------------------------------------------------------------------------
    def branches(self) -> list[str]:
        return [l.split("refs/heads/")[-1] for l in git(self.remote, "for-each-ref", "--format=%(refname)",
                                                        "refs/heads").splitlines()]

    def files(self, branch: str) -> list[str]:
        return git(self.remote, "ls-tree", "-r", "--name-only", branch).splitlines()

    def show(self, branch: str, rel: str) -> str:
        return git(self.remote, "show", f"{branch}:{rel}")

    def find(self, branch: str, pattern: str) -> list[str]:
        return [f for f in self.files(branch) if fnmatch.fnmatch(f, pattern)]

    def prs(self) -> list[dict]:
        p = Path(self.env["gh_state"]) / "prs.json"
        return json.loads(p.read_text(encoding="utf-8")).get("prs", []) if p.is_file() else []

    # 로컬 ---------------------------------------------------------------------------------
    def lock_free(self):
        p = self.work / "session.lock"
        return (not p.is_file(), "session.lock 없음" if not p.is_file() else p.read_text(encoding="utf-8"))

    def clone_same(self):
        clone = Path(self.env["issue_db_clone"])
        now = {"branch": git(clone, "rev-parse", "--abbrev-ref", "HEAD").strip(),
               "head": git(clone, "rev-parse", "HEAD").strip(),
               "status": git(clone, "status", "--porcelain").strip(),
               "branches": sorted(git(clone, "branch", "--format=%(refname:short)").split())}
        before = {k: (v.strip() if isinstance(v, str) else v if isinstance(v, dict) else sorted(v))
                  for k, v in self.before.items()}
        # HEAD는 pull --ff-only로 앞으로 갈 수 있다(원칙상 허용). 브랜치·워킹 트리·브랜치 목록, main 밖 로컬 브랜치 SHA를 본다.
        same = all(now[k] == before[k] for k in ("branch", "status", "branches"))
        shas = {b: git(clone, "rev-parse", f"refs/heads/{b}").strip() for b in (before.get("branch_shas") or {})}
        same = same and all(shas[b] == sha for b, sha in (before.get("branch_shas") or {}).items() if b != "main")
        now["branch_shas"] = shas
        return same, f"before={before} now={now}"

    def plan(self, job: str) -> dict | None:
        p = self.work / job / "plan.json"
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
        q = self.run / "outputs" / "plan.json"
        return json.loads(q.read_text(encoding="utf-8")) if q.is_file() else None

    def jira_writes(self):
        p = Path(self.env["env"]["MOCK_JIRA_WRITE_LOG"])
        return (not p.is_file(), "쓰기 도구 호출 없음" if not p.is_file() else p.read_text(encoding="utf-8"))

    def pending(self) -> list[str]:
        d = Path(self.env["env"]["TELEPHONY_TRIAGE_HOME"]) / "pending-feedback"
        return sorted(p.name for p in d.glob("*.yaml")) if d.is_dir() else []


def _yaml_front(text: str) -> dict:
    return yaml.safe_load(text.split("---")[1]) if text.startswith("---") else {}


def _cause(ctx: Ctx, branch: str, type_glob: str, cid: str) -> dict | None:
    for f in ctx.find(branch, type_glob):
        for c in _yaml_front(ctx.show(branch, f)).get("causes") or []:
            if c.get("id") == cid:
                return c
    return None


def checks(eid: int, ctx: Ctx) -> list:
    """assertion 순서대로 (함수 | None). 함수는 (passed, evidence)."""
    if eid in (10, 20, 21, 22, 23, 25, 26, 27, 28):
        return checks_c(eid, ctx)
    if eid in (31, 34, 35, 36, 38):
        return checks_d(eid, ctx)
    no_remote = lambda br: (lambda: (br not in ctx.branches() and not ctx.prs(), f"branches={ctx.branches()} prs={len(ctx.prs())}"))
    if eid == 1:
        br = "issue/MOCK-1001"
        def jira():
            t = ctx.show(br, "data/DATA-001-no-setup-data-call/jira/MOCK-1001.yaml")
            return ("cause: DATA-001-01" in t, t or f"branches={ctx.branches()}")
        def fb():
            fs = ctx.find(br, "feedback/*/MOCK-1001-*.yaml")
            d = yaml.safe_load(ctx.show(br, fs[0])) if fs else {}
            return (d.get("decision") == "accepted" and d.get("final") == "DATA-001-01", str(d) or "피드백 없음")
        return [None, None, None, jira, fb, lambda: (len(ctx.prs()) == 1, f"prs={len(ctx.prs())}"),
                None, ctx.lock_free, ctx.clone_same]
    if eid == 2:
        def nc():
            p = ctx.plan("MOCK-9002") or {}
            ops = [o for o in p.get("operations", []) if o.get("op") == "new-cause"]
            ok = bool(ops) and ops[0].get("temp_id") == "NEW-CAUSE-1" and ops[0].get("type") == "DATA-001" \
                and "NO_SUITABLE_DATA_PROFILE" in json.dumps(ops[0].get("cause", {}).get("signatures"))
            return ok, json.dumps(ops, ensure_ascii=False)[:600]
        def fx():
            p = ctx.plan("MOCK-9002") or {}
            ops = [o for o in p.get("operations", []) if o.get("op") == "add-fixture"]
            ok = any(o.get("for") == "NEW-CAUSE-1" and o.get("kind") == "positive" for o in ops) and " cut " in ctx.ran
            return ok, json.dumps(ops, ensure_ascii=False)
        def res():
            p = ctx.plan("MOCK-9002") or {}
            ops = [o for o in p.get("operations", []) if o.get("op") == "new-cause"]
            r = (ops[0].get("cause", {}).get("resolution") if ops else "") or ""
            return r.rstrip(". ").endswith("한다"), r
        def lock_pending():
            ok, ev = ctx.lock_free()
            return ok and not ctx.pending(), f"{ev}; pending={ctx.pending()}"
        return [None, nc, fx, None, res, None, no_remote("issue/MOCK-9002"), lock_pending]
    if eid == 16:
        br = "issue/MOCK-9016"
        def lease():
            return ("--lease new" not in ctx.ran and "publish" in ctx.ran, "실행 기록의 publish 호출")
        def renum():
            c = _cause(ctx, br, "data/DATA-001-*/type.md", "DATA-001-04")
            fx = ctx.find(br, "data/DATA-001-*/fixtures/DATA-001-04.log")
            return (c is not None and bool(fx), f"cause={bool(c)} fixture={fx}")
        return [None, None, None, lease, renum, ctx.lock_free]
    if eid == 19:
        br = "verify-fix/CALL-001-01-MOCKB77_U2_20260925"
        def fixed():
            c = _cause(ctx, br, "call/CALL-001-*/type.md", "CALL-001-01") or {}
            f = c.get("fix") or {}
            return (f.get("status") == "fixed" and (f.get("verification") or {}).get("build") == "MOCKB77_U2_20260925",
                    json.dumps(f, ensure_ascii=False, default=str)[:400] or f"branches={ctx.branches()}")
        def fxf():
            fs = ctx.find(br, "call/CALL-001-*/fixtures/CALL-001-01.fixed.MOCKB77_U2_20260925.log")
            return bool(fs), str(fs)
        return [None, None, fixed, fxf, ctx.lock_free]
    if eid == 30:
        br = "issue/MOCK-9030"
        def noparse():
            bad = [w for w in ("parse_logcat", "match_signatures") if w in ctx.ran]
            return not bad, f"commands.md에서 발견: {bad}"
        def plan():
            p = ctx.plan("MOCK-9030") or {}
            ops = p.get("operations", [])
            fb = p.get("feedback") or {}
            ok = p.get("source") == "record" and ops == [{"op": "append", "cause": "DATA-001-02"}] \
                and fb.get("decision") == "manual" and fb.get("suggested") == []
            return ok, json.dumps({"source": p.get("source"), "ops": ops, "feedback": fb}, ensure_ascii=False)
        def jira():
            t = ctx.show(br, "data/DATA-001-no-setup-data-call/jira/MOCK-9030.yaml")
            return ("cause: DATA-001-02" in t, t or f"branches={ctx.branches()}")
        return [noparse, lambda: ("jira_fetch_ticket" in ctx.ran, "실행 기록(Bash·MCP)"), plan, None, jira, ctx.lock_free]
    if eid == 32:
        def plan():
            p = ctx.plan("MOCK-9032") or {}
            ops = [o for o in p.get("operations", []) if o.get("op") == "new-cause"]
            c = ops[0].get("cause", {}) if ops else {}
            ok = bool(ops) and not c.get("signatures") and c.get("signatures_pending") is True \
                and (c.get("resolution_verification") or {}).get("status") == "unverified"
            return ok, json.dumps(c, ensure_ascii=False)[:500]
        return [None, plan, None, None, None, no_remote("issue/MOCK-9032")]
    if eid == 40:
        def plan():
            p = ctx.plan("MOCK-9040") or {}
            ok = p.get("operations") == [{"op": "append", "cause": "DATA-001-01"}] and \
                (p.get("feedback") or {}).get("decision") == "chose-other"
            return ok and analyzer_called()[0], json.dumps({"ops": p.get("operations"), "fb": p.get("feedback")}, ensure_ascii=False) + "; " + analyzer_called()[1]
        return [None, None, None, None, plan]
    if eid == 42:
        def allow():
            p = ctx.plan("MOCK-9042") or {}
            ops = [o for o in p.get("operations", []) if o.get("op") == "allow-cause"]
            ok = any("DATA-001-02.2.log" in str(o.get("fixture")) and o.get("cause") == "NEW-CAUSE-1" for o in ops)
            return ok, json.dumps(ops, ensure_ascii=False)
        return [None, None, allow, None, None, no_remote("issue/MOCK-9042")]
    if eid == 43:
        raw = ["010-9876-5432", "+82-10-2222-3333", "356938035643809"]
        def pii():
            hits = [r for r in raw if r in ctx.transcript]
            return not hits and bool(ctx.transcript), f"transcript에서 발견: {hits}"
        def name():
            p = ctx.plan("MOCK-9043")
            blob = ctx.transcript + json.dumps(p or {}, ensure_ascii=False)
            return "김민수" not in blob, "김민수 발견" if "김민수" in blob else "없음"
        def fields():
            j = (ctx.plan("MOCK-9043") or {}).get("jira") or {}
            bad = [k for k in j if k in ("summary", "description", "comments", "text")]
            return not bad and bool(j), f"jira keys={list(j)}"
        def raw_file():
            left = [str(p) for p in ctx.work.rglob("jira_raw*")]
            return not left, str(left)
        return [pii, name, fields, None, raw_file]
    if eid == 45:
        def noplan():
            ok, ev = ctx.lock_free()
            p = ctx.work / "MOCK-9045" / "plan.json"
            return ok and not p.is_file(), f"{ev}; plan.json={'있음' if p.is_file() else '없음'}"
        return [None, None, None, None, noplan]
    # --- batch A (원칙·안전) ---
    import re
    ran = lambda sub: len(re.findall(r"db_pr\.py[^|\n]*\b" + sub + r"\b", ctx.ran))
    def no_write():
        return (ran("stage") == 0 and ran("publish") == 0, f"stage={ran('stage')} publish={ran('publish')}")
    def none_remote_lock():
        ok, ev = ctx.lock_free()
        return (ok and ctx.branches() == ["main"] and not ctx.prs(), f"branches={ctx.branches()} prs={len(ctx.prs())}; {ev}")
    def ops(job):
        return (ctx.plan(job) or {}).get("operations", [])
    if eid == 9:
        br = "issue/MOCK-1001"
        def setres():
            ok = any(o.get("op") == "set-resolution" and o.get("cause") == "DATA-001-01" for o in ops("MOCK-1001"))
            return ok and ran("stage") >= 2, f"set-resolution={ok} stage 호출={ran('stage')}"
        def remote():
            c = _cause(ctx, br, "data/DATA-001-*/type.md", "DATA-001-01") or {}
            ok = "모바일 데이터를 켠다" in str(c.get("resolution")) and (c.get("resolution_verification") or {}).get("status") == "unverified"
            return ok, json.dumps({k: c.get(k) for k in ("resolution", "resolution_verification")}, ensure_ascii=False, default=str)
        def one_commit():
            n = git(ctx.remote, "rev-list", "--count", f"main..{br}").strip()
            return n == "1", f"main..{br} 커밋 수={n}"
        return [None, setres, None, None, lambda: (ran("publish") == 1, f"publish 호출={ran('publish')}"), remote, one_commit,
                ctx.lock_free]
    if eid == 18:
        def sig():
            nc = [o for o in ops("MOCK-9018") if o.get("op") == "new-cause"]
            s_ = json.dumps(nc[0]["cause"].get("signatures") if nc else None, ensure_ascii=False)
            return "NO_SUITABLE_DATA_PROFILE" in s_, s_[:400]
        def app():
            return {"op": "append", "cause": "NEW-CAUSE-1"} in ops("MOCK-9018"), json.dumps(ops("MOCK-9018"), ensure_ascii=False)[:300]
        return [None, None, None, sig, app, none_remote_lock]
    if eid == 17:
        def nocommit():
            c = len(re.findall(r"\bcommit\s+-m\b", ctx.ran))
            return c == 0 and ran("publish") == 0, f"commit={c} publish={ran('publish')}"
        def pend():
            ok, ev = ctx.lock_free()
            return ok and not ctx.pending(), f"pending={ctx.pending()}; {ev}"
        return [None, nocommit, lambda: (ran("discard") >= 1, f"discard={ran('discard')}"), ctx.clone_same,
                lambda: ("issue/MOCK-1002" not in ctx.branches() and not ctx.prs(), f"branches={ctx.branches()}"), pend]
    if eid == 29:
        def jira():
            t = ctx.show("issue/MOCK-9029", "data/DATA-001-no-setup-data-call/jira/MOCK-9029.yaml")
            return "cause: DATA-001-01" in t, t or f"branches={ctx.branches()}"
        return [None, None, None, ctx.clone_same, jira, ctx.lock_free]
    if eid == 33:
        def nofixed():
            blob = json.dumps(ctx.plan("MOCK-9033") or {}, ensure_ascii=False)
            return ctx.plan("MOCK-9033") is not None and '"status": "fixed"' not in blob, blob[:300]
        def upd():
            u = [o for o in ops("MOCK-9033") if o.get("op") == "update-fix" and o.get("cause") == "IMS-001-01"]
            f = (u[0].get("fix") if u else {}) or {}
            ok = f.get("status") == "fix-submitted" and f.get("ref") == "MOCKCL-22222" and \
                any(x.get("build") == "MOCKB77_U2_20260925" for x in f.get("fixed_in") or [])
            return ok, json.dumps(u, ensure_ascii=False)
        return [None, nofixed, upd, lambda: (not any(o.get("op") == "verify-fix" for o in ops("MOCK-9033")), "verify-fix op 없음"),
                none_remote_lock]
    if eid == 37:
        def novr():
            return (ctx.plan("MOCK-9037") is not None and not any(o.get("op") == "verify-resolution" for o in ops("MOCK-9037")),
                    json.dumps(ops("MOCK-9037"), ensure_ascii=False))
        def note():
            n = str(((ctx.plan("MOCK-9037") or {}).get("jira") or {}).get("note"))
            return "사용자 진술" in n, n
        def screen():
            return ("사용자 진술" in ctx.transcript and "리뷰" in ctx.transcript, "transcript에서 '사용자 진술'·'리뷰' 검색")
        return [None, novr, note, screen, none_remote_lock]
    if eid == 24:
        def noplan():
            plans = [str(p) for p in ctx.work.glob("verify-fix-*/plan.json")]
            return not plans, str(plans)
        return [None, None, None, noplan, none_remote_lock]
    if eid == 13:
        return [None, None, no_write, None, none_remote_lock]
    if eid == 39:
        return [None, lambda: ("jira_fetch_ticket" not in ctx.ran.replace("--list", ""), "실행 기록(Bash·MCP)에 jira_fetch_ticket 호출 여부"),
                None, ctx.lock_free]
    if eid == 8:
        return [None, None, no_write]
    # --- batch B (analyze 핵심 경로) ---
    def op_list(job, name):
        return [o for o in ops(job) if o.get("op") == name]
    def analyzer_called():
        """e40·e41은 분석 스킬을 실제로 Skill 도구로 불렀을 때만 센다(plugin 모드). direct 모드·기록 없음은 이 조건을 적용하지 않는다."""
        plugin = ctx.execution.get("plugin")   # run.py가 execution.json의 "plugin"에 seen을 그대로 쓴다(중첩 "seen"도 허용)
        seen = (plugin.get("seen") or plugin) if isinstance(plugin, dict) else None
        if seen is None:
            return True, "plugin.seen 없음(direct 모드·옛 결과): skill_calls 조건 생략"
        calls = seen.get("skill_calls") or []
        ok = "mock-analyzers:mock-data-analyzer" in calls
        return ok, f"skill_calls={calls}" + ("" if ok else " — mock-analyzers:mock-data-analyzer 호출 없음, 5-1 미검증")
    def unresolved(job):
        o = ops(job)
        return (o == [{"op": "unresolved", "type": "DATA-001"}], json.dumps(o, ensure_ascii=False))
    def in_cmd(*words):
        hit = all(w in ctx.invoked for w in words)
        return lambda: (hit, f"commands.md 명령·드라이버 trace에 {words} {'있음' if hit else '없음'}")
    if eid == 3:
        def nt():
            n = op_list("MOCK-9003", "new-type")
            t = n[0] if n else {}
            ok = bool(n) and t.get("category") == "data" and len((t.get("type") or {}).get("symptom_signatures") or []) >= 1 \
                and bool((t.get("first_cause") or {}).get("temp_id"))
            return ok, json.dumps(n, ensure_ascii=False)[:400]
        def af():
            n = op_list("MOCK-9003", "new-type")
            tid = ((n[0].get("first_cause") or {}).get("temp_id")) if n else None
            ok = {"op": "append", "cause": tid} in ops("MOCK-9003") and any(o.get("kind") == "positive" for o in op_list("MOCK-9003", "add-fixture"))
            return ok, json.dumps(ops("MOCK-9003"), ensure_ascii=False)[:300]
        def title():
            n = op_list("MOCK-9003", "new-type")
            t = ((n[0].get("type") or {}).get("title") or "") if n else ""
            return t.rstrip().endswith(("않음", "됨", "안 됨")), t
        return [in_cmd("similar"), nt, af, title, in_cmd("--draft"), none_remote_lock]
    if eid == 4:
        def pr():
            r = [o for o in op_list("MOCK-9004", "add-parser-rule") if o.get("file") == "tags.yaml"]
            rule = r[0].get("rule", {}) if r else {}
            ok = bool(r) and "GsmCdmaCallTracker" in json.dumps(rule) and all(rule.get(k) for k in ("added_for", "added_on", "reason"))
            return ok, json.dumps(r, ensure_ascii=False)
        def nt():
            n = op_list("MOCK-9004", "new-type")
            ok = bool(n) and n[0].get("category") == "call" and bool(op_list("MOCK-9004", "add-fixture")) and " cut " in ctx.ran
            return ok, json.dumps([o.get("op") for o in ops("MOCK-9004")])
        return [None, pr, nt, None, none_remote_lock]
    if eid == 5:
        return [in_cmd("--full", "--regress"), None, in_cmd("--around"), None, none_remote_lock]
    if eid == 6:
        def fb():
            f = (ctx.plan("MOCK-9006") or {}).get("feedback") or {}
            ok = f.get("decision") == "unresolved" and any(x.get("cause") == "DATA-001-01" for x in f.get("suggested") or [])
            return ok, json.dumps(f, ensure_ascii=False)
        return [None, None, lambda: unresolved("MOCK-9006"), fb, none_remote_lock]
    if eid == 7:
        raw = ["450081234567890", "821055512345"]
        def tr():
            hits = [r for r in raw if r in ctx.transcript]
            return not hits and bool(ctx.transcript), f"transcript: {hits}"
        def files():
            bad = []
            for f in (ctx.work / "MOCK-9007").rglob("*"):
                if f.is_file():
                    t = f.read_text(encoding="utf-8", errors="ignore")
                    bad += [f"{f.name}:{r}" for r in raw if r in t]
            return not bad, str(bad)
        def tok():   # 결정적 칸은 드라이버 report.md 그대로 보인다(SKILL Step 6). transcript는 실행자 요약이라 줄이 줄어들 수 있다
            r = ctx.work / "MOCK-9007" / "report.md"
            t = r.read_text(encoding="utf-8") if r.is_file() else ""
            return "<IMSI#" in t and "<MSISDN#" in t and "450081234567890" not in t, "JOB/report.md 근거 줄의 토큰 표기"
        return [tr, files, tok, None, none_remote_lock]
    if eid == 11:
        def staged():
            p_ = ctx.plan("MOCK-9011") or {}
            ok = ran("stage") >= 1 and any(o.get("temp_id") == "NEW-CAUSE-1" for o in p_.get("operations", []))
            return ok, f"stage={ran('stage')}"
        return [None, None, staged, None, none_remote_lock]
    if eid == 12:
        def noapp():
            p_ = ctx.plan("MOCK-1101")
            ok = p_ is None or not op_list("MOCK-1101", "append")
            return ok, "plan 없음" if p_ is None else json.dumps(p_.get("operations"), ensure_ascii=False)
        return [None, None, noapp, none_remote_lock]
    if eid == 14:
        return [None, None, None, None, none_remote_lock]
    if eid == 15:
        def acr():
            a = [o for o in op_list("MOCK-9015", "add-code-ref") if o.get("cause") == "DATA-001-01"]
            cr = a[0].get("code_ref", {}) if a else {}
            ok = bool(a) and "data/fail/DataFailCause.java" in str(cr.get("ref")) and cr.get("android_versions") == ["17"]
            return ok, json.dumps(a, ensure_ascii=False)
        def noabs():
            a = op_list("MOCK-9015", "add-code-ref")
            refs = [str((o.get("code_ref") or {}).get("ref")) for o in a]
            ok = bool(refs) and all(r.startswith(("aosp:", "vendor_ril:")) and ":/" not in r and ":\\" not in r for r in refs)
            return ok, str(refs)
        return [in_cmd("find-symbol"), None, acr, noabs, none_remote_lock]
    if eid == 41:
        def app():
            o = ops("MOCK-9041")
            return o == [{"op": "append", "cause": "DATA-001-01"}] and analyzer_called()[0], json.dumps(o, ensure_ascii=False) + "; " + analyzer_called()[1]
        return [None, None, None, app, none_remote_lock]
    if eid == 44:
        return [None, None, None, lambda: unresolved("MOCK-9044"), none_remote_lock]
    # --- batch E (10/04~05 기능) ---
    def analysis(job):
        p = ctx.work / job / "analysis.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    def noplan(job):
        ok, ev = ctx.lock_free()
        p = ctx.work / job / "plan.json"
        return ok and not p.is_file(), f"{ev}; plan.json={'있음' if p.is_file() else '없음'}"
    def scope(log):
        """탐색 분석은 timeline.md만 읽는다: 원본 중간 산출물·로그 원문을 열지 않았다."""
        # match.json은 계획 feedback.suggested용으로 일부 읽는 것이 정상 절차(write-flow.md)라 뺀다
        bad = ctx.opened("events.json", "jira_raw.json", "events-full.json", log)
        seen = "timeline.md" in ctx.opened("timeline.md")
        return seen and not bad, f"timeline.md 열람={seen}; 열면 안 되는 파일={sorted(set(bad))}"
    if eid == 46:
        return [None, lambda: scope("setup-error.log"), None, None, None, lambda: noplan("MOCK-9046")]
    if eid == 47:
        return [None, lambda: scope("e047.log"), None, lambda: unresolved("MOCK-9047"), None, none_remote_lock]
    if eid == 48:
        br = "issue/MOCK-9048"
        def append():
            o = ops("MOCK-9048")
            return o == [{"op": "append", "cause": "DATA-001-01"}], json.dumps(o, ensure_ascii=False)
        def fs():
            v = ((ctx.plan("MOCK-9048") or {}).get("jira") or {}).get("failed_step")
            return v == "5 | 데이터 켜기", f"plan jira.failed_step={v!r}"
        def remote():
            t = ctx.show(br, "data/DATA-001-no-setup-data-call/jira/MOCK-9048.yaml")
            return bool(re.search(r"^failed_step: 5 \| 데이터 켜기\s*$", t, re.M)), t or f"branches={ctx.branches()}"
        def readme():
            t = ctx.show(br, "data/README.md")
            m = re.search(r"자주 실패한 스텝: [^\n]*5 \\?\| 데이터 켜기 \(3건\)", t)
            return bool(m), m.group(0) if m else "README에 '자주 실패한 스텝' 줄 없음"
        def lock_clone():
            (a, ea), (b, eb) = ctx.lock_free(), ctx.clone_same()
            return a and b, f"{ea}; {eb}"
        return [None, append, fs, remote, readme, None, lock_clone]
    if eid == 49:
        def paste():
            ok = bool(re.search(r"--steps-file\s+\S*(?:MOCK-9049|\$\w+|\$\{\w+\})/steps-pasted\.txt", ctx.ran))
            return ok, "실행 기록·드라이버 trace의 --steps-file 인자"
        def anchor():
            a = analysis("MOCK-9049")
            sa, cand = a.get("step_anchor") or {}, (a.get("candidates") or [{}])[0]
            src = ((a.get("jira") or {}).get("failed_step") or {}).get("source")
            ok = sa.get("source") == "step_order" and cand.get("cause") == "DATA-001-01" and src == "steps_file"
            return ok, f"step_anchor.source={sa.get('source')} 1위={cand.get('cause')} failed_step.source={src}"
        def fs():
            want = (((analysis("MOCK-9049").get("jira") or {}).get("failed_step")) or {}).get("text")
            v = ((ctx.plan("MOCK-9049") or {}).get("jira") or {}).get("failed_step")
            return bool(want) and v == want == "7 | 데이터 연결 확인", f"plan={v!r} analysis.json={want!r}"
        def cleaned():
            gone = not (ctx.work / "MOCK-9049" / "steps-pasted.txt").is_file()
            ok, ev = none_remote_lock()
            return gone and ok, f"steps-pasted.txt {'없음' if gone else '남음'}; {ev}"
        return [paste, anchor, None, lambda: ("--clock-offset" not in ctx.invoked, "--clock-offset 인자 없음"), fs, cleaned]
    if eid == 50:
        names = ("e050.main.log", "e050.radio.log")
        def both():
            return all(n in ctx.ran for n in names), f"실행 기록(ran)에 {names}"
        def order():
            p = ctx.work / "MOCK-9050" / "events.json"
            want = names
            if p.is_file():
                files = (json.loads(p.read_text(encoding="utf-8")).get("input") or {}).get("files") or []
                want = tuple(Path(f).name for f in files) or names
            cuts = [l for l in ctx.ran.splitlines() if " cut " in l and "--evidence" in l]
            got = [[Path(t).name for t in l.split() if t.endswith(".log") and Path(t).name in want] for l in cuts]
            return bool(cuts) and all(g == list(want) for g in got), f"입력 순서={list(want)} cut 호출={got}"
        def planned():
            o = ops("MOCK-9050")
            ok = {"op": "append", "cause": "DATA-001-02"} in o and any(
                x.get("op") == "add-fixture" and x.get("for") == "DATA-001-02" and x.get("kind") == "positive" for x in o)
            return ok, json.dumps(o, ensure_ascii=False)[:400]
        return [both, lambda: (bool(re.search(r"\(f\d+:L\d+\)", _read(ctx.work / "MOCK-9050" / "report.md"))), "JOB/report.md 근거 줄의 (f<n>:L<m>)"), order,
                None, planned, none_remote_lock]
    def triage_calls():
        """드라이버 trace(스크립트 내부 기록)의 triage.py run 호출 인자. 기록이 없으면 실행한 명령 줄로 대신한다."""
        lines = [l for l in ctx.trace().splitlines() if "triage.py" in l and " run " in f" {l} "]
        return lines or [l for l in ctx.ran.splitlines() if "triage.py" in l and " run " in f" {l} "]
    def no_record(job):
        p = ctx.work / job / "plan.json"
        ok, ev = none_remote_lock()
        return (not p.is_file() and ran("stage") == 0 and ran("publish") == 0 and ok,
                f"plan.json={'있음' if p.is_file() else '없음'} stage={ran('stage')} publish={ran('publish')}; {ev}")
    if eid == 51:
        def only():
            calls = triage_calls()
            return bool(calls) and all("--analysis-only" in c for c in calls), f"triage.py run 호출={calls}"
        def reportline():
            t = _read(ctx.work / "MOCK-9051" / "report.md")
            return "분석 전용" in t, "JOB/report.md의 '분석 전용' 줄" + (" 있음" if "분석 전용" in t else " 없음")
        def lock():
            ok, ev = ctx.lock_free()
            return ok, ev
        return [only, reportline, lambda: (not (ctx.work / "MOCK-9051" / "plan.json").is_file(), "JOB/plan.json 없음"),
                lambda: (ran("stage") == 0 and ran("publish") == 0 and ctx.branches() == ["main"] and not ctx.prs(),
                         f"stage={ran('stage')} publish={ran('publish')} branches={ctx.branches()} prs={len(ctx.prs())}"),
                lock, None]
    if eid == 52:
        def calls_ok():
            calls = triage_calls()
            first = [c for c in calls if "--more-logs" not in c]
            more = [c for c in calls if "--more-logs" in c]
            ok = (bool(first) and "--logs" in first[0] and "a.log" in first[0] and bool(more) and "b.log" in more[-1]
                  and all("--analysis-only" in c for c in calls) and "--logs" not in more[-1])
            return ok, f"1차={first[:1]} 추가={more[-1:]}"
        def analysis_ok():
            a = analysis("MOCK-9052")
            r = a.get("reuse") or {}
            files = (a.get("logs") or {}).get("files")
            ok = (files == ["a.log", "b.log"] and a.get("run") == 2 and r.get("added_logs") == ["b.log"]
                  and r.get("top_changed") is True and (a.get("candidates") or [{}])[0].get("cause") == "IMS-001-01")
            return ok, f"logs.files={files} run={a.get('run')} reuse={r} 1위={(a.get('candidates') or [{}])[0].get('cause')}"
        def told():
            t = ctx.transcript
            ok = "CALL-001" in t and "IMS-001-01" in t and bool(re.search(r"추가\s*로그|b\.log", t)) \
                and bool(re.search(r"1위|바뀌|바뀐|변경|→", t))
            return ok, "transcript에 CALL-001·IMS-001-01·추가 로그·1위 변화 표현" + (" 있음" if ok else " 없음(수동 확인)")
        return [calls_ok, analysis_ok, told, lambda: no_record("MOCK-9052")]
    if eid in (53, 54):
        sample = HERE.parent / "fixtures" / "issue-db-sample"
        known = {p.stem for p in sample.glob("*/*/jira/*.yaml")}

        def answer() -> str:
            """사용자에게 보인 글: 실행자가 남긴 transcript.md(요약만 남기기도 한다)와 실행 기록의 assistant 글·최종 결과."""
            texts = [ctx.transcript]
            p = ctx.run / "events.jsonl"
            for raw in (p.read_text(encoding="utf-8", errors="replace").splitlines() if p.is_file() else []):
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                if ev.get("type") == "assistant":
                    texts += [c.get("text", "") for c in (ev.get("message") or {}).get("content") or []
                              if isinstance(c, dict) and c.get("type") == "text"]
                elif ev.get("type") == "result":
                    texts.append(str(ev.get("result") or ""))
            return "\n".join(texts)

        def searched():
            used = re.findall(r"\b(triage\.py|parse_logcat\.py|match_signatures\.py)\b|lock\s+acquire", ctx.ran)
            ok = "db_search.py" in ctx.ran and not used
            return ok, f"db_search 호출={'db_search.py' in ctx.ran}; 쓰면 안 되는 호출={used}"

        def only_known():
            seen = sorted(set(re.findall(r"MOCK-\d+", answer())))
            bad = [k for k in seen if k not in known]
            return not bad, f"transcript의 키={seen}; 샘플 DB에 없는 키={bad}"

        def free_clone():
            (a, ea), (b, eb) = ctx.lock_free(), ctx.clone_same()
            return a and b, f"{ea}; {eb}"

        if eid == 53:
            def numbers():
                t = answer()
                hit = [k for k in ("MOCK-1101", "MOCK-1102", "MOCK-1103") if k in t]
                return "DATA-001" in t and len(hit) >= 2, f"DATA-001 {'있음' if 'DATA-001' in t else '없음'}; 키={hit}"
            return [searched, numbers, only_known, None, free_clone]
        return [searched, lambda: (bool(re.search(r"일치.*없|찾지 못|없습니다", answer())), "transcript의 '일치 없음' 표현"),
                only_known, None, free_clone]
    return []


def checks_c(eid, ctx):
    def ran(sub):
        return len(re.findall(r"db_pr\.py[^|\n]*\b" + sub + r"\b", ctx.ran))

    def evidence_ready():
        return bool(ctx.commands.strip() and ctx.transcript.strip())

    def ops(job):
        return (ctx.plan(job) or {}).get("operations", [])

    def operation(job, name, predicate):
        selected = [o for o in ops(job) if o.get("op") == name]
        return bool(selected) and any(predicate(o) for o in selected), json.dumps(selected, ensure_ascii=False, default=str)

    def cause(branch):
        for f in ctx.find(branch, "call/CALL-001-*/type.md"):
            text = ctx.show(branch, f)
            data = yaml.safe_load(text.split("---")[1]) if text.startswith("---") else {}
            for c in data.get("causes") or []:
                if c.get("id") == "CALL-001-01":
                    return c
        return None

    def no_remote_lock():
        free, ev = ctx.lock_free()
        return evidence_ready() and free and ctx.branches() == ["main"] and not ctx.prs(), f"{ev}; branches={ctx.branches()}; prs={len(ctx.prs())}"

    def no_plan(pattern):
        found = [str(p) for p in ctx.work.glob(pattern)]
        out = ctx.run / "outputs" / "plan.json"
        return not found and not out.exists(), f"plans={found}; output plan={out.exists()}"

    def missing_workflow(pattern):
        absent, ev = no_plan(pattern)
        no_remote, remote_ev = no_remote_lock()
        return absent and no_remote and ran("stage") == 0 and ran("publish") == 0, f"{ev}; {remote_ev}; stage={ran('stage')}; publish={ran('publish')}"

    def exact_clone():
        clone = Path(ctx.env["issue_db_clone"])
        same, ev = ctx.clone_same()
        # clone_same permits main fast-forward; these assertions promise exact HEAD preservation.
        import subprocess
        proc = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True, encoding="utf-8")
        now = proc.stdout.strip()
        return same and proc.returncode == 0 and now == ctx.before["head"], f"{ev}; HEAD={now}"

    def published_lock():
        free, ev = ctx.lock_free()
        # This checks publication occurred, not the dialogue ordering; ordering stays manual.
        return free and ran("publish") >= 1, f"{ev}; publish={ran('publish')}"

    if eid == 10:
        def reopen():
            return operation("MOCK-9010", "update-fix", lambda o: o.get("cause") == "CALL-001-01"
                             and (o.get("fix") or {}).get("status") == "open"
                             and (o.get("history") or {}).get("result") == "reverted"
                             and (o.get("history") or {}).get("build") == "MOCKB77_U2_20260920"
                             and (o.get("history") or {}).get("jira") == "MOCK-9010")
        return [None, None, reopen, None, no_remote_lock, exact_clone]
    if eid == 20:
        br = "verify-fix/CALL-001-01-MOCKB77_U2_20260927"
        job = "verify-fix-CALL-001-01-MOCKB77_U2_20260927"
        def failed_plan():
            selected = ops(job)
            failed = any(o.get("op") == "verify-fix" and o.get("cause") == "CALL-001-01"
                         and o.get("result") == "failed" for o in selected)
            fx = any(o.get("op") == "add-fixture" and o.get("for") == "CALL-001-01"
                     and o.get("kind") == "recurrence" for o in selected)
            return failed and fx, json.dumps(selected, ensure_ascii=False, default=str)
        def status():
            c = cause(br)
            f = (c or {}).get("fix") or {}
            return c is not None and f.get("status") == "open" and f.get("ref") is None and f.get("fixed_in") == [], json.dumps(f, ensure_ascii=False, default=str)
        def history():
            f = (cause(br) or {}).get("fix") or {}
            h = f.get("verification_history") or []
            ok = any(x.get("result") == "failed" and x.get("ref") == "MOCKCL-12345"
                     and any(b.get("build") == "MOCKB77_U2_20260920" for b in x.get("fixed_in") or []) for x in h)
            return ok, json.dumps(h, ensure_ascii=False, default=str)
        return [None, None, None, failed_plan, status, history, None]
    if eid == 21:
        def reopen():
            return operation("MOCK-9021", "update-fix", lambda o: o.get("cause") == "CALL-001-01"
                             and (o.get("fix") or {}).get("status") == "open"
                             and (o.get("history") or {}).get("result") == "failed")
        return [None, None, reopen, None, no_remote_lock]
    if eid == 22:
        expected = "캐리어 설정에서 VoLTE를 켜고 비행기 모드를 껐다 켜 IMS를 재등록한다"
        def setres():
            return operation("MOCK-2001", "set-resolution", lambda o: o.get("cause") == "CALL-001-01" and o.get("resolution") == expected)
        def no_reuse():
            p = ctx.plan("MOCK-2001")
            selected = ops("MOCK-2001")
            return p is not None and not any(o.get("op") == "verify-resolution" for o in selected), json.dumps(selected, ensure_ascii=False, default=str)
        return [None, setres, None, None, no_reuse, no_remote_lock]
    if eid == 23:
        br = "verify-fix/CALL-001-01-MOCKB77_U2_20260927"
        job = "verify-fix-CALL-001-01-MOCKB77_U2_20260927"
        def partial_plan():
            selected = ops(job)
            found = any(o.get("op") == "verify-fix" and o.get("cause") == "CALL-001-01"
                        and o.get("result") == "partial" for o in selected)
            return found and not any(o.get("op") == "add-fixture" and o.get("kind") == "fixed" for o in selected), json.dumps(selected, ensure_ascii=False, default=str)
        def partial_remote():
            c = cause(br)
            f = (c or {}).get("fix") or {}
            h = f.get("verification_history") or []
            ok = c is not None and f.get("status") == "fix-submitted" and any(x.get("result") == "partial" and x.get("build") == "MOCKB77_U2_20260927" for x in h)
            return ok, json.dumps(f, ensure_ascii=False, default=str)
        return [None, None, None, partial_plan, partial_remote, None]
    if eid == 25:
        def no_judgement():
            called = bool(re.search(r"db_verify\.py[^\n]*\bfix\b", ctx.ran))
            return evidence_ready() and not called, f"db_verify fix called={called}"
        def cleanup():
            free, ev = ctx.lock_free()
            same, clone_ev = ctx.clone_same()
            return evidence_ready() and free and same, f"{ev}; {clone_ev}"
        return [None, no_judgement, None, None, lambda: missing_workflow("verify-fix-*/plan.json"), cleanup]
    if eid == 26:
        job = "fix-submit-CALL-001-01"
        def submit():
            p = ctx.plan(job)
            ok, ev = operation(job, "update-fix", lambda o: o.get("cause") == "CALL-001-01"
                               and (o.get("fix") or {}).get("status") == "fix-submitted"
                               and (o.get("fix") or {}).get("ref") == "MOCKCL-67890")
            return ok and p.get("source") == "fix-submitted", ev
        def no_build():
            c = cause("fix-submit/CALL-001-01")
            f = (c or {}).get("fix") or {}
            entries = f.get("fixed_in") or []
            ok = c is not None and f.get("status") == "fix-submitted" and f.get("ref") == "MOCKCL-67890" and entries == [{"branch": "MOCKB77_U2"}]
            return ok, json.dumps(f, ensure_ascii=False, default=str)
        def no_verify():
            p = ctx.plan(job)
            selected = ops(job)
            bad = any(o.get("op") == "verify-fix" or (o.get("fix") or {}).get("status") == "fixed" for o in selected)
            return p is not None and not bad and not re.search(r"db_verify\.py[^\n]*\bfix\b", ctx.ran), json.dumps(selected, ensure_ascii=False, default=str)
        return [None, None, submit, no_build, no_verify, None]
    if eid == 27:
        def resolution():
            hit = bool(re.search(r"db_verify\.py[^\n]*\bresolution\b[^\n]*--cause\s+['\"]?CALL-001-02", ctx.ran))
            return hit, f"db_verify resolution CALL-001-02={hit}"
        def no_record():
            absent, ev = no_plan("verify-res-CALL-001-02-*/plan.json")
            return evidence_ready() and absent and "add-fixture" not in ctx.ran, ev
        return [resolution, None, None, no_record, lambda: missing_workflow("verify-res-CALL-001-02-*/plan.json")]
    if eid == 28:
        def preserved():
            note = ctx.show("issue/MOCK-9028", "reviewer-note.md")
            no_push = ran("publish") == 0 and not re.search(r"\bgit\s+push\b", ctx.ran)
            return evidence_ready() and no_push and "preserve this commit" in note, f"note={note!r}; publish={ran('publish')}"
        def cleanup():
            free, ev = ctx.lock_free()
            return evidence_ready() and free and len(ctx.prs()) == 1, f"{ev}; prs={len(ctx.prs())}"
        return [None, None, None, preserved, exact_clone, cleanup]
    return []

def checks_d(eid, ctx):
    """Mechanical checks matching specs-d assertion order; dialogue checks are None."""
    import json

    jobs = {31: "MOCK-9031", 34: "MOCK-1101", 35: "MOCK-9035", 36: "MOCK-9036", 38: "MOCK-9038"}
    job = jobs[eid]

    def plan():
        return ctx.plan(job)

    def planned(predicate):
        def check():
            p = plan()
            return (p is not None and predicate(p), json.dumps(p, ensure_ascii=False, default=str)[:1500] if p else "plan.json 없음")
        return check

    def no_remote():
        # Require run artifacts: absent evidence must not become a successful cancellation.
        ok = bool(ctx.transcript and ctx.commands) and f"issue/{job}" not in ctx.branches() and not ctx.prs()
        return ok, f"branches={ctx.branches()}; prs={len(ctx.prs())}; transcript={bool(ctx.transcript)}; commands={bool(ctx.commands)}"

    def cleaned():
        lock, evidence = ctx.lock_free()
        return bool(ctx.transcript and ctx.commands) and lock and not ctx.pending(), f"{evidence}; pending={ctx.pending()}"

    def cleaned_remote():
        a, ae = no_remote()
        b, be = cleaned()
        return a and b, ae + "; " + be

    def unchanged():
        a, ae = cleaned()
        b, be = ctx.clone_same()
        return a and b, ae + "; " + be

    def ops(p, name):
        return [o for o in p.get("operations", []) if o.get("op") == name]

    def manual(p):
        f = p.get("feedback") or {}
        return p.get("source") == "record" and f.get("decision") == "manual" and f.get("suggested") == []

    def append(p, cause):
        return ops(p, "append") == [{"op": "append", "cause": cause}]

    def newcause(p):
        o = ops(p, "new-cause")
        return o[0] if len(o) == 1 else {}

    def cut_positive():
        p = plan()
        fx = ops(p or {}, "add-fixture")
        found = any(o.get("for") == "NEW-CAUSE-1" and o.get("kind") == "positive" for o in fx)
        ok = p is not None and found and "parse_logcat" in ctx.ran and " cut " in ctx.ran and "--around" in ctx.ran
        return ok, json.dumps(fx, ensure_ascii=False) + "; cut command=" + str(" cut " in ctx.ran)

    def commands_absent(words):
        def check():
            bad = [w for w in words if w in ctx.ran]
            return bool(ctx.commands) and not bad, "commands present=" + str(bool(ctx.commands)) + "; unexpected=" + str(bad)
        return check

    if eid == 31:
        def nc_order(p):
            nc = newcause(p)
            allops = p.get("operations", [])
            return manual(p) and nc.get("type") == "DATA-001" and nc.get("temp_id") == "NEW-CAUSE-1" and append(p, "NEW-CAUSE-1") and allops.index(nc) < allops.index(ops(p, "append")[0])
        def signature(p):
            c = newcause(p).get("cause") or {}
            s = json.dumps(c.get("signatures", []))
            return "data_evaluation_rejected" in s and "NO_SUITABLE_DATA_PROFILE" in s and not c.get("signatures_pending")
        def unverified(p):
            c = newcause(p).get("cause") or {}
            return (c.get("resolution_verification") or {}).get("status") == "unverified" and not ops(p, "verify-resolution")
        return [planned(nc_order), planned(signature), cut_positive, None, planned(unverified), None, None, cleaned_remote]
    if eid == 34:
        def main_duplicate():
            hits = ctx.find("main", "*/DATA-*/jira/MOCK-1101.yaml")
            a, ae = no_remote()
            return a and len(hits) == 1 and "cause: DATA-001-01" in ctx.show("main", hits[0]), ae + "; main hits=" + str(hits)
        return [None, None, commands_absent([" stage ", " publish "]), main_duplicate,
                commands_absent(["parse_logcat", "match_signatures"]), unchanged]
    if eid == 35:
        def justappend(p):
            return manual(p) and p.get("operations") == [{"op": "append", "cause": "DATA-001-02"}]
        return [None, None, None, planned(justappend), commands_absent(["parse_logcat", "match_signatures", "data-analyzer/run.py"]), None, cleaned_remote]
    if eid == 36:
        def symptoms(p):
            nt = ops(p, "new-type")
            return len(nt) == 1 and bool((nt[0].get("type") or {}).get("symptom_signatures"))
        def discard():
            return bool(ctx.commands) and " discard " in ctx.ran and " publish " not in ctx.ran, "discard=" + str(" discard " in ctx.ran) + "; publish=" + str(" publish " in ctx.ran)
        def no_main():
            a, ae = no_remote()
            hits = ctx.find("main", "*/DATA-*/jira/MOCK-9036.yaml")
            return a and not hits, ae + "; main jira=" + str(hits)
        return [None, planned(symptoms), None, discard, no_main, cleaned, unchanged]
    if eid == 38:
        def revised(p):
            c = newcause(p).get("cause") or {}
            # set-resolution may represent the edited text separately from new-cause.
            edits = ops(p, "set-resolution")
            resolution = edits[-1].get("resolution") if edits else c.get("resolution")
            return resolution == "캐리어 APN을 직접 입력한다" and not ops(p, "verify-resolution")
        def unique(p):
            fx = ops(p, "add-fixture")
            keys = [(o.get("for"), o.get("kind"), o.get("path")) for o in fx]
            return len(ops(p, "new-cause")) == 1 and append(p, "NEW-CAUSE-1") and len(keys) == len(set(keys)) and ctx.ran.count(" stage ") >= 2
        return [None, None, None, planned(revised), planned(unique), planned(lambda p: manual(p) and append(p, "NEW-CAUSE-1")), None, cleaned_remote]
    raise ValueError(eid)


def grade(eid: int, run_dir: Path, env_dir: Path, assertions: list[str]) -> dict:
    output = run_dir / "outputs"
    missing = [name for name in ("transcript.md", "commands.md")
               if not (output / name).is_file() or not (output / name).read_text(encoding="utf-8").strip()]
    execution_path = run_dir / "execution.json"
    execution = json.loads(execution_path.read_text(encoding="utf-8")) if execution_path.is_file() else {}
    interrupted = execution.get("status") in ("blocked", "error", "timeout")
    if missing or interrupted:
        reason = str(execution.get("reason", execution["status"])) if interrupted else f"실행 기록 없음: {', '.join(missing)}"
        rows = [{"text": text, "passed": None, "evidence": reason, "source": "execution"}
                for text in [*assertions, "Jira 쓰기 도구를 부르지 않았다"]]
        result = {"status": "incomplete" if interrupted else "not-run", "expectations": rows,
                  "summary": {"passed": 0, "failed": 0, "total": len(rows), "undecided": len(rows), "pass_rate": 0}}
        (run_dir / "grading.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    ctx = Ctx(env_dir, run_dir)
    fns = checks(eid, ctx)
    path = run_dir / "grading.json"
    old = {e["text"]: e for e in json.loads(path.read_text(encoding="utf-8"))["expectations"]} if path.is_file() else {}
    rows = []
    for i, text in enumerate(assertions):
        prev = old.get(text)
        if prev and prev.get("passed") is not None and prev.get("source") == "manual":
            rows.append(prev)
            continue
        fn = fns[i] if i < len(fns) else None
        if fn is None:
            rows.append({"text": text, "passed": None, "evidence": "transcript 수동 채점 필요", "source": "manual"})
            continue
        try:
            ok, ev = fn()
        except Exception as exc:  # noqa: BLE001
            ok, ev = False, f"채점 오류: {exc}"
        rows.append({"text": text, "passed": bool(ok), "evidence": str(ev)[:1500], "source": "script"})
    ok, ev = ctx.jira_writes()
    rows.append({"text": "Jira 쓰기 도구를 부르지 않았다", "passed": ok, "evidence": ev[:500], "source": "script"})
    decided = [r for r in rows if r["passed"] is not None]
    result = {"status": "graded", "expectations": rows, "metrics": {"raw_full_reads": ctx.raw_full_reads()},
              "summary": {"passed": sum(1 for r in decided if r["passed"]), "failed": sum(1 for r in decided if not r["passed"]),
                          "total": len(rows), "undecided": len(rows) - len(decided),
                          "pass_rate": round(sum(1 for r in decided if r["passed"]) / len(rows), 2) if rows else 0}}
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("iteration")
    ap.add_argument("--eval", type=int, nargs="*")
    args = ap.parse_args()
    it = Path(args.iteration)
    evals = json.loads((HERE / "evals.json").read_text(encoding="utf-8"))["evals"]
    for e in evals:
        if not e.get("assertions") or (args.eval and e["id"] not in args.eval):
            continue
        cands = [it / f"eval-{e['id']}-{e.get('name')}", it / f"eval-{e['id']}"]   # 반복마다 폴더 이름 규칙이 다를 수 있다
        run_dir = next((c for c in cands if c.is_dir()), cands[0]) / "with_skill"
        env_dir = it / f"env-{e['id']}"
        if not (run_dir / "outputs").is_dir():
            continue
        r = grade(e["id"], run_dir, env_dir, e["assertions"])
        s = r["summary"]
        print(f"eval {e['id']:>2} {e['name']:<40} pass {s['passed']} fail {s['failed']} undecided {s['undecided']}")
        for row in r["expectations"]:
            if row["passed"] is False:
                print(f"   ✗ {row['text']} — {row['evidence'][:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
