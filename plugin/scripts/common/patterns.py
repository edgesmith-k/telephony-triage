"""정규식 실행 시간 상한 (04-parser-matching.md §5.8 (4) "정규식 안전").

규칙과 시그니처의 정규식은 모든 기여자의 매처·pre-commit·CI에서 전체 로그에 돈다.
패턴 하나가 `matcher.pattern_timeout_ms`(기본 2000)를 넘기면 그 패턴(시그니처·
extractor)을 `error`로 표시하고 분석은 계속한다.

파이썬 `re`는 실행 중에 끊을 수 없으므로 **작업 프로세스 하나**에서 패턴을 돌리고,
시간을 넘기면 그 프로세스를 끝낸 뒤(`PatternTimeout`) 다음 패턴에서 새로 띄운다.
새 의존성(`regex` 모듈 등)을 쓰지 않기 위한 방식이다.

작업 프로세스는 **한 프로세스 안의 모든 `PatternRunner`가 같이 쓴다**(spawn 기동은 인터프리터와
`__main__` import를 다시 하므로 픽스처마다 띄우면 느리다). 본문(줄 목록)은 runner가 처음 패턴을 돌릴 때
한 번 보내고, 다른 runner가 끼어들어 본문을 바꿨으면 다시 보낸다. `close()`는 프로세스를 끝내지 않는다
(daemon이라 부모가 끝나면 같이 끝난다). 시간 초과로 끝낸 뒤에는 다음 패턴에서 새로 띄우고 본문을 다시 보낸다.

    with PatternRunner(texts, timeout_ms=2000) as runner:
        hits = runner.search(r"RILJ.*>\\s*SETUP_DATA_CALL")      # texts 인덱스 목록
        vals = runner.search(r".*DATA_DISABLED.*", texts=values, mode="fullmatch")
"""

from __future__ import annotations

import multiprocessing
import re

DEFAULT_TIMEOUT_MS = 2000
_STARTUP_TIMEOUT_SEC = 60.0  # 프로세스 기동(본문 전달 포함)은 상한에 넣지 않는다


class PatternTimeout(Exception):
    def __init__(self, pattern: str, timeout_ms: int):
        self.pattern = pattern
        self.timeout_ms = timeout_ms
        super().__init__(f"정규식 실행 시간 상한({timeout_ms}ms) 초과: {pattern!r}")


class PatternError(Exception):
    """정규식 컴파일 오류."""


def _scan(regex: re.Pattern, mode: str, texts, indices=None) -> list[int]:
    fn = regex.fullmatch if mode == "fullmatch" else regex.search
    if indices is not None:
        return [i for i in indices if texts[i] is not None and fn(texts[i])]
    return [i for i, text in enumerate(texts) if text is not None and fn(text)]


_TEXTS = "texts"  # 본문 교체 메시지: (_TEXTS, 줄 목록) → ("ready", None)


def _worker(conn) -> None:  # 작업 프로세스
    cache: dict[str, re.Pattern] = {}
    texts: list = []
    conn.send(("ready", None))
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return
        if msg[0] == _TEXTS:
            texts = msg[1]
            conn.send(("ready", None))
            continue
        pattern, mode, subset, indices = msg
        try:
            regex = cache.get(pattern)
            if regex is None:
                regex = cache[pattern] = re.compile(pattern)
            src = texts if subset is None else subset
            conn.send(("ok", _scan(regex, mode, src, indices)))
        except re.error as exc:
            conn.send(("error", str(exc)))


class _SharedWorker:
    """프로세스 안에서 runner들이 같이 쓰는 작업 프로세스 하나. `owner`는 지금 본문을 올려 둔 runner."""

    proc = None
    conn = None
    owner = None

    @classmethod
    def alive(cls) -> bool:
        return cls.proc is not None and cls.proc.is_alive()

    @classmethod
    def start(cls) -> None:
        cls.stop(kill=True)
        ctx = multiprocessing.get_context("spawn")  # OS마다 같은 방식
        parent, child = ctx.Pipe()
        proc = ctx.Process(target=_worker, args=(child,), daemon=True)
        proc.start()
        child.close()
        if not parent.poll(_STARTUP_TIMEOUT_SEC):
            proc.kill()
            proc.join(timeout=5)
            parent.close()
            raise RuntimeError("정규식 작업 프로세스가 시작되지 않았습니다.")
        parent.recv()
        cls.proc, cls.conn, cls.owner = proc, parent, None

    @classmethod
    def load(cls, owner, texts) -> None:
        """본문을 올린다 (전달 시간은 패턴 상한에 넣지 않는다)."""
        cls.owner = None
        cls.conn.send((_TEXTS, texts))
        if not cls.conn.poll(_STARTUP_TIMEOUT_SEC):
            cls.stop(kill=True)
            raise RuntimeError("정규식 작업 프로세스에 본문을 넘기지 못했습니다.")
        cls.conn.recv()
        cls.owner = owner

    @classmethod
    def stop(cls, kill: bool = False) -> None:
        proc, conn = cls.proc, cls.conn
        cls.proc = cls.conn = cls.owner = None
        if proc is None:
            return
        try:
            if kill:
                proc.kill()
            else:
                conn.send(None)
        except (OSError, BrokenPipeError):
            pass
        proc.join(timeout=5)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=5)
        conn.close()


class PatternRunner:
    def __init__(self, texts, timeout_ms: int | None = DEFAULT_TIMEOUT_MS):
        self.texts = list(texts)
        self.timeout_ms = int(timeout_ms) if timeout_ms else 0

    def _ready(self) -> None:
        if not _SharedWorker.alive():
            _SharedWorker.start()
        if _SharedWorker.owner is not self:
            _SharedWorker.load(self, self.texts)

    def close(self) -> None:
        """작업 프로세스는 다음 runner가 다시 쓴다. 본문을 올려 둔 것이 이 runner면 소유만 푼다."""
        if _SharedWorker.owner is self:
            _SharedWorker.owner = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- 실행 -----------------------------------------------------------------

    def search(self, pattern: str, texts=None, mode: str = "search", indices=None) -> list[int]:
        """`pattern`이 맞는 인덱스 목록. `texts`가 없으면 생성할 때 준 본문을 쓰고,
        `indices`를 주면 본문의 그 인덱스만 본다(큰 본문을 다시 보내지 않는다).
        `mode`: `search`(부분) 또는 `fullmatch`(전체)."""
        src = self.texts if texts is None else list(texts)
        if not src or (indices is not None and not indices):
            return []
        idx = None if indices is None else list(indices)
        if self.timeout_ms <= 0:
            try:
                return _scan(re.compile(pattern), mode, src, idx)
            except re.error as exc:
                raise PatternError(str(exc)) from exc
        self._ready()
        conn = _SharedWorker.conn
        conn.send((pattern, mode, None if texts is None else src, idx))
        if not conn.poll(self.timeout_ms / 1000):
            _SharedWorker.stop(kill=True)
            raise PatternTimeout(pattern, self.timeout_ms)
        status, value = conn.recv()
        if status == "error":
            raise PatternError(value)
        return value
