"""분석 환경 출처 기록 (B2-7, MODULE_SKILLS_DECISIONS 11/05 ① "출처 기록").

환경 변수와 site-defaults 키 하나(`runtime.label`)만 본다 — 모델에게 묻지 않는다(약한 모델은 잘못 말할 수 있다).
`TT_RUNTIME`/`TT_MODEL`(OpenCode 셈, 계획 I O2a) 먼저, 그다음 `CLAUDECODE`·`ANTHROPIC_MODEL`·`ANTHROPIC_DEFAULT_*_MODEL`·
`ANTHROPIC_SMALL_FAST_MODEL`. `gateway`는 `ANTHROPIC_BASE_URL`의 종류(anthropic|other|none)만 — 주소는 남기지 않는다.
`cfg`는 **site-defaults dict**다(`runtime`은 site 전용 키라 merged cfg에 없다). 변수가 Bash까지 오지 않으면 "모름"·{}·none
(틀리지는 않는다). 예외를 내지 않는다.
"""

from __future__ import annotations

import os
import re

_HOST = re.compile(r"^https?://([^/:?#@]+@)?([^/:?#]+)", re.IGNORECASE)
_LABEL = re.compile(r"[A-Za-z0-9._ +-]{1,40}")
_UNKNOWN = "모름"


def _clean(v) -> str | None:
    return re.sub(r"[^A-Za-z0-9._:+/@\[\]-]", "", str(v or ""))[:60] or None


def env_info(environ=None, cfg=None) -> dict:
    """`{"runtime", "model", "model_defaults": {opus?, sonnet?, haiku?, small?}, "gateway", "label"}`."""
    try:
        env = os.environ if environ is None else environ
        runtime = _clean(env.get("TT_RUNTIME")) or ("claude-code" if env.get("CLAUDECODE") == "1" else None) or _UNKNOWN
        model = _clean(env.get("TT_MODEL")) or _clean(env.get("ANTHROPIC_MODEL")) or _UNKNOWN
        defaults = {k: v for k, v in (("opus", _clean(env.get("ANTHROPIC_DEFAULT_OPUS_MODEL"))),
                                      ("sonnet", _clean(env.get("ANTHROPIC_DEFAULT_SONNET_MODEL"))),
                                      ("haiku", _clean(env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL"))),
                                      ("small", _clean(env.get("ANTHROPIC_SMALL_FAST_MODEL")))) if v}
        base = str(env.get("ANTHROPIC_BASE_URL") or "").strip()
        m = _HOST.match(base)
        host = m.group(2).lower() if m else ""
        gateway = "none" if not base else ("anthropic" if host == "anthropic.com" or host.endswith(".anthropic.com")
                                           else "other")
        rt = cfg.get("runtime") if isinstance(cfg, dict) else None
        label = rt.get("label") if isinstance(rt, dict) else None
        label = label if isinstance(label, str) and _LABEL.fullmatch(label) else None
        return {"runtime": runtime, "model": model, "model_defaults": defaults, "gateway": gateway, "label": label}
    except Exception:
        return {"runtime": _UNKNOWN, "model": _UNKNOWN, "model_defaults": {}, "gateway": "none", "label": None}
