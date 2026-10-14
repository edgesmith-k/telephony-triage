#!/usr/bin/env bash
# 사내 리허설: 반입 묶음을 사내 순서 그대로 설치·시작·기준선·전체 테스트까지 돌린다 (docs/SITE_INSTALL.md 2~5·8절).
#
# 사내와 같은 조건에서 실행한다: Ubuntu 22.04(apt python3 3.10 / python3.11 = 3.11.0rc1, git 2.34), 일반 사용자,
# LANG=ko_KR.UTF-8(git 메시지가 한국어), TZ=Asia/Seoul. 사외 CI는 .github/workflows/external.yml의 site-rehearsal job.
# 로컬에서는 같은 조건의 컨테이너 안에서 실행한다 (이 PC의 레포에는 손대지 않는다: 새 <작업 폴더>에만 쓴다, 이미 있으면 멈춘다).
#
#   tools/site_rehearsal.sh <반입 zip> <user|venv|tt311> [작업 폴더]
#     user   시스템 python3 + pip install --user        (가이드 방법 A, 권장)
#     venv   레포 안 .venv (python3)                     (GUIDE.md 방식, 가이드 방법 B)
#     tt311  ~/.venvs/tt 같은 레포 밖 venv (python3.11)   (첫 반입 때 사내 방식)
#
# 의존성은 pyproject.toml 고정값(Python 버전 표식 포함)을 그대로 설치한다(사내 미러 대신 PyPI).
# 종료 코드: 0 전부 통과, 1 단계 실패(메시지에 단계 이름), 2 사용 오류.
set -euo pipefail

usage() { echo "사용: $0 <반입 zip> <user|venv|tt311> [작업 폴더]" >&2; exit 2; }
[ $# -ge 2 ] || usage
ZIP=$(readlink -f "$1"); METHOD=$2; WORK=${3:-$HOME/tt-rehearsal-$METHOD}
[ -f "$ZIP" ] || usage
case "$METHOD" in user|venv|tt311) ;; *) usage ;; esac

step() { echo; echo "=== [$METHOD] $*"; }
fail() { echo "!!! [$METHOD] 실패: $*" >&2; exit 1; }

step "환경: $(. /etc/os-release && echo "$PRETTY_NAME") · $(python3 --version) · $(git --version) · LANG=${LANG:-} · $(date +%Z) · uid=$(id -u)"
[ "$(id -u)" != 0 ] || echo "경고: root로 실행 중 — 사내는 일반 사용자다(권한 차이를 못 잡는다)"

[ ! -e "$WORK" ] || { echo "작업 폴더가 이미 있다: $WORK — 다른 경로를 주거나 직접 지운다" >&2; exit 2; }
mkdir -p "$WORK"
REPO="$WORK/telephony-triage"

step "1. 압축 풀기·로컬 git (2절)"
mkdir -p "$REPO" && unzip -q "$ZIP" -d "$REPO"
[ ! -e "$REPO/.local-draft" ] || fail "반입본에 .local-draft가 있다"
cd "$REPO"
git config --global user.name >/dev/null || git config --global user.name "사내 사용자"
git config --global user.email >/dev/null || git config --global user.email "dev@corp.example.invalid"
git init -q -b main && git add -A && git commit -qm "반입 (리허설)" || fail "git init/commit"

step "2. 의존성 (4절, pyproject 고정값)"
python3 - "$REPO/pyproject.toml" > "$WORK/requirements.txt" <<'EOF'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
for block in re.findall(r'(?ms)^(?:dependencies|test)\s*=\s*\[(.*?)^\]', text):
    for req in re.findall(r'"([^"]+)"', block):
        print(req)
EOF
case "$METHOD" in
  user)  python3 -m pip install -q --user -r "$WORK/requirements.txt" || fail "pip install --user"
         PY=python3 ;;
  venv)  python3 -m venv .venv && set +u && . .venv/bin/activate && set -u || fail "python3 -m venv .venv"
         python3 -m pip install -q -r "$WORK/requirements.txt" || fail "pip install (.venv)"
         PY=python3 ;;
  tt311) python3.11 -m venv "$WORK/tt" && set +u && . "$WORK/tt/bin/activate" && set -u || fail "python3.11 -m venv"
         python3 -m pip install -q -r "$WORK/requirements.txt" || fail "pip install (tt)"
         PY=python3 ;;
esac
$PY -c "import sys, yaml, jsonschema, pytest; print(sys.executable, sys.version.split()[0])" || fail "의존성 import"
[ -z "$(git status --porcelain)" ] || { git status --short | head; fail "설치 뒤 레포가 더러워졌다(.gitignore 누락?)"; }

step "3. 사내 설정 시작 (5절: site_step.py)"
set +e; $PY tools/site_step.py > "$WORK/site_step.out" 2>&1; rc=$?; set -e
tail -n 5 "$WORK/site_step.out"
[ "$rc" -le 1 ] || { cat "$WORK/site_step.out"; fail "site_step.py 종료 $rc"; }
[ -f SITE_PROFILE.md ] || fail "SITE_PROFILE.md가 생기지 않았다"

step "4. 기준선 (8절: 같은 묶음으로 import_draft)"
mkdir -p "$WORK/src" && unzip -q "$ZIP" -d "$WORK/src"
$PY "$WORK/src/tools/import_draft.py" "$WORK/src" --dest . --label rehearsal --check-boundary || fail "import_draft 기준선"
git add -A && git commit -qm "기준선 (리허설)"
$PY "$WORK/src/tools/import_draft.py" "$WORK/src" --dest . --label rehearsal --dry-run | grep -q "덮어씀 0 / 지움 0" \
  || fail "같은 묶음 재반입이 0건이 아니다"

step "5. 전체 테스트"
$PY -m pytest -q -p no:cacheprovider tests || fail "pytest"
echo; echo "=== [$METHOD] 리허설 통과"
