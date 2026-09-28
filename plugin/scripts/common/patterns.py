"""정규식 실행 시간 상한 (04-parser-matching.md §5.8 (4) "정규식 안전").

규칙과 시그니처의 정규식은 모든 기여자의 매처·pre-commit·CI에서 전체 로그에 돈다.
패턴 하나가 `matcher.pattern_timeout_ms`(기본 2000)를 넘기면 그 패턴(시그니처·
extractor)을 `error`로 표시하고 분석은 계속한다.

파이썬 `re`는 실행 중에 끊을 수 없으므로 **작업 프로세스 하나**에서 패턴을 돌리고,
시간을 넘기면 그 프로세스를 끝낸 뒤(`PatternTimeout`) 다음 패턴에서 새로 띄운다.
본문(줄 목록)은 프로세스를 띄울 때 한 번만 넘긴다. 새 의존성(`regex` 모듈 등)을
쓰지 않기 위한 방식이다.

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


def _worker(conn, texts) -> None:  # 작업 프로세스
    cache: dict[str, re.Pattern] = {}
    conn.send(("ready", None))
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return
        pattern, mode, subset, indices = msg
        try:
            regex = cache.get(pattern)
            if regex is None:
                regex = cache[pattern] = re.compile(pattern)
            src = texts if subset is None else subset
            conn.send(("ok", _scan(regex, mode, src, indices)))
        except re.error as exc:
            conn.send(("error", str(exc)))


class PatternRunner:
    def __init__(self, texts, timeout_ms: int | None = DEFAULT_TIMEOUT_MS):
        self.texts = list(texts)
        self.timeout_ms = int(timeout_ms) if timeout_ms else 0
        self._proc = None
        self._conn = None

    # -- 프로세스 -------------------------------------------------------------

    def _start(self) -> None:
        ctx = multiprocessing.get_context("spawn")  # OS마다 같은 방식
        parent, child = ctx.Pipe()
        proc = ctx.Process(target=_worker, args=(child, self.texts), daemon=True)
        proc.start()
        child.close()
        if not parent.poll(_STARTUP_TIMEOUT_SEC):
            proc.kill()
            raise RuntimeError("정규식 작업 프로세스가 시작되지 않았습니다.")
        parent.recv()
        self._proc, self._conn = proc, parent

    def _stop(self, kill: bool = False) -> None:
        if self._proc is None:
            return
        try:
            if kill:
                self._proc.kill()
            else:
                self._conn.send(None)
        except (OSError, BrokenPipeError):
            pass
        self._proc.join(timeout=5)
        if self._proc.is_alive():
            self._proc.kill()
            self._proc.join(timeout=5)
        self._conn.close()
        self._proc = self._conn = None

    def close(self) -> None:
        self._stop()

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
        if self._proc is None or not self._proc.is_alive():
            self._start()
        self._conn.send((pattern, mode, None if texts is None else src, idx))
        if not self._conn.poll(self.timeout_ms / 1000):
            self._stop(kill=True)
            raise PatternTimeout(pattern, self.timeout_ms)
        status, value = self._conn.recv()
        if status == "error":
            raise PatternError(value)
        return value
