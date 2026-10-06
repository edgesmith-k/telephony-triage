#!/usr/bin/env python3
"""스킬 eval 채점 보조 (tests/skill_evals/README.md).

    python3 tests/skill_evals/grade.py <iteration 디렉토리>... [--eval <id>...] [--token-budget [PATH]] [--token-margin X]
                                       [--write-baseline PATH]

`evals.json`의 assertion 가운데 기계적으로 확인할 수 있는 것(원격 브랜치·파일, gh PR, 세션 lock, 사용자 clone 상태,
원문 PII 노출, Jira 쓰기 도구 호출, 계획 내용)은 여기서 판정한다. 나머지는 `passed: null`(사람·LLM이 transcript로 채점)로 남긴다.
결과는 각 run 디렉토리의 `grading.json` — skill-creator viewer 형식 `{expectations: [{text, passed, evidence}], summary}`.
수동 채점만 보존하고, 스크립트 판정은 다시 계산한다. 실행 기록이 없으면 미실행으로 남긴다.
토큰: `execution.json`의 `tokens`(run.py가 stream-json result에서 만든다)를 표로 보이고, `--token-budget`이면
`token_baseline.json` × 여유율을 상한으로 판정한다(채점 항목 하나 추가). 상세는 README "토큰 기록".
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import math
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
DEFAULT_BASELINE = HERE / "token_baseline.json"
DEFAULT_TOKEN_MARGIN = 1.3      # W0 실측으로 정함(README "토큰 기록")
TOKEN_BUDGET_TEXT = "토큰 총합 ≤ 상한(기준선 × 여유율)"   # 텍스트에 숫자를 넣지 않는다: 수동 채점 보존 키가 흔들리지 않게
sys.path.insert(0, str(HERE.parents[1] / "plugin" / "scripts"))   # guard 규칙 10의 통독 판정을 지표가 그대로 쓴다


def git(repo, *args) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return p.stdout if p.returncode == 0 else ""


_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?^\s*\2\s*$", re.S | re.M)


def _strip_heredocs(cmd: str) -> str:
    """heredoc 본문(실행자가 transcript·commands.md를 쓰는 글)은 실행한 명령이 아니다."""
    return _HEREDOC_RE.sub("<<heredoc", cmd)


class _Manual(Exception):
    """자동 판정할 근거가 없다: 수동 채점으로 넘긴다."""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


_ASK = re.compile(r"할까요|실행할까|진행할까|할지|하시겠|할래요")


def is_question(text: str, topic: str) -> bool:
    """사용자에게 묻는 문장인가: 물음표로 끝나는 문장(줄·마침표 단위) 안에 topic 정규식과 질문 어구가 함께 있다.
    '…할지 물으면 아니오로 답한다' 같은 서술·요약은 물음표로 끝나지 않으므로 질문이 아니다."""
    for chunk in re.split(r"(?<=[?？])", text):
        sent = re.split(r"[.!\n]", chunk.rstrip("?？"))[-1] if chunk.rstrip().endswith(("?", "？")) else ""
        if sent and re.search(topic, sent) and _ASK.search(sent):
            return True
    return False


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

    def needs_input(self, kind: str | None = None) -> list[str] | None:
        """드라이버가 `needs_input`으로 멈춘 kind 목록(JOB/trace.jsonl의 `step: needs_input` 줄, 모든 작업 디렉토리).
        kind를 주면 그 kind만. trace가 하나도 없으면(미실행·기록 없음) None — 0회로 세지 않는다."""
        kinds, seen = [], False
        for path in sorted(self.work.glob("*/trace.jsonl")) if self.work.is_dir() else []:
            seen = True
            for raw in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                if row.get("step") == "needs_input":
                    kinds.append(str(row.get("kind")))
        if not seen:
            return None
        return [k for k in kinds if kind is None or k == kind]

    def texts(self) -> list[str] | None:
        """assistant 텍스트 조각들(순서대로). 실행 기록(events.jsonl)이 없으면 None."""
        seq = self.seq()
        return None if seq is None else [e["text"] for e in seq if e["kind"] == "text"]

    def tool_uses(self):
        """events.jsonl의 assistant tool_use를 [(이름, 입력)]으로. 기록이 없으면 None."""
        seq = self.seq()
        if seq is None:
            return None
        return [(e["name"], e["input"]) for e in seq if e["kind"] == "tool"]

    def seq(self):
        """events.jsonl을 순서대로 [{kind:"text",text} | {kind:"tool",id,name,input,result,error}]로. 기록이 없으면 None.
        tool_use는 id가 같은 tool_result(user 이벤트)와 짝지어 result(문자열)·error(bool)를 채운다."""
        if getattr(self, "_seq", None) is not None:
            return self._seq
        p = self.run / "events.jsonl"
        if not p.is_file():
            return None
        out, by_id = [], {}
        for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            content = (ev.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict):
                    continue
                if ev.get("type") == "assistant" and c.get("type") == "tool_use":
                    e = {"kind": "tool", "id": c.get("id"), "name": c.get("name") or "", "input": c.get("input") or {},
                         "result": "", "error": False}
                    out.append(e)
                    if e["id"]:
                        by_id[e["id"]] = e
                elif ev.get("type") == "assistant" and c.get("type") == "text":
                    out.append({"kind": "text", "text": str(c.get("text") or "")})
                elif ev.get("type") == "user" and c.get("type") == "tool_result" and c.get("tool_use_id") in by_id:
                    body = c.get("content")
                    if isinstance(body, list):
                        body = "\n".join(str(b.get("text", "")) for b in body if isinstance(b, dict))
                    by_id[c["tool_use_id"]].update(result=str(body or ""), error=bool(c.get("is_error")))
        self._seq = out
        return out

    def opened(self, *names):
        """Read나 Bash 읽기(cat·head·tail·less·sed·awk·jq·grep·python)로 연 파일 중 basename이 names에 있는 것.
        triage·parse_logcat 호출 인자는 제외한다. events.jsonl이 없으면 commands.md의 읽기 명령으로 본다."""
        uses = self.tool_uses()
        if uses is None:
            return [n for n in names if re.search(r"\b(cat|head|tail|less|sed|awk|jq|grep)\b[^|\n]*" + re.escape(n), self.invoked)]
        hits = []
        for name, inp in uses:
            hits += self._opens(name, inp, names)
        return hits

    @staticmethod
    def _opens(name, inp, names) -> list[str]:
        if name == "Read" and Path(str(inp.get("file_path", ""))).name in names:
            return [Path(inp["file_path"]).name]
        if name == "Bash":
            cmd = str(inp.get("command", ""))
            if re.search(r"\b(cat|head|tail|less|sed|awk|jq|grep|python3?)\b", cmd) \
                    and "triage.py" not in cmd and "parse_logcat.py" not in cmd:
                return [n for n in names if re.search(r"(?<![\w.-])" + re.escape(n) + r"\b", cmd)]
        return []

    def explore_order(self, filename="timeline.md"):
        """(explore 호출 순번, 질문 순번, `filename` 첫 열람 순번). 순번은 seq 안의 위치, 없으면 None. 기록이 없으면 None.
        질문 = explore 호출 앞의 assistant 텍스트 중 '탐색 분석'과 '할까요/실행할까/진행할까/할지'가 함께 든 것."""
        seq = self.seq()
        if seq is None:
            return None
        explored = next((i for i, e in enumerate(seq) if e["kind"] == "tool" and e["name"] == "Bash"
                         and re.search(r"triage\.py[\"']?\s+explore\b", _strip_heredocs(str(e["input"].get("command", ""))))), None)
        asked = next((i for i, e in enumerate(seq) if e["kind"] == "text" and "탐색 분석" in e["text"]
                      and re.search(r"할까요|실행할까|진행할까|할지", e["text"]) and (explored is None or i < explored)), None)
        read = next((i for i, e in enumerate(seq) if e["kind"] == "tool" and self._opens(e["name"], e["input"], (filename,))), None)
        if explored is not None:
            # 같은 Bash 호출 안에서 explore 뒤에 filename을 읽으면 explore 뒤 열람(순번 explored+0.5). 앞이면 인정하지 않는다.
            cmd = _strip_heredocs(str(seq[explored]["input"].get("command", "")))
            m = re.search(r"triage\.py[\"']?\s+explore\b", cmd)
            same = re.search(r"\b(cat|head|tail|less|sed|awk|jq|grep)\b[^\n;&|]*" + re.escape(filename), cmd[m.end():])
            before = re.search(r"\b(cat|head|tail|less|sed|awk|jq|grep)\b[^\n;&|]*" + re.escape(filename), cmd[:m.start()])
            if before and (read is None or read >= explored):
                read = explored
            elif same and (read is None or read > explored):
                read = explored + 0.5
        return explored, asked, read

    _RAW_READ_CMD = re.compile(r"(?<![\w./-])(cat|head|less|strings|unzip)\b([^|;&\n]*)")

    def _is_raw_target(self, token: str) -> bool:
        t = token.strip("\"'")
        name = Path(t).name
        norm = t.replace("\\", "/")
        if re.search(r"(^|/)(fixtures|draft)/", norm):
            return False     # 판별 근거 주변만 잘라 마스킹한 fixture(`cut` 출력)·draft는 원문이 아니다 (상대 경로 포함)
        if name in ("events.json", "events-full.json", "jira_raw.json", "match.json") or name.endswith((".log", ".zip")):
            return True
        logs = self.env_dir / "logs"
        return "/logs/" in t.replace("\\", "/") or t.startswith("logs/") or str(logs) in t

    def _dump_reads(self, cmd: str) -> list[str]:
        """guard 규칙 10과 같은 판정: grep·awk·sed가 모든 줄을 내보내는 형태로 원문을 읽은 호출."""
        import guard
        found = []
        for inv in guard.invocations(cmd, Path(".")):
            dump = guard._dump_verb_and_files(inv)
            if dump and any(self._is_raw_target(t) for t in dump[1]):
                found.append(" ".join(inv.argv)[:200])
        return found

    def _raw_reads(self) -> tuple[list[str], list[str]]:
        """(통독 의심 호출, hook이 막은 호출). guard 규칙 10이 거부한 호출(결과가 `[telephony-triage]`를 담은
        오류)은 실제로 읽지 못했으므로 앞 목록에서 빼고 뒤 목록에 둔다."""
        hits, blocked = [], []
        for e in self.seq() or []:
            if e["kind"] != "tool":
                continue
            name, inp = e["name"], e["input"]
            found = []
            if name == "Read":
                fp = str(inp.get("file_path", ""))
                if fp and not inp.get("limit") and self._is_raw_target(fp):
                    found.append(f"Read {fp}")
            elif name == "Bash":
                cmd = _strip_heredocs(str(inp.get("command", "")))
                for m in self._RAW_READ_CMD.finditer(cmd):
                    verb, rest = m.group(1), m.group(2)
                    if verb == "head" and not re.search(r"(^|\s)-c\b", rest):
                        continue
                    if verb == "unzip" and not re.search(r"(^|\s)-\w*p", rest):
                        continue
                    if any(self._is_raw_target(t) for t in rest.split() if not t.startswith("-")):
                        found.append(f"{verb}{rest}".strip()[:200])
                found += self._dump_reads(cmd)
            (blocked if e["error"] and "[telephony-triage]" in e["result"] else hits).extend(found)
        return hits, blocked

    def raw_full_reads(self) -> list[str]:
        """원문 통독 의심(지표): 로그·zip·events.json·jira_raw.json을 Bash cat/head -c/less/strings/unzip -p 로 열거나
        limit 없는 Read로 읽은 호출 중 hook이 막지 않은 것. 채점 항목은 아니다. 실행 기록이 없으면 빈 목록."""
        return self._raw_reads()[0]

    def raw_reads_blocked(self) -> list[str]:
        """guard 규칙 10이 거부한 원문 통독 시도(지표)."""
        return self._raw_reads()[1]

    def step8_bash(self) -> dict | None:
        """Step 8 Bash 호출 수(정보성 지표, 채점 항목 아님): db_pr stage·summary·publish·discard(서브커맨드 위치만, `--then-summary`·
        `--and-discard` 같은 옵션은 세지 않는다)와 git add·git commit. 실행 기록이 없으면 None."""
        uses = self.tool_uses()
        if uses is None:
            return None
        cmds = [_strip_heredocs(str(i.get("command", ""))) for n, i in uses if n == "Bash"]
        count = {sub: sum(1 for c in cmds if re.search(r"db_pr\.py[^|\n]*(?<![-\w])" + sub + r"\b", c))
                 for sub in ("stage", "summary", "publish", "discard")}
        for sub in ("add", "commit"):
            count["git_" + sub] = sum(1 for c in cmds if re.search(r"\bgit\b[^|\n;&]*(?<![-\w])" + sub + r"\b", c))
        count["total"] = sum(count.values())
        return count

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
    if eid in (55, 56, 57, 58):
        return checks_w4(eid, ctx)
    no_remote = lambda br: (lambda: (br not in ctx.branches() and not ctx.prs(), f"branches={ctx.branches()} prs={len(ctx.prs())}"))
    def analyzer_called():
        """e40·e41은 분석 스킬을 실제로 Skill 도구로 불렀을 때만 센다(plugin 모드). direct 모드·기록 없음은 이 조건을 적용하지 않는다."""
        plugin = ctx.execution.get("plugin")   # run.py가 execution.json의 "plugin"에 seen을 그대로 쓴다(중첩 "seen"도 허용)
        seen = (plugin.get("seen") or plugin) if isinstance(plugin, dict) else None
        if seen is None:
            return True, "plugin.seen 없음(direct 모드·옛 결과): skill_calls 조건 생략"
        calls = seen.get("skill_calls") or []
        ok = "mock-analyzers:mock-data-analyzer" in calls
        return ok, f"skill_calls={calls}" + ("" if ok else " — mock-analyzers:mock-data-analyzer 호출 없음, 5-1 미검증")
    if eid == 1:
        br = "issue/MOCK-1001"
        def jira():
            t = ctx.show(br, "data/DATA-001-no-setup-data-call/jira/MOCK-1001.yaml")
            return ("cause: DATA-001-01" in t, t or f"branches={ctx.branches()}")
        def fb():
            fs = ctx.find(br, "feedback/*/MOCK-1001-*.yaml")
            d = yaml.safe_load(ctx.show(br, fs[0])) if fs else {}
            return (d.get("decision") == "accepted" and d.get("final") == "DATA-001-01", str(d) or "피드백 없음")
        def commit_via_publish():
            # W5: 커밋은 `db_pr publish --commit`이 한다. 스킬이 직접 `git commit`을 부르면 안 된다.
            if not ctx.ran.strip():
                raise _Manual("실행 기록 없음")
            flagged = re.findall(r"db_pr\.py[^|\n]*(?<![-\w])publish\b[^|\n]*(?<![-\w])--commit\b", ctx.ran)
            direct = re.findall(r"\bgit\b[^|\n;&]*(?<![-\w])commit\b", ctx.ran)
            return bool(flagged) and not direct, f"publish --commit 호출={len(flagged)} 직접 git commit={len(direct)}"
        return [None, None, None, jira, fb, lambda: (len(ctx.prs()) == 1, f"prs={len(ctx.prs())}"),
                commit_via_publish, ctx.lock_free, ctx.clone_same]
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
    ran = lambda sub: len(re.findall(r"db_pr\.py[^|\n]*(?<![-\w])" + sub + r"\b", ctx.ran))   # `--and-discard`는 discard가 아니다
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
        def doctor_table():
            """W9: 매핑이 비었을 때 `config.py doctor --format markdown` 표(jira 행 fail)를 그대로 보였다."""
            texts = ctx.texts()
            if texts is None:
                raise _Manual("실행 기록(events.jsonl) 없음")
            ran = bool(re.search(r"config\.py[\"']?\s+doctor\s+--format\s+markdown", ctx.ran))
            row = next((t for t in texts if re.search(r"\|\s*jira\s*\|\s*fail\s*\|", t)), None)
            return ran and row is not None, f"doctor 실행={ran}; jira fail 행을 담은 assistant 텍스트={'있음' if row else '없음'}"
        return [None, lambda: ("jira_fetch_ticket" not in ctx.ran.replace("--list", ""), "실행 기록(Bash·MCP)에 jira_fetch_ticket 호출 여부"),
                None, ctx.lock_free, doctor_table]
    if eid == 8:
        return [None, None, no_write]
    # --- batch B (analyze 핵심 경로) ---
    def op_list(job, name):
        return [o for o in ops(job) if o.get("op") == name]
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
        order = ctx.explore_order()
        seen = "timeline.md" in ctx.opened("timeline.md") or (order is not None and order[2] is not None)
        after, note = True, ""
        if order is not None:
            explored, _, read = order
            after = explored is not None and read is not None and read > explored
            note = f"; explore 호출 순번={explored}, timeline.md 첫 열람 순번={read}"
        return seen and not bad and after, f"timeline.md 열람={seen}; 열면 안 되는 파일={sorted(set(bad))}{note}"
    def asked_before_explore():
        """e46 1번: explore 호출 전에 '탐색 분석을 할까요' 류 질문이 있었다."""
        order = ctx.explore_order()
        if order is None:
            raise _Manual("실행 기록(events.jsonl) 없음")
        explored, asked, _ = order
        if explored is None:
            return False, "triage.py explore 호출 없음"
        if asked is None:
            return False, f"explore 호출(순번 {explored}) 앞에 '탐색 분석'+'할까요/실행할까/진행할까'가 든 assistant 텍스트 없음"
        return True, f"질문 순번={asked} < explore 호출 순번={explored}"
    if eid == 46:
        return [asked_before_explore, lambda: scope("setup-error.log"), None, None, None, lambda: noplan("MOCK-9046")]
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


def checks_w4(eid, ctx):
    """W4(질문 수 줄이기) eval 55~57. 읽을 수 없으면 _Manual(수동 채점), 통과로 세지 않는다."""
    def no_questions(kind):
        def check():
            got = ctx.needs_input(kind)
            if got is None:
                raise _Manual("JOB/trace.jsonl 없음")
            return not got, f"needs_input kind={kind} {len(got)}회"
        return check

    def said(*patterns):
        """assistant 텍스트 한 조각 안에 모든 패턴이 있다."""
        def check():
            texts = ctx.texts()
            if texts is None:
                raise _Manual("실행 기록(events.jsonl) 없음")
            hit = next((t for t in texts if all(re.search(p, t) for p in patterns)), None)
            return hit is not None, (hit[:300] if hit else f"{patterns}를 모두 담은 assistant 텍스트 없음")
        return check

    def asked(topic):
        """topic을 묻는 질문 조각 수(assistant 텍스트 중 topic과 '할까요/실행할까/진행할까/할지'가 함께 든 것). 기록 없으면 None."""
        texts = ctx.texts()
        if texts is None:
            return None
        return [t for t in texts if is_question(t, topic)]

    if eid == 58:
        def doctor_ran():
            ok = bool(re.search(r"config\.py[\"']?\s+doctor\s+--format\s+markdown", ctx.ran))
            return ok, "실행 기록에 `config.py doctor --format markdown` " + ("있음" if ok else "없음")
        def pasted():
            return said(r"\|\s*점검\s*\|\s*상태\s*\|", r"\|\s*gh\s*\|")()
        def gh_guided():
            return said(r"gh", r"auth login")()
        def untouched():
            a, ea = ctx.lock_free()
            b, eb = ctx.clone_same()
            ran = ctx.ran
            hit = re.search(r"config\.py[\"']?\s+doctor", ran)
            after = ran[hit.end():] if hit else ""     # doctor 호출 뒤에 수리 명령이 없어야 한다
            c = bool(hit) and not re.search(r"install-hooks|sync-scripts-path|config\.py\s+set\b|git\b[^\n]*\bconfig\b", after)
            return a and b and c, f"{ea}; {eb}; doctor 호출 {'있음' if hit else '없음'}, 그 뒤 수리 호출 {'없음' if c else '있음'}"
        return [doctor_ran, pasted, gh_guided, untouched]
    if eid == 55:
        def code_used():
            ok = bool(re.search(r"code_roots\.py[^\n]*android16-main", ctx.ran)) or "android16-main" in json.dumps(
                (ctx.plan("MOCK-1001") or {}), ensure_ascii=False)
            return ok, "실행 기록의 code_roots 호출에 android16-main"
        def top():
            cands = (json.loads(_read(ctx.work / "MOCK-1001" / "analysis.json") or "{}").get("candidates") or [{}])
            return cands[0].get("cause") == "DATA-001-01", f"analysis.json 1위={cands[0].get('cause')}"
        def jira():
            t = ctx.show("issue/MOCK-1001", "data/DATA-001-no-setup-data-call/jira/MOCK-1001.yaml")
            return "cause: DATA-001-01" in t, t or f"branches={ctx.branches()}"
        def lock_clone():
            (a, ea), (b, eb) = ctx.lock_free(), ctx.clone_same()
            return a and b, f"{ea}; {eb}"
        return [no_questions("code"), said(r"android16-main", r"--code"), code_used, top, jira, lock_clone]
    if eid == 56:
        job = "MOCK-8800"
        def kept():
            wt = ctx.work / job / "wt"
            branches = git(Path(ctx.env["issue_db_clone"]), "branch", "--list", f"tt/{job}").split()
            return wt.is_dir() and bool(branches), f"{wt} {'있음' if wt.is_dir() else '없음'}; tt/{job} 브랜치={'있음' if branches else '없음'}"
        def no_delete():
            if ctx.tool_uses() is None:
                raise _Manual("실행 기록(events.jsonl) 없음")
            hit = re.findall(r"db_pr\.py[^\n]*\bcleanup\b[^\n]*--yes", ctx.ran)
            return not hit, f"cleanup --yes 호출={hit}"
        def told():
            return said(r"잔여|남은|leftover", r"/telephony-triage:sync")()
        def dry():
            a, ea = ctx.lock_free()
            b, eb = ctx.clone_same()
            c = "issue/MOCK-1001" not in ctx.branches() and not ctx.prs()
            return a and b and c, f"{ea}; {eb}; branches={ctx.branches()} prs={len(ctx.prs())}"
        return [no_questions("cleanup"), kept, no_delete, told, dry]
    # eid == 57
    def analyzer_once():
        got = asked(r"심층 분석|mock-data-analyzer")
        if got is None:
            raise _Manual("실행 기록(events.jsonl) 없음")
        return len(got) == 1, f"심층 분석 질문 {len(got)}개"
    def explore_not_asked():
        got = asked(r"탐색 분석|explore")
        order = ctx.explore_order()
        if got is None or order is None:
            raise _Manual("실행 기록(events.jsonl) 없음")
        analyzer_q = [t for t in (asked(r"심층 분석|mock-data-analyzer") or []) if re.search(r"탐색", t)]
        return not got and not analyzer_q, f"탐색 질문 {len(got)}개; 심층 분석 질문에 탐색 혼입 {len(analyzer_q)}개"
    def explored_then_read():
        order = ctx.explore_order()
        if order is None:
            raise _Manual("실행 기록(events.jsonl) 없음")
        explored, _, read = order
        return explored is not None and read is not None and read > explored, f"explore 순번={explored}, timeline.md 첫 열람 순번={read}"
    def unresolved():
        o = (ctx.plan("MOCK-9044") or {}).get("operations", [])
        return o == [{"op": "unresolved", "type": "DATA-001"}] or (len(o) == 1 and o[0].get("op") == "unresolved" and o[0].get("type") == "DATA-001"), json.dumps(o, ensure_ascii=False)[:400]
    def dry():
        a, ea = ctx.lock_free()
        c = "issue/MOCK-9044" not in ctx.branches() and not ctx.prs()
        return a and c, f"{ea}; branches={ctx.branches()} prs={len(ctx.prs())}"
    return [analyzer_once, explore_not_asked, explored_then_read, unresolved, dry]


def checks_c(eid, ctx):
    def ran(sub):
        return len(re.findall(r"db_pr\.py[^|\n]*(?<![-\w])" + sub + r"\b", ctx.ran))   # `--and-discard`·`--then-summary` 제외

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
            # 판정이 나오지 않았다: 부르지 않았거나, 불렀다면 종료 코드 2로 거부되었고 그 안내(update-signature)를 보였다
            if not evidence_ready():
                return False, "실행 기록 없음"
            def flat(cmd):
                return re.sub(r"\\\n\s*", " ", _strip_heredocs(str(cmd)))     # 줄 이음(\\\n)을 한 줄로
            seq = ctx.seq()
            if seq is None:
                if re.search(r"db_verify\.py[^\n]*\bfix\b", ctx.ran):
                    raise _Manual("events.jsonl이 없어 db_verify fix 결과를 판별할 수 없다")
                return True, "db_verify fix called=0"
            bash = [e for e in seq if e["kind"] == "tool" and e["name"] == "Bash"]
            calls = [e for e in bash if re.search(r"db_verify\.py[^\n]*\bfix\b", flat(e["input"].get("command", "")))]
            # 판정 JSON은 어느 Bash 결과에 나와도 판정이 나온 것이다 (파일로 돌린 뒤 cat하는 우회)
            if any('"judgement"' in e["result"] for e in bash):
                return False, f"판정 JSON이 출력됨 (called={len(calls)})"
            if not calls:
                return True, "db_verify fix called=0"
            refused = [e for e in calls if "판정 전에 중단" in e["result"]
                       or (re.search(r"exit code:?\s*2\b", e["result"], re.I) and e["error"])]
            if len(refused) != len(calls):
                raise _Manual("db_verify fix 결과에서 종료 코드 2 거부를 확인할 수 없다")
            shown = "update-signature" in ctx.transcript
            return shown, (f"db_verify fix called={len(calls)}, 종료 코드 2 거부, 재호출={len(calls) > 1}, "
                           f"안내(update-signature) 표시={shown}")
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


# 토큰 기록 -----------------------------------------------------------------------------------
_USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
_MODEL_KEYS = ("inputTokens", "outputTokens", "cacheCreationInputTokens", "cacheReadInputTokens")
_FIELDS = ("input", "output", "cache_creation", "cache_read")


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _sum(parts):
    """하나라도 없으면(null) 합도 null — 빠진 값을 0으로 채우지 않는다."""
    return sum(parts) if parts and all(p is not None for p in parts) else None


def token_record(result) -> dict:
    """stream-json result 이벤트(또는 옛 execution.json)에서 `tokens` 기록을 만든다. None·빠진 값은 null.
    total은 modelUsage 합(서브에이전트·보조 모델 포함)이고, usage_total은 상위 usage 네 값의 합(비교용)이다."""
    r = result if isinstance(result, dict) else {}
    usage = r.get("usage") if isinstance(r.get("usage"), dict) else {}
    by_model = {}
    mu = r.get("modelUsage")
    for name, m in (mu.items() if isinstance(mu, dict) else []):
        m = m if isinstance(m, dict) else {}
        vals = [_int(m.get(k)) for k in _MODEL_KEYS]
        by_model[str(name)] = {**dict(zip(_FIELDS, vals)), "total": _sum(vals), "cost_usd": _num(m.get("costUSD"))}
    sums = [_sum([m[f] for m in by_model.values()]) for f in _FIELDS]
    return {**dict(zip(_FIELDS, sums)), "total": _sum(sums),
            "usage_total": _sum([_int(usage.get(k)) for k in _USAGE_KEYS]),
            "num_turns": _int(r.get("num_turns")), "duration_ms": _num(r.get("duration_ms")),
            "total_cost_usd": _num(r.get("total_cost_usd")),
            "by_model": by_model, "source": "modelUsage" if by_model else None}


def execution_tokens(execution: dict) -> dict | None:
    """실행 기록의 tokens. 실행하지 않았으면(기록 없음·prepared) None. 옛 execution.json은 usage에서 만든다."""
    if not execution or execution.get("status") in (None, "prepared"):
        return None
    t = execution.get("tokens")
    return t if isinstance(t, dict) else token_record(execution)


def load_baseline(path: Path) -> dict:
    """기준선 파일. 없거나 형식이 틀리면 ValueError(조용히 넘어가지 않는다)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"토큰 기준선을 읽을 수 없음: {path} ({exc})") from exc
    evals = data.get("evals") if isinstance(data, dict) else None
    if not isinstance(evals, dict) or not evals or not all(isinstance(v, dict) and _int(v.get("total")) is not None for v in evals.values()):
        raise ValueError(f"토큰 기준선 형식 오류: {path} (비어 있지 않은 evals.<id>.total 정수 필요)")
    return data


def token_limit(baseline_total: int, margin: float) -> int:
    return math.ceil(round(baseline_total * margin, 6))


def token_budget_row(eid: int, tokens: dict | None, budget: dict | None) -> dict | None:
    """상한 판정 항목. 예산을 안 쓰거나 기준선에 eval이 없거나 실행하지 않았으면 None(항목을 만들지 않는다)."""
    entry = ((budget or {}).get("baseline") or {}).get("evals", {}).get(str(eid))
    if entry is None or tokens is None:
        return None
    margin = budget["margin"]
    limit, total = token_limit(entry["total"], margin), tokens.get("total")
    if total is None:
        return {"text": TOKEN_BUDGET_TEXT, "passed": None, "evidence": "토큰 미기록(판정 보류)", "source": "script"}
    return {"text": TOKEN_BUDGET_TEXT, "passed": total <= limit, "source": "script",
            "evidence": f"total={total} 상한={limit} (기준선 {entry['total']} × 여유율 {margin})"}


def token_cells(tokens: dict | None) -> list[str]:
    """표의 토큰 칸: input·cache_create·cache_read·output·total·usage_total·turns·cost. null → 미기록, 실행 없음 → 미실행."""
    if tokens is None:
        return ["미실행"] * 8
    cost = tokens.get("total_cost_usd")
    vals = [tokens.get(k) for k in ("input", "cache_creation", "cache_read", "output", "total", "usage_total", "num_turns")]
    return ["미기록" if v is None else str(v) for v in [*vals, None if cost is None else f"{cost:.2f}"]]


def token_table(rows: list[dict]) -> str:
    """rows: {eid, status, tokens, limit(int|None), budget(bool), verdict}. 표 문자열."""
    head = ["eval", "status", "input", "cache_create", "cache_read", "output", "total", "usage_total", "turns", "cost",
            "상한", "판정"]
    body = []
    for r in rows:
        limit = "-" if not r["budget"] else ("기준선 없음" if r["limit"] is None else str(r["limit"]))
        body.append([str(r["eid"]), r["status"], *token_cells(r["tokens"]), limit, r["verdict"]])
    widths = [max(len(row[i]) for row in [head, *body]) for i in range(len(head))]
    return "\n".join(" | ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip() for row in [head, *body])


def write_baseline(path: Path, runs: dict[int, list[dict]], model: str, commit: str, dirty: bool) -> tuple[dict, dict[int, int]]:
    """runs: {eval id: [tokens...]}. total이 기록된 run만 센다(빠진 run 수는 두 번째 반환값 {eval id: 수}). 대표값은 total이 가장
    큰 run(상한 판정이 보수적). 기존 파일의 margin_default·margin_basis와 이번에 재지 않은 eval은 유지한다.
    기록할 eval이 없거나, 기존 파일이 깨졌거나, 기존 파일과 모델이 다르면 ValueError(파일을 쓰지 않는다)."""
    old = load_baseline(path) if Path(path).is_file() else {}
    if old and old.get("model") != model:
        raise ValueError(f"기존 기준선의 모델({old.get('model')})과 다르다({model}). 덮어쓰지 않는다: {path}")
    evals, skipped, recorded = dict(old.get("evals") or {}), {}, []
    for eid, items in sorted(runs.items()):
        kept = [t for t in items if t.get("total") is not None]
        if len(kept) < len(items):
            skipped[eid] = len(items) - len(kept)
        if not kept:
            continue
        recorded.append(eid)
        best = max(kept, key=lambda t: t["total"])
        evals[str(eid)] = {"total": best["total"], "num_turns": best.get("num_turns"),
                           "total_cost_usd": best.get("total_cost_usd"),
                           "runs": [{"total": t["total"], "num_turns": t.get("num_turns"),
                                     "total_cost_usd": t.get("total_cost_usd")} for t in kept]}
    if not recorded:
        raise ValueError(f"기록할 eval이 없다: total이 기록된 run 없음 (빠진 run 수 {skipped})")
    data = {"model": model, "date": date.today().isoformat(), "commit": commit, "dirty": dirty,
            "margin_default": old.get("margin_default", DEFAULT_TOKEN_MARGIN),
            "margin_basis": old.get("margin_basis", "W0 실측 전 임시값"),
            "evals": dict(sorted(evals.items(), key=lambda kv: int(kv[0])))}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data, skipped


def grade(eid: int, run_dir: Path, env_dir: Path, assertions: list[str], budget: dict | None = None) -> dict:
    """budget = {"baseline": 기준선 dict, "margin": 여유율}이면 토큰 상한 항목을 하나 더한다(없으면 기존 채점 그대로)."""
    output = run_dir / "outputs"
    missing = [name for name in ("transcript.md", "commands.md")
               if not (output / name).is_file() or not (output / name).read_text(encoding="utf-8").strip()]
    execution_path = run_dir / "execution.json"
    execution = json.loads(execution_path.read_text(encoding="utf-8")) if execution_path.is_file() else {}
    interrupted = execution.get("status") in ("blocked", "error", "timeout")
    tokens = execution_tokens(execution)
    budget_row = token_budget_row(eid, tokens, budget)
    if missing or interrupted:
        reason = str(execution.get("reason", execution["status"])) if interrupted else f"실행 기록 없음: {', '.join(missing)}"
        rows = [{"text": text, "passed": None, "evidence": reason, "source": "execution"}
                for text in [*assertions, "Jira 쓰기 도구를 부르지 않았다"]]
        rows += [budget_row] if budget_row else []
        summary = {"passed": 0, "failed": 0, "total": len(rows), "undecided": len(rows), "pass_rate": 0}
        if budget_row and budget_row["passed"] is not None:      # 상한 판정만 스크립트 결정이다(나머지는 미결정 그대로)
            ok = budget_row["passed"]
            summary.update(passed=int(ok), failed=int(not ok), undecided=len(rows) - 1, pass_rate=round(int(ok) / len(rows), 2))
        result = {"status": "incomplete" if interrupted else "not-run", "expectations": rows, "tokens": tokens,
                  "summary": summary}
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
        except _Manual as exc:
            rows.append({"text": text, "passed": None, "evidence": f"transcript 수동 채점 필요 ({exc})", "source": "manual"})
            continue
        except Exception as exc:  # noqa: BLE001
            ok, ev = False, f"채점 오류: {exc}"
        rows.append({"text": text, "passed": bool(ok), "evidence": str(ev)[:1500], "source": "script"})
    ok, ev = ctx.jira_writes()
    rows.append({"text": "Jira 쓰기 도구를 부르지 않았다", "passed": ok, "evidence": ev[:500], "source": "script"})
    rows += [budget_row] if budget_row else []
    decided = [r for r in rows if r["passed"] is not None]
    result = {"status": "graded", "expectations": rows, "tokens": tokens, "metrics": {"raw_full_reads": ctx.raw_full_reads(),
                                       "raw_reads_blocked": ctx.raw_reads_blocked(),
                                       "step8_bash": getattr(ctx, "step8_bash", lambda: None)()},
              "summary": {"passed": sum(1 for r in decided if r["passed"]), "failed": sum(1 for r in decided if not r["passed"]),
                          "total": len(rows), "undecided": len(rows) - len(decided),
                          "pass_rate": round(sum(1 for r in decided if r["passed"]) / len(rows), 2) if rows else 0}}
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _git_head() -> tuple[str, bool]:
    repo = HERE.parents[1]
    return git(repo, "rev-parse", "HEAD").strip(), bool(git(repo, "status", "--porcelain").strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("iteration", nargs="+", help="iteration 디렉토리(--write-baseline은 여러 개를 합칠 수 있다)")
    ap.add_argument("--eval", type=int, nargs="*")
    ap.add_argument("--token-budget", nargs="?", const=str(DEFAULT_BASELINE), metavar="PATH",
                    help="토큰 상한 판정(기준선 × 여유율). PATH 기본 tests/skill_evals/token_baseline.json. 반복 경로 뒤에 둔다")
    ap.add_argument("--token-margin", type=float, help="여유율(기본: 기준선의 margin_default, 없으면 DEFAULT_TOKEN_MARGIN)")
    ap.add_argument("--write-baseline", metavar="PATH", help="이번 iteration의 토큰으로 기준선 파일을 만들거나 갱신")
    args = ap.parse_args()
    budget = None
    if args.token_budget:
        try:
            baseline = load_baseline(Path(args.token_budget))
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        margin = args.token_margin if args.token_margin is not None else baseline.get("margin_default", DEFAULT_TOKEN_MARGIN)
        if _num(margin) is None or margin <= 0:
            print(f"여유율 오류: {margin!r}", file=sys.stderr)
            return 2
        budget = {"baseline": baseline, "margin": margin}
    evals = json.loads((HERE / "evals.json").read_text(encoding="utf-8"))["evals"]
    exit_code, measured, models, undetermined = 0, {}, set(), 0
    for it in map(Path, args.iteration):
        table = []
        for e in evals:
            if not e.get("assertions") or (args.eval and e["id"] not in args.eval):
                continue
            cands = [it / f"eval-{e['id']}-{e.get('name')}", it / f"eval-{e['id']}"]   # 반복마다 폴더 이름 규칙이 다를 수 있다
            run_dir = next((c for c in cands if c.is_dir()), cands[0]) / "with_skill"
            env_dir = it / f"env-{e['id']}"
            if not (run_dir / "outputs").is_dir():
                continue
            r = grade(e["id"], run_dir, env_dir, e["assertions"], budget)
            s = r["summary"]
            print(f"eval {e['id']:>2} {e['name']:<40} pass {s['passed']} fail {s['failed']} undecided {s['undecided']}")
            for row in r["expectations"]:
                if row["passed"] is False:
                    print(f"   ✗ {row['text']} — {row['evidence'][:200]}")
            tokens = r.get("tokens")
            row = next((x for x in r["expectations"] if x["text"] == TOKEN_BUDGET_TEXT), None)
            entry = ((budget or {}).get("baseline") or {}).get("evals", {}).get(str(e["id"]))
            verdict = "-" if budget is None else ("기준선 없음" if entry is None else
                      "미실행" if tokens is None else {True: "통과", False: "초과", None: "미기록"}[row["passed"]])
            if row and row["passed"] is not True:
                exit_code = 1
            table.append({"eid": e["id"], "status": r["status"], "tokens": tokens, "budget": budget is not None,
                          "limit": None if entry is None else token_limit(entry["total"], budget["margin"]), "verdict": verdict})
            if tokens is not None:
                measured.setdefault(e["id"], []).append(tokens)
                execution = json.loads(_read(run_dir / "execution.json") or "{}")
                model = execution.get("model") or execution.get("init_model")   # --model 값 → init 이벤트. by_model로 추정하지 않는다
                models.add(model) if model else None
                undetermined += not model
        if table:
            print("\n" + token_table(table))
            (it / "tokens.json").write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.write_baseline:
        if not measured or len(models) != 1 or undetermined:
            print(f"기준선을 쓰지 않음: 측정된 eval {sorted(measured)}, 모델 {sorted(models)}, 모델 미기록 run {undetermined} "
                  "(모든 run의 모델이 하나로 정해져야 한다)", file=sys.stderr)
            return 2
        commit, dirty = _git_head()
        try:
            data, skipped = write_baseline(Path(args.write_baseline), measured, next(iter(models)), commit, dirty)
        except ValueError as exc:
            print(f"기준선을 쓰지 않음: {exc}", file=sys.stderr)
            return 2
        for eid, n in skipped.items():
            print(f"eval {eid}: total 미기록 run {n}개 제외", file=sys.stderr)
        print(f"기준선 기록: {args.write_baseline} (eval {sorted(data['evals'], key=int)}, model {data['model']})")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
