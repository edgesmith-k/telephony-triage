"""정규식 실행 시간 상한 (04-parser-matching.md §5.8 (4) "정규식 안전").

규칙과 시그니처의 정규식은 모든 기여자의 매처·pre-commit·CI에서 전체 로그에 돈다.
패턴 하나가 `matcher.pattern_timeout_ms`(기본 2000)를 넘기면 그 패턴(시그니처·
extractor)을 `error`로 표시하고 분석은 계속한다.

파이썬 `re`는 실행 중에 끊을 수 없으므로 **작업 프로세스 하나**에서 패턴을 돌리고,
시간을 넘기면 그 프로세스를 끝낸 뒤(`PatternTimeout`) 다음 패턴에서 새로 띄운다.
새 의존성(`regex` 모듈 등)을 쓰지 않기 위한 방식이다.

작업 프로세스는 **한 프로세스 안의 모든 `PatternRunner`가 같이 쓴다**(spawn 기동은 인터프리터와
`__main__` import를 다시 하므로 픽스처마다 띄우면 느리다). 각 runner는 생성할 때 정수 토큰을 받고, 작업
프로세스는 토큰별 본문(줄 목록)을 **최근에 쓴 4개까지** 들고 있다(LRU). 본문은 runner가 처음 패턴을 돌릴 때
한 번 보내고, 작업 프로세스가 아직 들고 있으면 다시 보내지 않는다 — runner 여러 개를 번갈아 써도(예: 픽스처마다
평가기를 두고 조건마다 픽스처를 도는 `db_verify`) 본문 업로드는 runner당 한 번이다. 부모는 어느 토큰이 올라가
있는지만 기억하고(작업 프로세스의 LRU를 그대로 따라 한다) runner 객체나 본문은 붙들지 않는다. `close()`는
그 토큰의 본문을 버리라고 알리기만 하고(응답을 기다리지 않는다) 프로세스를 끝내지 않는다(daemon이라 부모가 끝나면
같이 끝난다). 시간 초과로 끝낸 뒤에는 다음 패턴에서 새로 띄우고 본문을 다시 보낸다.

    with PatternRunner(texts, timeout_ms=2000) as runner:
        hits = runner.search(r"RILJ.*>\\s*SETUP_DATA_CALL")      # texts 인덱스 목록
        vals = runner.search(r".*DATA_DISABLED.*", texts=values, mode="fullmatch")
"""

from __future__ import annotations

import itertools
import multiprocessing
import re
from collections import OrderedDict

DEFAULT_TIMEOUT_MS = 2000
_STARTUP_TIMEOUT_SEC = 60.0  # 프로세스 기동(본문 전달 포함)은 상한에 넣지 않는다
BODY_CACHE_MAX = 4           # 작업 프로세스가 들고 있는 본문(runner) 수
_TOKENS = itertools.count(1)  # runner마다 하나씩


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


# 메시지: ("texts", 토큰, 줄 목록) → ("ready", None) | ("drop", 토큰) (응답 없음) | ("search", 토큰, 패턴, 모드, 부분 본문, 인덱스)
_TEXTS, _DROP, _SEARCH = "texts", "drop", "search"


def _worker(conn) -> None:  # 작업 프로세스
    cache: dict[str, re.Pattern] = {}
    bodies: OrderedDict[int, list] = OrderedDict()
    conn.send(("ready", None))
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return
        kind = msg[0]
        if kind == _TEXTS:
            bodies[msg[1]] = msg[2]
            bodies.move_to_end(msg[1])
            while len(bodies) > BODY_CACHE_MAX:
                bodies.popitem(last=False)
            conn.send(("ready", None))
            continue
        if kind == _DROP:
            bodies.pop(msg[1], None)
            continue
        _, token, pattern, mode, subset, indices = msg
        try:
            regex = cache.get(pattern)
            if regex is None:
                regex = cache[pattern] = re.compile(pattern)
            if subset is None:
                if token not in bodies:     # 부모의 기록과 어긋났다 — 다시 보내라고 알린다
                    conn.send(("miss", None))
                    continue
                bodies.move_to_end(token)
                src = bodies[token]
            else:
                src = subset
            conn.send(("ok", _scan(regex, mode, src, indices)))
        except re.error as exc:
            conn.send(("error", str(exc)))


class _SharedWorker:
    """프로세스 안에서 runner들이 같이 쓰는 작업 프로세스 하나. `held`는 지금 본문을 올려 둔 토큰들(오래된 것부터)이다."""

    proc = None
    conn = None
    held: OrderedDict = OrderedDict()
    loads = 0       # 본문을 올린 횟수 (누적, 테스트·진단용)

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
        cls.proc, cls.conn = proc, parent
        cls.held = OrderedDict()

    @classmethod
    def load(cls, token: int, texts) -> None:
        """본문을 올린다 (전달 시간은 패턴 상한에 넣지 않는다). 작업 프로세스의 LRU(4개)를 그대로 따라 기록한다."""
        cls.held.pop(token, None)
        cls.conn.send((_TEXTS, token, texts))
        if not cls.conn.poll(_STARTUP_TIMEOUT_SEC):
            cls.stop(kill=True)
            raise RuntimeError("정규식 작업 프로세스에 본문을 넘기지 못했습니다.")
        cls.conn.recv()
        cls.loads += 1
        cls.held[token] = None
        while len(cls.held) > BODY_CACHE_MAX:
            cls.held.popitem(last=False)

    @classmethod
    def drop(cls, token: int) -> None:
        """토큰의 본문을 버리라고 알린다 (응답을 기다리지 않는다). 작업 프로세스가 없으면 기록만 지운다."""
        if token not in cls.held:
            return
        del cls.held[token]
        if cls.alive():
            try:
                cls.conn.send((_DROP, token))
            except (OSError, BrokenPipeError):
                pass

    @classmethod
    def stop(cls, kill: bool = False) -> None:
        proc, conn = cls.proc, cls.conn
        cls.proc = cls.conn = None
        cls.held = OrderedDict()
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
        self._token = next(_TOKENS)

    def _ready(self, need_body: bool = True) -> None:
        if not _SharedWorker.alive():
            _SharedWorker.start()
        if need_body:
            if self._token in _SharedWorker.held:
                _SharedWorker.held.move_to_end(self._token)
            else:
                _SharedWorker.load(self._token, self.texts)

    def close(self) -> None:
        """작업 프로세스는 다음 runner가 다시 쓴다. 이 runner의 본문만 버리라고 알린다 (응답은 기다리지 않는다)."""
        _SharedWorker.drop(self._token)

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
        while True:
            self._ready(need_body=texts is None)
            conn = _SharedWorker.conn
            conn.send((_SEARCH, self._token, pattern, mode, None if texts is None else src, idx))
            if not conn.poll(self.timeout_ms / 1000):
                _SharedWorker.stop(kill=True)
                raise PatternTimeout(pattern, self.timeout_ms)
            status, value = conn.recv()
            if status == "miss":    # 작업 프로세스가 본문을 이미 버렸다 — 기록을 지우고 다시 올린다
                _SharedWorker.held.pop(self._token, None)
                continue
            if status == "error":
                raise PatternError(value)
            return value
