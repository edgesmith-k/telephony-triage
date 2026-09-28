"""reference 파서 백엔드 (16-existing-assets.md §16.3).

공통 처리(포맷·시각·RIL 페어링·윈도우)는 제품 수준이고, builtin 판별 로직은
없다. site 백엔드는 이 클래스를 상속해 `detect()`만 구현하면 공통 처리를 그대로
재사용한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .. import logcat, ril
from ..base import ParserBackend, Window

VERSION = "0.1.0"


class ReferenceBackend(ParserBackend):
    name = "reference"

    def version(self) -> str:
        return VERSION

    def builtin_events(self) -> list[str]:
        return []

    def detect(self, record: dict) -> list[tuple[str, dict]]:
        """줄 레코드 하나에 대한 builtin 판별 `[(이벤트 이름, fields)]`.
        reference는 판별 로직이 없다. site 백엔드가 바꾼다."""
        return []

    # -- 공통 처리 ---------------------------------------------------------

    def _line_record(self, line: logcat.LogLine) -> dict:
        return {
            "ts": logcat.format_ts(line.dt),
            "pid": line.pid,
            "tid": line.tid,
            "level": line.level,
            "tag": line.tag,
            "msg": line.msg,
            "phone_id": logcat.phone_id(line.tag, line.msg),
            "category_hint": None,
            "ril": ril.parse(line.tag, line.msg),
            "event": None,
            "fields": {},
            "source": f"backend:{self.name}",
            "_dt": line.dt,
            "_file": line.file_index,
            "_line": line.line_no,
            "_sub": 0,
        }

    def _builtin_record(self, base: dict, event: str, fields: dict, sub: int) -> dict:
        parts = event.split(".")
        rec = dict(base)
        rec.update(
            {
                "category_hint": parts[1] if len(parts) >= 3 and parts[0] == "builtin" else None,
                "ril": None,
                "event": event,
                "fields": {k: str(v) for k, v in fields.items() if v is not None},
                "_sub": sub,
            }
        )
        return rec

    def parse(
        self,
        paths: Sequence[str | Path],
        tz: str | None,
        year: int | None,
        window: Window | None,
    ) -> list[dict]:
        out: list[dict] = []
        for index, path in enumerate(paths):
            lines, _ = logcat.read_file(path, index, tz, year)
            records = [self._line_record(line) for line in lines]
            ril.pair(records)  # 윈도우를 자르기 전에 파일 전체로
            for rec in records:
                if window and not (window[0] <= rec["_dt"] <= window[1]):
                    continue
                out.append(rec)
                for sub, (event, fields) in enumerate(self.detect(rec), 1):
                    out.append(self._builtin_record(rec, event, fields, sub))
        out.sort(key=lambda r: (r["_dt"], r["_file"], r["_line"], r["_sub"]))
        return [{k: v for k, v in rec.items() if not k.startswith("_")} for rec in out]


BACKEND = ReferenceBackend()
