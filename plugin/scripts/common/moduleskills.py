"""모듈 스킬 레포 관리 clone: 받기(clone·fetch)·객체 저장소 점검·트리/글 점검·ff-only·cone sparse·doctor 조회.

`triage.py module`(`triagelib/modulecmd.py`)만 받고, `config.py doctor`는 `inspect_clone`(읽기 전용)만 쓴다.
JOB에는 쓰지 않는다 — 점검한 blob 바이트를 돌려주고 호출자가 쓴다(B1-6).

순서(B1 §5.4, B2 §5.2): `prepare` = 처음이면 A(임시 clone → 점검 → 바꿔 넣기) 뒤 C·E·F·G, 있으면 B·C·D·E·F·G.
`materialise` = H(모듈 찾기)·I(blob 재해시·글 점검)·J(점검한 sha로 ff-only)·K(sparse)·L. `fetch` = 둘을 잇는다.
실패는 `ModuleError(code, reason, detail)`(detail은 마스킹·≤160자, 원격 URL·자격 증명 없음).

하지 않는 것: reset·clean, 맞지 않는 clone 지우기·덮어쓰기(지우는 것은 이번 실행이 만든 첫 clone 임시 폴더뿐),
lock 훔치기·지우기, 다른 자격 증명으로 재시도, 전체 checkout, partial clone, 레포 안의 것 실행(hook·fsmonitor·submodule 끔).
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from common import masking, skillcheck

CLONE_DIR, LOCK_FILE = "_module-skills", "_module-skills.lock"
LOCK_WAIT = 30.0
LOCK_WAIT_ENV = "TT_MODULE_SKILLS_LOCK_WAIT"     # 테스트: float, [0, 30]로 자른다
NET_TIMEOUT, LOCAL_TIMEOUT = 120, 30
MIN_GIT = (2, 25)
DEEP_FILES = ("_common/layers.md", "_common/components.md", "{m}/SKILL.md", "{m}/analyzer.md")
EXPLORE_FILES = ("_common/layers.md", "_common/components.md", "{m}/explore.md")
TYPE_RE = re.compile(r"^[A-Z]+-\d{3}(-\d{2})?$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CHECKS_PASSED = ["무결성", "링크", "서브모듈", "실행 비트", "자동 읽기 이름", "허용 이름", "크기", "UTF-8", "위험 지시", "원문 열람 지시"]
CHECKS_SKIPPED = {"로그 원문": "건너뜀(E)", "사내 값": "건너뜀(E)", "D-Bus 이름": "건너뜀(E)"}
# 받기 실패 이유(종료 2). `점검(<check>)`은 skillcheck.CHECKS마다 하나
REASONS = ("관리 clone 사용 중", "인증", "네트워크", "원격 브랜치 없음", "관리 clone 불일치", "ff-only 실패", "modules.yaml",
           "sparse") + tuple(f"점검({c})" for c in skillcheck.CHECKS)

_DROP_ENV = {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
             "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_PREFIX", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
             "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_QUARANTINE_PATH", "GIT_REPLACE_REF_BASE", "GIT_GRAFT_FILE",
             "GIT_SHALLOW_FILE", "GIT_CURL_VERBOSE", "GIT_REDACT_COOKIES", "GIT_CEILING_DIRECTORIES"}
_DROP_PREFIX = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_", "GIT_TRACE")
_OUTSIDE = (".git/objects/info/alternates", ".git/objects/info/http-alternates", ".git/info/grafts", ".git/shallow",
            ".git/commondir")


class ModuleError(Exception):
    def __init__(self, code: int, reason: str, detail: str = "", extra: dict | None = None):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.code, self.reason, self.detail, self.extra = code, reason, detail, dict(extra or {})


@dataclass
class TreeState:
    platform: str
    clone: Path
    sha: str
    entries: list
    doc: dict
    modules_yaml: bytes
    tree: frozenset
    warnings: list
    lock: object
    work_dir: Path | None = None
    base: str = "main"


@dataclass
class Fetched:
    platform: str
    module: str
    sha: str
    files: list
    modules_yaml: bytes = b""
    doc: dict = field(default_factory=dict)
    tree: frozenset = frozenset()
    warnings: list = field(default_factory=list)
    with_modem: str | None = None


def _step(name: str, state=None) -> None:
    """테스트가 끼어드는 자리(B1 §10.2 lock_stolen_mid_run·ref_moved_after_check). 운영에서는 아무것도 안 한다."""


# -- git 실행 ---------------------------------------------------------------------------------------


def _env(work_dir, readonly: bool) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _DROP_ENV and not k.startswith(_DROP_PREFIX)}
    env.update({"LC_ALL": "C", "LANGUAGE": "", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "never", "GIT_HTTP_LOW_SPEED_LIMIT": "1000", "GIT_HTTP_LOW_SPEED_TIME": "30"})
    if work_dir is not None:
        env["GIT_CEILING_DIRECTORIES"] = str(work_dir)
    if readonly:
        env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _kill(proc) -> None:
    try:
        from common import mcptools
        mcptools._kill_tree(proc)
    except Exception:  # noqa: BLE001 — 정리만
        try:
            proc.kill()
        except OSError:
            pass


def _git(work_dir, cwd, *args, timeout=None, binary: bool = False, readonly: bool = False):
    """굳힌 git 실행 → (rc, out, err). 시간 초과 = (124, "", "timeout Ns"), git 없음 = (127, "", "git 없음")."""
    timeout = LOCAL_TIMEOUT if timeout is None else timeout
    cmd = ["git", "-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false", "-c", "core.symlinks=false",
           "-c", "protocol.ext.allow=never", "-c", "submodule.recurse=false", "-c", "transfer.credentialsInUrl=die",
           *(["-C", str(cwd)] if cwd else []), *map(str, args)]
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True})
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=_env(work_dir, readonly), **group)
    except FileNotFoundError:
        return 127, b"" if binary else "", "git 없음"
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill(proc)
        try:
            proc.communicate(timeout=5)
        except (subprocess.TimeoutExpired, ValueError, OSError):
            pass
        return 124, b"" if binary else "", f"timeout {timeout}s"
    text_err = err.decode("utf-8", errors="replace")
    if binary:
        return proc.returncode, out, text_err
    return proc.returncode, out.decode("utf-8", errors="surrogateescape"), text_err


def git_version() -> tuple[int, ...] | None:
    """설치된 git 버전(없거나 읽지 못하면 None)."""
    try:
        rc, out, _ = _git(None, None, "--version", timeout=LOCAL_TIMEOUT)
    except Exception:  # noqa: BLE001 — doctor·module 모두 None으로 다룬다
        return None
    m = re.search(r"git version (\d+)\.(\d+)(?:\.(\d+))?", out or "") if rc == 0 else None
    return tuple(int(g) for g in m.groups() if g is not None) if m else None


CRED_DETAIL = "URL에 자격 증명 — git credential helper를 쓴다"
_URL_PASSWORD = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://[^/?#@\s]*:[^/?#@\s]*@")


def url_has_password(remote) -> bool:
    """`scheme://user:pass@…`(비밀번호가 든 주소). git 2.37 이상은 `transfer.credentialsInUrl=die`가 막지만 MIN_GIT(2.25)~2.36은
    모르는 설정이라 그대로 보낸다 — 원격에 보내기 전에 직접 막는다. 사용자 이름만 든 주소(`user@`)는 git도 막지 않는다."""
    return bool(_URL_PASSWORD.match(str(remote or "")))


def _fatal_lines(err: str) -> list[str]:
    return [ln for ln in (err or "").splitlines() if ln.startswith(("fatal:", "error:"))]


def classify(err: str) -> str:
    """clone·fetch stderr → 이유(B1 §5.5). `fatal:`·`error:` 줄과 실행기의 `timeout ` 머리만 본다."""
    lines = _fatal_lines(err)
    text = "\n".join(lines)
    if (err or "").startswith("timeout "):
        return "네트워크"
    if "uses plaintext credentials" in text:
        return "인증"
    if re.search(r"couldn't find remote ref|Remote branch .* not found", text):
        return "원격 브랜치 없음"
    if re.search(r"Authentication failed|could not read (Username|Password)|terminal prompts disabled|Permission denied"
                 r"|Host key verification failed|returned error: 40[134]|Repository not found"
                 r"|does not appear to be a git repository|correct access rights", text):
        return "인증"
    return "네트워크"


def first_fatal(err: str, rc: int = 1) -> str:
    """사람에게 보일 한 줄: 첫 fatal/error → 첫 warning → `git 실패(rc n)`. 마스킹·≤160자, URL 자격 증명은 가린다."""
    if (err or "").startswith("timeout "):
        return "시간 초과"
    lines = _fatal_lines(err)
    if any("uses plaintext credentials" in ln for ln in lines):
        return CRED_DETAIL
    if not lines:
        lines = [ln for ln in (err or "").splitlines() if ln.startswith("warning:")]
    line = lines[0] if lines else f"git 실패(rc {rc})"
    return masking.mask_brief(re.sub(r"://[^/@\s]+@", "://<CRED>@", line), 160)


# -- lock ----------------------------------------------------------------------------------------


class LockHandle:
    def __init__(self, fd: int, path: Path):
        self.fd, self.path = fd, path

    def check(self) -> None:
        """잡은 lock 파일이 그대로인지(inode). 바뀌었으면 ModuleError — 바꾸기 전 단계마다 부른다."""
        try:
            held = os.fstat(self.fd)
            now = os.stat(self.path, follow_symlinks=False)
        except OSError:
            raise ModuleError(2, "관리 clone 사용 중", "lock 파일이 바뀌었다") from None
        if os.name == "nt" and held.st_ino == 0:
            return
        if (held.st_dev, held.st_ino) != (now.st_dev, now.st_ino):
            raise ModuleError(2, "관리 clone 사용 중", "lock 파일이 바뀌었다")


def _lock_wait(wait: float | None) -> float:
    if wait is not None:
        return max(0.0, min(LOCK_WAIT, float(wait)))
    try:
        return max(0.0, min(LOCK_WAIT, float(os.environ[LOCK_WAIT_ENV])))
    except (KeyError, ValueError):
        return LOCK_WAIT


@contextlib.contextmanager
def clone_lock(work_dir: Path, wait: float | None = None):
    """`<work_dir>/_module-skills.lock` flock(기한 30초). 놓을 때 닫기만 하고 지우지 않는다."""
    path = Path(work_dir) / LOCK_FILE
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError:
        raise ModuleError(2, "관리 clone 불일치", "lock 파일이 링크다" if os.path.islink(path) else "lock 파일을 열지 못했다") from None
    try:
        limit = _lock_wait(wait)
        deadline = time.monotonic() + limit
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, 0)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ModuleError(2, "관리 clone 사용 중", f"{limit:.0f}초 안에 lock을 못 잡았다") from None
                time.sleep(0.1)
        handle = LockHandle(fd, path)
        handle.check()
        yield handle
    finally:
        os.close(fd)


# -- 원격·preflight --------------------------------------------------------------------------------


def norm_remote(url: str) -> str:
    """비교용 원격: userinfo 빼고 scheme·host 소문자, 끝 `/`·`.git` 제거, file://은 realpath, scp 형식 → scp://host/path."""
    u = str(url or "").strip()

    def tail(p: str) -> str:
        p = p.rstrip("/")
        return p.removesuffix(".git")

    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*)://(.*)$", u)
    if m:
        scheme, rest = m.group(1).lower(), m.group(2)
        if scheme == "file":
            return "file://" + tail(os.path.realpath(rest if rest.startswith("/") else "/" + rest.partition("/")[2]))
        host, _, path = rest.partition("/")
        return f"{scheme}://{host.rsplit('@', 1)[-1].lower()}/{tail(path)}"
    m = re.match(r"^(?:[^@/\s]+@)?([^:/\s]+):(.+)$", u)
    if m:
        return f"scp://{m.group(1).lower()}/{tail(m.group(2).lstrip('/'))}"
    return tail(u)


def _mismatch(detail: str) -> ModuleError:
    return ModuleError(2, "관리 clone 불일치", detail)


def _shape(clone: Path) -> None:
    if os.path.islink(clone) or not clone.is_dir():
        raise _mismatch("_module-skills가 디렉토리가 아니다")


def _out(work, clone, *args, readonly=False, what="관리 clone 불일치", detail=None) -> str:
    rc, out, err = _git(work, clone, *args, readonly=readonly)
    if rc != 0:
        raise ModuleError(2, what, detail or first_fatal(err, rc))
    return out


def _allowed_local(base: str) -> set[str]:
    return {"core.repositoryformatversion", "core.filemode", "core.bare", "core.logallrefupdates", "core.symlinks",
            "core.ignorecase", "core.precomposeunicode", "remote.origin.url", "remote.origin.fetch", "remote.origin.tagopt",
            "extensions.worktreeconfig", f"branch.{base}.remote", f"branch.{base}.merge"}


def _refspec(base: str) -> str:
    """`clone --single-branch --branch <base>`이 쓰는 refspec. 받기는 이것을 명시하고, 설정 값도 이것만 받는다."""
    return f"+refs/heads/{base}:refs/remotes/origin/{base}"


def _outside_refs(clone: Path) -> None:
    for rel in _OUTSIDE:
        if os.path.lexists(clone / rel):
            raise _mismatch(f"객체 저장소 밖 참조: {rel.rsplit('/', 1)[-1]}")


def _refs(work, clone, base, readonly=False) -> None:
    allowed = {f"refs/heads/{base}", f"refs/remotes/origin/{base}", "refs/remotes/origin/HEAD"}
    out = _out(work, clone, "for-each-ref", "--format=%(refname)", readonly=readonly)
    for ref in out.split():
        if ref not in allowed:
            raise _mismatch(f"참조 밖: {masking.mask_brief(ref, 80)}")


def _fsck(work, clone) -> None:
    rc, _, _ = _git(work, clone, "fsck", "--full", "--strict", "--no-dangling", "--no-progress")
    if rc != 0:
        raise _mismatch("객체 저장소 점검 실패(git fsck)")


def _preflight(work, clone: Path, remote: str, base: str, readonly: bool = False) -> None:
    """C1–C11(B1 §5.4 C). 첫 실패 → 관리 clone 불일치(강제 push는 ff-only 실패, extra forced)."""
    ro = {"readonly": readonly}
    git_dir = clone / ".git"
    if os.path.islink(git_dir) or not git_dir.is_dir():
        raise _mismatch(".git이 디렉토리가 아니다")
    _outside_refs(clone)
    top = _out(work, clone, "rev-parse", "--show-toplevel", **ro).strip()
    if os.path.realpath(top) != os.path.realpath(clone):
        raise _mismatch("최상위가 다르다")
    rc, head, _ = _git(work, clone, "symbolic-ref", "-q", "HEAD", **ro)
    if rc != 0 or head.strip() != f"refs/heads/{base}":
        raise _mismatch(f"브랜치가 {base}가 아니다 — base_branch를 바꿨으면 사용자가 관리 clone을 지운다")
    allowed = _allowed_local(base)
    for key in _out(work, clone, "config", "--local", "--name-only", "--list", **ro).split():
        if key not in allowed and key.lower() not in allowed:
            raise _mismatch(f"설정 키 밖: {masking.mask_brief(key, 80)}")
    rc, out, _ = _git(work, clone, "config", "--worktree", "--name-only", "--list", **ro)
    for key in (out.split() if rc == 0 else []):
        if key.lower() not in {"core.sparsecheckout", "core.sparsecheckoutcone"}:
            raise _mismatch(f"설정 키 밖: {masking.mask_brief(key, 80)}")
    # 모든 범위(system·global·local·include)에서 값이 정확히 하나여야 한다: `config --get`은 마지막 값만 보지만 이름 있는 원격
    # fetch는 첫 값을 쓴다(값 둘이면 점검과 받기가 다른 주소를 본다). 받기는 주소·refspec을 명시하지만 doctor도 같이 막는다.
    rc, url, _ = _git(work, clone, "config", "--get-all", "remote.origin.url", **ro)
    urls = url.splitlines() if rc == 0 else []
    if len(urls) != 1 or norm_remote(urls[0].strip()) != norm_remote(remote):
        raise _mismatch("origin이 module_skills.remote와 다르다" if len(urls) <= 1 else "remote.origin.url 값이 여러 개다")
    rc, fetch, _ = _git(work, clone, "config", "--get-all", "remote.origin.fetch", **ro)
    if rc != 0 or fetch.splitlines() != [_refspec(base)]:
        raise _mismatch("remote.origin.fetch가 기본값이 아니다")
    rc, tagopt, _ = _git(work, clone, "config", "--get-all", "remote.origin.tagopt", **ro)
    if rc == 0 and tagopt.splitlines() != ["--no-tags"]:
        raise _mismatch("remote.origin.tagopt가 기본값이 아니다")
    _refs(work, clone, base, readonly)
    for key in ("core.sparseCheckout", "core.sparseCheckoutCone"):
        rc, val, _ = _git(work, clone, "config", "--get", key, **ro)
        if rc != 0 or val.strip() != "true":
            raise _mismatch("cone sparse가 아니다")
    if _out(work, clone, "status", "--porcelain=v1", "-z", "--ignored=matching", "--untracked-files=all", **ro):
        raise _mismatch("작업 트리가 깨끗하지 않다")
    ref = f"refs/remotes/origin/{base}"
    count = _out(work, clone, "rev-list", "--count", f"{ref}..HEAD", **ro).strip()
    if count != "0":
        head_sha = _out(work, clone, "rev-parse", "HEAD", **ro).strip()
        log = git_dir / "logs" / "refs" / "remotes" / "origin" / base
        seen: set[str] = set()
        try:
            if log.is_file() and not log.is_symlink():
                for line in log.read_text("utf-8", errors="replace").splitlines():
                    seen.update(line.split()[:2])
        except OSError:
            pass
        if head_sha in seen:
            raise ModuleError(2, "ff-only 실패", "원격 브랜치가 강제로 바뀌었다 — 관리 clone을 지우고 다시 받는다",
                              {"forced": True})
        raise _mismatch("로컬 커밋이 있다")


def inspect_clone(work_dir: Path, remote: str, base: str) -> dict:
    """doctor용 읽기 전용 조회(lock·fetch·쓰기·fsck 없음): state absent | ok | mismatch | forced."""
    clone = Path(work_dir) / CLONE_DIR
    if not os.path.lexists(clone):
        return {"state": "absent", "sha": None, "problem": None}
    try:
        _shape(clone)
        _preflight(work_dir, clone, remote, base, readonly=True)
        sha = _out(work_dir, clone, "rev-parse", "HEAD", readonly=True).strip()
    except ModuleError as exc:
        return {"state": "forced" if exc.extra.get("forced") else "mismatch", "sha": None, "problem": exc.detail}
    except Exception as exc:  # noqa: BLE001 — doctor는 멈추지 않는다
        return {"state": "mismatch", "sha": None, "problem": masking.mask_brief(str(exc), 160)}
    return {"state": "ok", "sha": sha, "problem": None}


# -- 받기 ----------------------------------------------------------------------------------------


def _tree_entries(work, clone, rev: str) -> list:
    rc, out, _ = _git(work, clone, "ls-tree", "-r", "-l", "-z", "--full-tree", rev)
    if rc != 0:
        raise ModuleError(2, "점검(트리)", "ls-tree 실패")
    try:
        return skillcheck.parse_ls_tree(out)
    except ValueError:
        raise ModuleError(2, "점검(트리)", "ls-tree 형식") from None


def _check_tree(entries) -> None:
    found = skillcheck.check_tree(entries)
    if found:
        f = found[0]
        raise ModuleError(2, f"점검({f['check']})", masking.mask_brief(f["path"], 160))


def _blob(work, clone, entry) -> bytes:
    rc, data, _ = _git(work, clone, "cat-file", "blob", entry.sha, binary=True)
    if rc != 0 or hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() != entry.sha:
        raise ModuleError(2, "점검(읽기)", masking.mask_brief(entry.path, 160))
    return data


def _new_sha(work, clone, base) -> str:
    rc, out, _ = _git(work, clone, "rev-parse", "--verify", f"refs/remotes/origin/{base}^{{commit}}")
    new = out.strip() if rc == 0 else ""
    if not SHA_RE.fullmatch(new):
        raise ModuleError(2, "점검(트리)", "원격 브랜치 커밋을 읽지 못했다")
    return new


def _same_as_fetched(work, clone, base: str) -> None:
    """받은 뒤 `origin/<base>` = 이번 받기의 `FETCH_HEAD`인지 본다. 다르면 받은 커밋이 아닌 것이 참조에 남았다."""
    rc, out, _ = _git(work, clone, "rev-parse", "--verify", "-q", "FETCH_HEAD^{commit}")
    fetched = out.strip() if rc == 0 else ""
    if not SHA_RE.fullmatch(fetched) or _new_sha(work, clone, base) != fetched:
        raise _mismatch(f"origin/{base}가 받은 커밋(FETCH_HEAD)과 다르다")


def _first_clone(work: Path, clone: Path, remote: str, base: str) -> None:
    tmp = work / f"{CLONE_DIR}.tmp-{os.getpid()}-{time.time_ns()}"
    try:
        rc, _, err = _git(work, None, "clone", "--no-checkout", "--sparse", "--single-branch", "--no-tags", "--branch",
                          base, "--", remote, str(tmp), timeout=NET_TIMEOUT)
        if rc != 0:
            raise ModuleError(2, classify(err), first_fatal(err, rc))
        _out(work, tmp, "sparse-checkout", "init", "--cone", what="sparse")
        _outside_refs(tmp)
        _refs(work, tmp, base)
        _fsck(work, tmp)
        _check_tree(_tree_entries(work, tmp, _new_sha(work, tmp, base)))
        _out(work, tmp, "checkout", "-q", base, what="sparse")
        os.replace(tmp, clone)
    finally:
        if os.path.lexists(tmp):
            shutil.rmtree(tmp, ignore_errors=True)


def prepare(work_dir, remote, base, *, lock, platform) -> TreeState:
    """B1 §5.4 A–G: clone 또는 fetch, 객체 저장소·트리 점검, modules.yaml 읽기. HEAD는 움직이지 않는다(ff는 materialise)."""
    if url_has_password(remote):            # 보내기 전에(git 2.37 미만은 credentialsInUrl=die를 모른다)
        raise ModuleError(2, "인증", CRED_DETAIL)
    work = Path(work_dir)
    clone = work / CLONE_DIR
    if not os.path.lexists(clone):
        _first_clone(work, clone, remote, base)
        _shape(clone)
        _preflight(work, clone, remote, base)
    else:
        _shape(clone)
        _preflight(work, clone, remote, base)
        _fsck(work, clone)
        # 이름(`origin`)이 아니라 설정된 주소와 refspec을 명시한다: 설정 파일의 `remote.origin.*`(값 여럿·바꾼 refspec·
        # global 값)이 받을 주소와 갱신할 참조를 바꾸지 못한다
        rc, _, err = _git(work, clone, "fetch", "--no-tags", "--", remote, _refspec(base),
                          timeout=NET_TIMEOUT)
        if rc != 0:
            raise ModuleError(2, classify(err), first_fatal(err, rc))
        _refs(work, clone, base)
        _fsck(work, clone)
        _same_as_fetched(work, clone, base)
    new = _new_sha(work, clone, base)
    entries = _tree_entries(work, clone, new)
    _check_tree(entries)
    by_path = {e.path: e for e in entries}
    if "modules.yaml" not in by_path:
        raise ModuleError(2, "modules.yaml", "modules.yaml 없음")
    data = _blob(work, clone, by_path["modules.yaml"])
    try:
        doc = skillcheck.load_modules_yaml(data)
        errs = skillcheck.validate_modules(doc)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ModuleError(2, "modules.yaml", masking.mask_brief(str(exc), 160)) from None
    except Exception as exc:  # noqa: BLE001 — yaml.YAMLError 등
        raise ModuleError(2, "modules.yaml", masking.mask_brief(f"YAML 오류: {type(exc).__name__}", 160)) from None
    if errs:
        raise ModuleError(2, "modules.yaml", masking.mask_brief(errs[0], 160))
    warnings = [f"modules.yaml 모르는 키 무시: {p}" for p in skillcheck.unknown_keys(doc)]
    return TreeState(platform, clone, new, entries, skillcheck.strip_unknown(doc), data,
                     frozenset(by_path), warnings, lock, work, base)


def _missing(platform: str, x: str, sha: str) -> ModuleError:
    return ModuleError(1, f"레포에 {platform}/{x} 없음", "modules.yaml 또는 필요한 문서가 없다",
                       {"module": f"{platform}/{x}", "sha": sha})


def materialise(state, *, purpose, module=None, category=None, type_id=None, also=False, deep=False) -> Fetched:
    """B1 §5.4 H–L on state.sha: 모듈 찾기 → blob 재해시·글 점검 → (lock 확인) ff-only → (lock 확인) sparse.
    `deep`(explore 정밀 탐색): EXPLORE_FILES 뒤에 `{m}/deep.md`."""
    _step("H", state)
    p, sha, tree = state.platform, state.sha, state.tree
    block = (state.doc.get("platforms") or {}).get(p)
    mods = (block or {}).get("modules") or {}
    if block is None:
        raise _missing(p, module or category or "?", sha)
    if module is not None:
        if module not in mods:
            raise _missing(p, module, sha)
        m = module
    else:
        hits = [d for d, b in mods.items() if isinstance(b, dict) and b.get("db_category") == category]
        if len(hits) != 1:
            raise _missing(p, category or "?", sha)
        m = hits[0]
    names = DEEP_FILES if purpose == "deep" else EXPLORE_FILES + (("{m}/deep.md",) if deep else ())
    paths = [f"{p}/{n.format(m=m)}" for n in names]
    if any(x not in tree for x in paths):
        raise _missing(p, m, sha)
    if purpose == "deep" and isinstance(type_id, str) and TYPE_RE.fullmatch(type_id):
        ref = f"{p}/{m}/references/{type_id}.md"
        if ref in tree:
            paths.append(ref)
    dirs = [f"{p}/_common", f"{p}/{m}"]
    modem = None
    if also and purpose == "deep":
        cands = [d for d, b in mods.items() if isinstance(b, dict) and b.get("db_category") == "common"]
        modem = cands[0] if len(cands) == 1 else None
        if modem is None or f"{p}/{modem}/SKILL.md" not in tree:
            raise _missing(p, modem or "modem", sha)
        if modem != m:
            paths.append(f"{p}/{modem}/SKILL.md")
            dirs.append(f"{p}/{modem}")
    by_path = {e.path: e for e in state.entries}
    work, clone = state.work_dir, state.clone
    files = []
    for path in paths:
        data = _blob(work, clone, by_path[path])
        found = skillcheck.check_text(path, data)
        if found:
            f = found[0]
            where = f"{f['path']}:{f['line']}" if "line" in f else f["path"]
            raise ModuleError(2, f"점검({f['check']})", masking.mask_brief(where, 160))
        files.append((path, data))
    _step("J", state)
    state.lock.check()
    rc, _, err = _git(work, clone, "merge", "--ff-only", "-q", sha)
    if rc != 0:
        raise ModuleError(2, "ff-only 실패", first_fatal(err, rc))
    head = _out(work, clone, "rev-parse", "HEAD", what="ff-only 실패").strip()
    rc, now, _ = _git(work, clone, "rev-parse", f"refs/remotes/origin/{state.base}")
    if head != sha or rc != 0 or now.strip() != sha:
        raise ModuleError(2, "ff-only 실패", "HEAD·origin이 점검한 커밋과 다르다")
    _step("K", state)
    state.lock.check()
    _out(work, clone, "sparse-checkout", "set", *dirs, what="sparse")
    rc, val, _ = _git(work, clone, "config", "--get", "core.sparseCheckoutCone")
    if rc != 0 or val.strip() != "true":
        raise ModuleError(2, "sparse", "cone sparse가 아니다")
    listed = _out(work, clone, "sparse-checkout", "list", what="sparse").split()
    if listed != sorted(dirs):
        raise ModuleError(2, "sparse", "sparse 목록이 다르다")
    if _out(work, clone, "status", "--porcelain=v1", "-z", "--ignored=matching", "--untracked-files=all", what="sparse"):
        raise ModuleError(2, "sparse", "작업 트리가 깨끗하지 않다")
    return Fetched(p, m, sha, files, state.modules_yaml, state.doc, tree, list(state.warnings),
                   modem if modem and modem != m else None)


def fetch(work_dir, remote, base, *, lock, platform, purpose, module=None, category=None, type_id=None,
          also=False) -> Fetched:
    """= materialise(prepare(...), ...) (B1의 서명 + also)."""
    state = prepare(work_dir, remote, base, lock=lock, platform=platform)
    return materialise(state, purpose=purpose, module=module, category=category, type_id=type_id, also=also)
