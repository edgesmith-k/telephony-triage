# 사내 설치 가이드 (반입 → "사내 설정 시작"까지)

반입 묶음을 사내 PC(Ubuntu 22.04 기준)에 풀고 Claude Code에서 **"사내 설정 시작"** 을 입력하기까지의 순서다.
첫 반입(import-20261013)에서 실제로 막힌 곳과 해결법을 그대로 적었다. 사내 값(미러 주소·회사명·도메인)은 이 문서에 적지 않는다 — 필요하면 `SITE_PROFILE.md`에만.

| 단계 | 할 일 | 끝난 기준 |
|---|---|---|
| 1 | 반입 파일 확인 | `sha256sum -c` 모두 OK |
| 2 | 압축 풀기·회사명 검색·로컬 git | 검색 결과 `.git` 밖 0건, 첫 커밋 |
| 3 | Python 3.11 venv | 프롬프트에 `(tt)`, `python3 --version` 3.11+ |
| 4 | 의존성 설치 (사내 PyPI 미러) | 버전 3개 출력 |
| 5 | `claude` → "사내 설정 시작" | `SITE_PROFILE.md` 생성, S-1 안내 |

## 1. 반입 파일 확인

받는 것: `telephony-triage-import-<label>.zip`, `issue-db-skeleton-import-<label>.zip`, `SHA256SUMS`.

```
cd <zip 둔 폴더>          # zip 2개와 SHA256SUMS가 같은 폴더에
sha256sum -c SHA256SUMS   # 두 줄 모두 OK
```

- `SHA256SUMS`는 **zip 파일**의 해시다. 이미 압축을 풀었다면 zip으로 다시 확인하거나, 사외에서 파일별 해시 목록(`FILES-*.sha256`)을 받아 푼 폴더 루트에서 `sha256sum -c --quiet FILES-….sha256`(출력 없으면 OK). 확인 뒤 그 목록 파일은 지우고 커밋하지 않는다.
- FAILED·No such file → 다시 받는다. 반입 중 파일 이름이 바뀌었으면 원래 이름으로.

## 2. 압축 풀기 · 회사명 검색 · 로컬 git

```
mkdir telephony-triage && cd telephony-triage
unzip ../telephony-triage-import-<label>.zip
grep -rniE --exclude-dir=.git '<회사명>|<사내 도메인>' .     # 0건이어야 한다
git init -b main
git config user.name "<이름>"; git config user.email "<사내 메일>"
git add -A && git commit -m "import-<label> 반입 (사외 <커밋>)"

mkdir ../issue-db-skeleton && unzip ../issue-db-skeleton-import-<label>.zip -d ../issue-db-skeleton   # S-4a까지 그대로 둔다
```

- 묶음에는 `.git`이 없다. 사내 단계 도구(`site_step.py`)가 커밋 정보와 `git user.name`(확인자)을 쓰므로 로컬 git을 먼저 만든다. 외부로 나가는 것은 없다. 사내 GHE push는 S-4a에서.
- 회사명 검색은 `.git`을 뺀다. git 설정·커밋에 사내 메일이 들어가 `.git` 안에서 걸리는 것은 정상이다. `.git` 밖에서 걸리면 반입을 멈추고 원인을 본다(사외로 그 문자열을 옮기지 않는다 — 파일·줄만).

## 3. Python 3.11 venv

Ubuntu 22.04의 `python3`는 **3.10**이다. 이 플러그인은 **3.11+** 가 필요하다(`requires-python >= 3.11`, 3.10은 시험하지 않았다).

```
lsb_release -a                       # Ubuntu 버전
sudo apt update && sudo apt install python3.11 python3.11-venv   # 22.04 universe에 있음
python3.11 -m venv ~/.venvs/tt
. ~/.venvs/tt/bin/activate           # 프롬프트에 (tt)
python3 --version                    # 3.11.x
```

- 시스템 `python3`(3.10)는 그대로 둔다. apt 등 시스템 도구가 쓴다. venv를 켠 터미널에서만 `python3`가 3.11이다.
- `Unable to locate package python3.11` → 사내 apt 미러에 universe가 없음. sudo가 없을 때와 같이 IT에 "python3.11, python3.11-venv 설치" 요청.
- `ensurepip is not available` → `python3.11-venv` 미설치.
- 20.04 이하는 apt에 3.11이 없다 → conda 등 다른 방법.

## 4. 의존성 설치 (사내 PyPI 미러)

`(tt)` 터미널에서. 레포 자체는 설치하지 않는다(스크립트를 직접 실행하는 구조) — **의존성만** 설치한다.

```
pip config --site set global.index-url https://<사내 미러>/simple   # 이 venv에만 적용. 인증서가 필요하면 global.cert
python3 -m pip install PyYAML==6.0.3 jsonschema==4.26.0 attrs==26.1.0 jsonschema-specifications==2025.9.1 \
  referencing==0.37.0 rpds-py==2026.6.3 typing-extensions==4.15.0 \
  pytest==9.0.3 iniconfig==2.3.0 packaging==26.2 pluggy==1.6.0 Pygments==2.20.0
python3 -c "import yaml, jsonschema, pytest; import importlib.metadata as m; print([m.version(x) for x in ('PyYAML','jsonschema','pytest')])"
```

버전은 `pyproject.toml`의 고정값이다(사외 시험 버전). 첫 반입에서는 이 고정 버전이 모두 설치됐다.

### 막혔을 때

| 증상 | 원인 | 해결 |
|---|---|---|
| `Successfully installed UNKNOWN-0.0.0` | `pip install --no-build-isolation '.[test]'` — 시스템의 옛 setuptools(<61)가 `pyproject.toml`을 못 읽어 빈 패키지만 설치, **의존성은 안 깔림** | `pip uninstall -y UNKNOWN` 후 위 "의존성만" 명령 |
| `ModuleNotFoundError: tomllib` | `python3`가 3.10 (venv 안 켬 또는 3.10으로 만든 venv) | 3단계를 다시 — venv를 `python3.11`로 |
| `ModuleNotFoundError: yaml` (설치는 됐는데) | pip와 python이 다른 인터프리터 | `which python3 pip` 확인, 항상 `python3 -m pip` |
| `Could not open requirements file` | 명령을 다른 폴더에서 실행 / 파일 이름 오타 | 해당 파일이 있는 폴더에서 실행 |
| 고정 버전 `No matching distribution` | 미러에 그 버전이 없음 | 범위로: `python3 -m pip install "PyYAML>=6" "jsonschema>=4.0" "pytest>=7"`. 버전이 고정값과 다르면 `SITE_PROFILE.md`에 기록하고 S-2에서 전체 테스트로 확인(아래 "검증된 하한") |
| `PyYAML==` → `(from versions: none)` | 미러에 PyYAML 없음·차단 | ① `sudo apt install python3-yaml` + venv를 `python3.11 -m venv --system-site-packages ~/.venvs/tt`로 다시(apt의 5.4.1을 순수 Python 모드로 사용) ② PyYAML wheel 한 개(cp311 manylinux) 반입 후 `pip install <whl>` ③ IT에 미러 추가 요청 |
| 미러 자체가 안 됨 | — | 사외에서 만든 오프라인 wheel 묶음 반입: 그 폴더에서 `pip install --no-index --find-links wheelhouse -r requirements-offline.txt` (오픈소스 반입 승인 대상일 수 있음) |

**검증된 하한** (사외, Python 3.11, 핵심 테스트 199개 — lint·verify·regress·config/setup·옛 키·db_pr): jsonschema 4.17.3 + PyYAML 6.0.1 + pytest 7.4.4 통과, jsonschema 4.17.3 + **PyYAML 5.4.1**(C 확장 없음) + pytest 7.4.4 통과(약 1.4배 느림). 코드가 `jsonschema.Draft202012Validator`를 쓰므로 jsonschema는 **4.0 미만 불가**(apt `python3-jsonschema` 3.2는 못 씀). 전체 테스트 확인은 S-2.

## 5. Claude Code 실행

```
. ~/.venvs/tt/bin/activate     # (tt) 확인 — 반드시
cd <레포 폴더>
claude                         # /model 로 Opus 권장 (사내 설정 단계는 판단이 많다)
```

첫 입력: **사내 설정 시작** (이어서 할 때는 **계속**). `tools/site_step.py`가 `SITE_PROFILE.md`(모드 사내 보완, 트래커 jira)를 만들고 S-1부터 할 일·점검·물을 것을 낸다. 단계 끝마다 사용자 확인 뒤 `--done S-n`.

**왜 `(tt)`가 필요한가**: 플러그인 hook(`plugin/hooks/hooks.json`)과 git hook은 `python3`라는 이름으로 Python을 부른다. `(tt)` 없이 `claude`를 띄우면 시스템 3.10으로 돌아 실패하고, guard는 안전한 쪽으로 막는다(MCP 거부, git 쓰기 ask). doctor의 guard 행에 `hook python3≠doctor python`이 보이면 이 경우다. 매번 켜기 번거로우면:

```
echo '. ~/.venvs/tt/bin/activate' >> ~/.bashrc    # 시스템 도구는 /usr/bin/python3를 직접 쓰므로 영향 없음
```

S-1에서 `SITE_PROFILE.md`에 남길 것: 설치 경위(미러·venv 경로·실제 설치 버전, 막힌 곳), "`(tt)` 터미널에서 실행" 원칙, 아래 S-7 결정 항목.

## 6. 팀원에게 배포할 때 (S-7 전에 결정)

지금 구조에서는 팀원도 `claude`를 실행하는 터미널의 `python3`가 3.11+ 이고 의존성이 있어야 한다.

| 방법 | 내용 | 장단점 |
|---|---|---|
| 1. 각자 venv | 3~4단계를 사람마다, `~/.bashrc` 자동 활성화 | 지금 가능. 설치 단계 하나 추가 |
| 2. 공용 venv | 한 곳(예: `/opt/tt-venv`)에 한 번 설치, 각자 `.bashrc`에 활성화 한 줄 | 설치 1회. 공용 경로 권한 관리 |
| 3. 플러그인 수정 | hook이 `python3` 대신 지정한 인터프리터(예: 환경변수 `TT_PYTHON`)를 부르게 | 터미널 상태와 무관. 코드 수정 + 전체 테스트 필요 → **사외 레포에서 고쳐 다음 반입** (사내에서 공통 코드를 고치면 재반입 때 충돌) |

관련: 반입 체크리스트 `docs/design/15-local-draft.md §15.4`, 사내 단계 §15.5, 사람용 총정리 `GUIDE.md` 4장.
