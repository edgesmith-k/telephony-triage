# 사내 설치 가이드 (반입 → "사내 설정 시작"까지)

반입 묶음을 사내 PC(Ubuntu 22.04 기준)에 풀고 Claude Code에서 **"사내 설정 시작"** 을 입력하기까지의 순서다.
첫 반입(import-20261013)에서 실제로 막힌 곳과 해결법을 그대로 적었다. 사내 값(미러 주소·회사명·도메인)은 이 문서에 적지 않는다 — 필요하면 `SITE_PROFILE.md`에만.

| 단계 | 할 일 | 끝난 기준 |
|---|---|---|
| 1 | 반입 파일 확인 | `sha256sum -c` 모두 OK |
| 2 | 압축 풀기·회사명 검색·로컬 git | 검색 결과 `.git` 밖 0건, 첫 커밋 |
| 3 | Python 3.10+ 확인, 설치 방법 선택(A `--user` / B venv) | `python3 --version` 3.10+ |
| 4 | 의존성 설치 (사내 PyPI 미러) | 버전 3개 출력 |
| 5 | `claude` → "사내 설정 시작" | `SITE_PROFILE.md` 생성, S-1 안내 |
| (팀원) | 7절 — 담당자 S-7 뒤 | setup 점검 표 모두 ok |

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

## 3. Python 환경 (3.10+)

이 플러그인은 **Python 3.10+** 에서 돈다(`requires-python >= 3.10`, CI 3.10·3.11·3.14). Ubuntu 22.04의 기본 `python3`(3.10)를 그대로 쓸 수 있다.

```
lsb_release -a        # Ubuntu 버전
python3 --version     # 3.10 이상이면 OK
python3 -m pip --version || sudo apt install python3-pip
```

의존성을 어디에 설치할지 둘 중 하나를 고른다. **`claude`를 실행하는 터미널의 `python3`로 의존성을 import할 수 있어야 한다**(5절 이유).

| 방법 | 설치 | `claude` 실행 | 언제 |
|---|---|---|---|
| **A. 시스템 python3 + `--user`** (권장) | `python3 -m pip install --user …` (`~/.local`에 설치, sudo 불필요) | 아무 터미널 | 새로 설치할 때. 팀원 안내가 가장 짧다 |
| B. venv `(tt)` | `python3 -m venv ~/.venvs/tt` → `. ~/.venvs/tt/bin/activate` | `(tt)` 터미널에서만 | 이미 venv를 만든 경우(첫 반입 때 3.11 venv — 그대로 써도 된다), 시스템 패키지와 섞기 싫을 때 |

- 시스템 `python3`는 바꾸지 않는다(apt가 쓴다). A는 사용자 폴더에만 설치한다.
- 3.11을 따로 쓰고 싶으면 B에서 `python3.11 -m venv`(apt `python3.11 python3.11-venv`). 22.04 apt의 3.11은 3.11.0rc1이지만 동작한다(tar 추출은 안전 검사 폴백).
- B에서 `ensurepip is not available` → `sudo apt install python3-venv`(3.11이면 `python3.11-venv`).
- Ubuntu 23.04+에서 A가 `externally-managed-environment`로 막히면 B를 쓴다.

## 4. 의존성 설치 (사내 PyPI 미러)

레포 자체는 설치하지 않는다(스크립트를 직접 실행하는 구조) — **의존성만** 설치한다. 아래는 A(`--user`) 기준이다. B면 `(tt)` 터미널에서 `--user`를 빼고, 미러 설정은 `pip config --site …`(그 venv에만).

```
pip config --user set global.index-url https://<사내 미러>/simple   # 인증서가 필요하면 global.cert
# 공통
python3 -m pip install --user PyYAML==6.0.3 jsonschema==4.26.0 attrs==26.1.0 jsonschema-specifications==2025.9.1 \
  referencing==0.37.0 typing-extensions==4.15.0 pytest==9.0.3 iniconfig==2.3.0 packaging==26.2 pluggy==1.6.0 Pygments==2.20.0
# Python 3.10이면 추가
python3 -m pip install --user rpds-py==0.30.0 exceptiongroup==1.3.1 tomli==2.5.0
# Python 3.11 이상이면 추가
python3 -m pip install --user rpds-py==2026.6.3
python3 -c "import yaml, jsonschema, pytest; import importlib.metadata as m; print([m.version(x) for x in ('PyYAML','jsonschema','pytest')])"
```

버전은 `pyproject.toml`의 고정값이다(사외 시험 버전, Python 버전별 표식 포함). 첫 반입(3.11 venv)에서는 고정 버전이 모두 설치됐다. 팀원은 PyYAML·jsonschema만 있으면 된다(7절).

### 막혔을 때

| 증상 | 원인 | 해결 |
|---|---|---|
| `Successfully installed UNKNOWN-0.0.0` | `pip install --no-build-isolation '.[test]'` — 시스템의 옛 setuptools(<61)가 `pyproject.toml`을 못 읽어 빈 패키지만 설치, **의존성은 안 깔림** | `pip uninstall -y UNKNOWN` 후 위 "의존성만" 명령 |
| `No module named pip` | 22.04 기본 설치에 pip 없음 | `sudo apt install python3-pip` |
| `ModuleNotFoundError: yaml` (설치는 됐는데) | pip와 python이 다른 인터프리터, 또는 B인데 `(tt)` 없이 실행 | `which python3` 확인, 항상 `python3 -m pip` |
| `Could not open requirements file` | 명령을 다른 폴더에서 실행 / 파일 이름 오타 | 해당 파일이 있는 폴더에서 실행 |
| 고정 버전 `No matching distribution` | 미러에 그 버전이 없음 | 범위로: `python3 -m pip install --user "PyYAML>=5.4" "jsonschema>=4.0" "pytest>=7"`. 버전이 고정값과 다르면 `SITE_PROFILE.md`에 기록하고 S-2에서 전체 테스트로 확인(아래 "검증된 하한") |
| `PyYAML==` → `(from versions: none)` | 미러에 PyYAML 없음·차단 | ① A: `sudo apt install python3-yaml`(5.4.1, 시스템 python3가 바로 씀) / B: venv를 `--system-site-packages`로 다시 ② PyYAML wheel 한 개(해당 cp 버전 manylinux) 반입 후 `pip install <whl>` ③ IT에 미러 추가 요청 |
| 미러 자체가 안 됨 | — | 사외에서 만든 오프라인 wheel 묶음 반입(Python 버전에 맞게 만든 것): 그 폴더에서 `pip install --no-index --find-links wheelhouse -r requirements-offline.txt` (오픈소스 반입 승인 대상일 수 있음) |

**검증된 하한** (사외, 핵심 테스트 — lint·verify·regress·config/setup·옛 키·db_pr): Python 3.11에서 jsonschema 4.17.3 + PyYAML 6.0.1 / **5.4.1**(C 확장 없음, 약 1.4배 느림) + pytest 7.4.4 통과. Python 3.10에서도 같은 조합 확인(10/13). 코드가 `jsonschema.Draft202012Validator`를 쓰므로 jsonschema는 **4.0 미만 불가**(apt `python3-jsonschema` 3.2는 못 씀). 전체 테스트 확인은 S-2.

## 5. Claude Code 실행

```
cd <레포 폴더>                 # B(venv)면 먼저 . ~/.venvs/tt/bin/activate — 프롬프트에 (tt)
claude                         # /model 로 Opus 권장 (사내 설정 단계는 판단이 많다)
```

첫 입력: **사내 설정 시작** (이어서 할 때는 **계속**). `tools/site_step.py`가 `SITE_PROFILE.md`(모드 사내 보완, 트래커 jira)를 만들고 S-1부터 할 일·점검·물을 것을 낸다. 단계 끝마다 사용자 확인 뒤 `--done S-n`.

**왜 터미널의 `python3`가 중요한가**: 플러그인 hook(`plugin/hooks/hooks.json`)과 git hook은 `python3`라는 이름으로 Python을 부른다. 그 `python3`가 3.10 미만이거나 의존성을 import하지 못하면 hook이 실패하고, guard는 안전한 쪽으로 막는다(MCP 거부, git 쓰기 ask). doctor의 guard 행에 `hook python3≠doctor python`이 보이면 hook과 doctor가 다른 Python을 쓰는 것이다. A는 어느 터미널이든 같다. B는 `(tt)` 없이 띄우면 시스템 python3로 돌아 의존성이 없다. 매번 켜기 번거로우면:

```
echo '. ~/.venvs/tt/bin/activate' >> ~/.bashrc    # B만. 시스템 도구는 /usr/bin/python3를 직접 쓰므로 영향 없음
```

S-1에서 `SITE_PROFILE.md`에 남길 것: 설치 경위(미러·A/B·Python 버전·실제 설치 버전, 막힌 곳), `claude` 실행 원칙(B면 "`(tt)` 터미널에서"), 아래 S-7 결정 항목.

## 6. 팀원에게 배포할 때 (S-7 전에 결정)

팀원도 `claude`를 실행하는 터미널의 `python3`가 3.10+ 이고 PyYAML·jsonschema를 import할 수 있어야 한다.

| 방법 | 내용 | 장단점 |
|---|---|---|
| 1. 각자 `--user` (권장) | 22.04 기본 python3에 `pip install --user` 한 줄 | 가장 짧다. venv·`.bashrc` 불필요 |
| 2. 각자 venv | 3~4단계 B를 사람마다, `~/.bashrc` 자동 활성화 | 시스템 패키지와 분리 |
| 3. 공용 venv | 한 곳(예: `/opt/tt-venv`)에 한 번 설치, 각자 `.bashrc`에 활성화 한 줄 | 설치 1회. 공용 경로 권한 관리 |

## 7. 팀원 사용 준비 (S-7 배포 뒤, 처음 한 번)

**전제**: 도입 담당자가 S-7까지 끝냈다(사이트 설정 `plugin/site-defaults.yaml`, 운영 이슈 DB, 사내 마켓플레이스 등록). 그 전에는 setup이 "플러그인 관리자가 사이트 설정(site-defaults.yaml)을 아직 올리지 않았습니다"로 멈춘다.

1. **의존성** (Ubuntu 22.04 기준, 6절 방법 1. venv로 정했으면 4절 B)
   ```
   python3 --version                                # 3.10 이상
   python3 -m pip --version || sudo apt install python3-pip
   pip config --user set global.index-url https://<사내 미러>/simple
   python3 -m pip install --user PyYAML==6.0.3 jsonschema==4.26.0
   ```
   pytest는 필요 없다(테스트·골든 확인용). 미러에 고정 버전이 없으면 4절 표.
2. **기본 연결**: `gh auth login -h <사내 GHE 호스트>`(이슈 DB PR용), `claude mcp list`에 Jira MCP가 사용자 범위로 보이는지.
3. **플러그인 설치**: Claude Code에서 사내 마켓플레이스의 `telephony-triage`. 레포 clone은 필요 없다.
4. **setup**: `claude`(venv면 `(tt)` 터미널에서) → `/telephony-triage:setup`. GHE 아이디·이슈 DB clone 경로·타임존 등을 묻고 점검 표(doctor)를 보여 준다. 모든 행 `ok`면 끝, `fail`·`warn`은 "다음" 열대로.
5. **연습·평소 사용**:
   ```
   $ claude
   > /telephony-triage:analyze ABC-12345 ~/logs/radio.txt --dry-run   # 연습(아무것도 올리지 않음)
   > ABC-12345 로그 분석해줘, 로그는 ~/logs/radio.txt                   # 평소
   ```

**지킬 것**: 의존성을 설치한 Python으로 `claude`(venv면 항상 `(tt)` 터미널, 5절 이유) · 로그는 대화에 붙이지 않고 파일 경로로 · 막히면 setup을 다시 실행해 점검 표를 보고, 그래도 안 되면 메시지 그대로 관리자에게.

| | 도입 담당자 | 팀원 |
|---|---|---|
| 레포 | 필요(레포 폴더에서 작업) | 불필요(마켓플레이스 설치) |
| 시작 | "사내 설정 시작" | `/telephony-triage:setup` |
| 의존성 | PyYAML·jsonschema·pytest | PyYAML·jsonschema |
| pytest·eval·빈 플러그인 실험 | 한다(S-2) | 안 한다 |
| 다시 검증할 때 | Claude Code 큰 버전 변경, 평소 모델 변경, 플러그인 새 반입(바뀐 흐름의 eval만) | — |

오프라인 의존성 묶음(`tt-offline-deps-<날짜>.zip`, 사외에서 만든 wheel)은 **비상용**이다. 사내 미러로 설치되면 반입하지 않는다.

관련: 반입 체크리스트 `docs/design/15-local-draft.md §15.4`, 사내 단계 §15.5, 사람용 총정리 `GUIDE.md` 4장.
