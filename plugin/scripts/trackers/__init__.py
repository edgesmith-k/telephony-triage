"""트래커 레지스트리 (트래커 범용화 설계 §3-1). 핵심(guard·issuepost·jira_bridge·jira_fields·db_*)은 트래커를 모른다.

트래커 하나 = `trackers/<name>.py` 모듈 하나와 그 `SPEC: base.TrackerSpec`이다. 이 모듈은 트래커 이름을 모른다 — 이름으로
동적 import한다(`platforms.get`과 같은 방식, 이름은 `NAME_RE`, `base`·`_x`는 뺀다). 기본 이름(`DEFAULT_KIND`)은 설정에
`tracker.kind`가 없을 때만 쓴다.

- `get(kind)`: 계약 `SPEC`. `known()`: 설치된 트래커 이름.
- `kind_of(cfg)`·`of(cfg)`: 세션 설정(site-defaults + 사용자 config 병합)의 `tracker.kind`와 그 `SPEC`.
- `db_kind(db_cfg)`·`of_db(db_cfg)`: 이슈 DB `issue-db.config.yaml`의 `tracker.kind`와 그 `SPEC`.
- `mismatch(cfg, db_cfg)`: 세션 kind ≠ DB kind면 `tracker-mismatch` 문구(호출자가 종료 코드 2).
- `all_server_words()`: 설치된 **모든** 트래커 `server_words`의 합집합(guard 규칙 2 휴리스틱, 설정과 무관).

오류는 모두 `TrackerConfigError`. 파일 I/O도 전역 상태도 없다(불변 `SPEC` 캐시만). 표준 라이브러리만 쓴다(계층 규칙, base.py).
"""

from __future__ import annotations

import importlib
import pkgutil
import re

from trackers.base import TrackerConfigError, TrackerSpec  # noqa: F401  (계약 타입을 `trackers.X`로도 쓴다)

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
DEFAULT_KIND = "jira"
TRACKER_MISMATCH = "tracker-mismatch"
# 레지스트리·트래커를 불러오지 못할 때 guard 규칙 2 휴리스틱이 쓰는 내장 단어(이전 규칙 그대로 — 약해지지 않는다)
FALLBACK_SERVER_WORDS = ("jira", "atlassian")
_NOT_TRACKERS = {"base"}
_SPECS: dict[str, TrackerSpec] = {}


def known() -> list[str]:
    """설치된 트래커 이름(`trackers/` 아래 모듈, 정렬). 메시지 "지원 트래커: …"에 쓴다."""
    return sorted(
        info.name for info in pkgutil.iter_modules(__path__)
        if not info.ispkg and info.name not in _NOT_TRACKERS and NAME_RE.fullmatch(info.name)
    )


def _unsupported(kind) -> str:
    return f"지원 트래커: {', '.join(known())} ({kind!r})"


def get(kind: str) -> TrackerSpec:
    """이름 → `SPEC`. 이름 검증 → `trackers.<kind>` import → `SPEC` 타입·이름 확인. 오류는 모두 `TrackerConfigError`다 —
    트래커 모듈의 SyntaxError·하위 의존성 누락·최상위 예외도 감싼다(호출자가 종료 2·MCP 거부로 한 길로 처리한다)."""
    if not isinstance(kind, str) or not NAME_RE.fullmatch(kind) or kind in _NOT_TRACKERS:
        raise TrackerConfigError(_unsupported(kind))
    if kind in _SPECS:
        return _SPECS[kind]
    module_name = f"{__name__}.{kind}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == module_name or module_name.startswith(exc.name + ".")):
            raise TrackerConfigError(_unsupported(kind)) from exc
        raise TrackerConfigError(f"트래커 {kind}을(를) 불러오지 못했다 (ModuleNotFoundError: {exc})") from exc
    except Exception as exc:  # noqa: BLE001 — SyntaxError·ImportError·모듈 최상위 예외
        raise TrackerConfigError(f"트래커 {kind}을(를) 불러오지 못했다 ({type(exc).__name__}: {exc})") from exc
    if hasattr(module, "__path__"):
        raise TrackerConfigError(_unsupported(kind))
    spec = getattr(module, "SPEC", None)
    if not isinstance(spec, TrackerSpec):
        raise TrackerConfigError(f"{module_name}.SPEC가 TrackerSpec이 아닙니다.")
    if spec.name != kind:
        raise TrackerConfigError(f"{module_name}.SPEC.name이 모듈 이름과 다릅니다: {spec.name!r}")
    _SPECS[kind] = spec
    return spec


def _kind(cfg, where: str) -> str:
    tracker = cfg.get("tracker") if isinstance(cfg, dict) else None
    kind = tracker.get("kind") if isinstance(tracker, dict) else None
    if kind is None:
        return DEFAULT_KIND
    try:
        get(kind)
    except TrackerConfigError as exc:
        raise TrackerConfigError(f"{where} tracker.kind: {exc}") from exc
    return kind


def kind_of(cfg: dict | None) -> str:
    """세션 설정의 `tracker.kind`(없으면 `DEFAULT_KIND`). 형식이 틀리거나 설치되지 않은 이름이면 `TrackerConfigError`."""
    return _kind(cfg, "설정")


def of(cfg: dict | None) -> TrackerSpec:
    return get(kind_of(cfg))


def db_kind(db_cfg: dict | None) -> str:
    """이슈 DB 설정의 `tracker.kind`(없으면 `DEFAULT_KIND`). 잘못되면 `TrackerConfigError`."""
    return _kind(db_cfg, "이슈 DB")


def of_db(db_cfg: dict | None) -> TrackerSpec:
    return get(db_kind(db_cfg))


def mismatch(cfg: dict | None, db_cfg: dict | None) -> str | None:
    """세션 `tracker.kind`와 이슈 DB 선언이 다르면 `tracker-mismatch` 문구, 같으면 None. 키 공간·링크·도구 인자가 다른 DB에
    기록하는 것은 의미가 없으므로 **거부**다(플랫폼 불일치와 같은 근거). kind 오류는 `TrackerConfigError`."""
    session, declared = kind_of(cfg), db_kind(db_cfg)
    if session == declared:
        return None
    return (f"{TRACKER_MISMATCH} — 이슈 DB 트래커는 {declared}, 설정 tracker.kind는 {session}. "
            "config의 tracker.kind나 issue_db.path를 확인한다")


def known_server_words() -> tuple[tuple[str, ...], list[tuple[str, Exception]]]:
    """설치된 트래커 **전부**(설정과 무관)의 `server_words` 합집합(정렬)과 불러오지 못한 트래커 `(이름, 예외)` 목록.
    트래커마다 따로 불러와 하나가 깨져도 나머지는 쓴다."""
    words: set[str] = set()
    errors: list[tuple[str, Exception]] = []
    for kind in known():
        try:
            words |= {str(w).lower() for w in get(kind).server_words}
        except Exception as exc:  # noqa: BLE001 — 하위 의존성 누락·SPEC 오류 모두 그 트래커만 뺀다
            errors.append((kind, exc))
    return tuple(sorted(words)), errors


def all_server_words() -> tuple[str, ...]:
    """guard 규칙 2 서버 이름 휴리스틱 단어(정렬). 설치된 트래커 단어 합집합에 내장 `FALLBACK_SERVER_WORDS`(jira·atlassian)를
    **늘** 더한다 — jira.py가 없는 설치·깨진 트래커·레지스트리 실패에서도 이전(jira·atlassian 고정)보다 약해지지 않는다."""
    try:
        words, _errors = known_server_words()
    except Exception:  # noqa: BLE001
        words = ()
    return tuple(sorted(set(words) | set(FALLBACK_SERVER_WORDS)))
