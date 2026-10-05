"""호환 shim — 실제 코드는 `platforms/android/ril.py` (RF-3, I2).
사내 site 백엔드의 `from .. import logcat`이 그대로 동작하도록 같은 모듈 객체를 등록한다."""
import sys

from platforms.android import ril as _impl

sys.modules[__name__] = _impl
