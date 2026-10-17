"""플러그인이 지원하는 이슈 DB 버전 (02-config.md §5.3, 06-collaboration.md §6.4).

- `GENERATOR_VERSION`: 생성 파일(README, STATS, CHANGELOG) 형식. 이슈 DB
  `issue-db.config.yaml`의 `generator_version`과 같아야 `db_build.py --write`를 할 수 있다.
  생성 결과가 바뀌는 플러그인 변경은 항상 이 값을 올린다. 생성기만 올리면 메인테이너가
  `migrate/schema-v<현재>` 브랜치에서 `db_migrate --to <현재>`로 이슈 DB 값을 맞춘다(06-collaboration.md §6.4).
- `SCHEMA_VERSION`: 이 플러그인이 읽고 쓰는 이슈 DB 스키마 버전 (`schema_version`).
- `plugin_fingerprint`: 플러그인 설치본 지문(`job_status --doctor`가 관리자에게 어느 설치본인지 보인다).
"""

import hashlib
from pathlib import Path

GENERATOR_VERSION = 2
SCHEMA_VERSION = 1


def plugin_fingerprint(root) -> str:
    """설치 폴더 아래 파일(`__pycache__` 제외, `site-defaults.yaml` 포함)의 상대 경로·sha256 목록을 sha256한 앞 12자."""
    root = Path(root)
    files = sorted((p.relative_to(root).as_posix(), p) for p in root.rglob("*")
                   if p.is_file() and "__pycache__" not in p.relative_to(root).parts)
    h = hashlib.sha256()
    for rel, p in files:
        h.update(f"{rel}\0{hashlib.sha256(p.read_bytes()).hexdigest()}\n".encode("utf-8"))
    return h.hexdigest()[:12]
