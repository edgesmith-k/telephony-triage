# 사내 스냅샷 복구 (모듈 스킬 템플릿·벤더 IPC 설정)

**읽는 사람**: S-6까지 끝낸 사내 레포의 담당자. `docs/site/module-skills/`가 아직 없으면 새 묶음을 반입하기 **전에** ⓪부터 한 번 하고, 이후 재반입 때는 ⑦만 본다. 요약은 `tools/site_step.py restore`, 점검은 `restore check`(진행 상태 없는 독립 명령, 토큰 0).

사외 레포의 모듈 스킬 템플릿(`templates/module-skills/`)과 벤더 IPC 판별은 공개 용어와 아래 placeholder만 쓴다. 사내 구성요소 이름·값은 사내가 SITE_PATHS에 채운다: 사내 레포에서 쓰던 템플릿 트리를 **스냅샷**으로 `docs/site/module-skills/`에 두면, 모듈 스킬 레포를 만들 때 `make_module_repo.py --site-overlay`가 같은 상대 경로로 통째로 덮어쓴다. 벤더 IPC 값은 site-defaults에 둔다.

| placeholder | 카테고리 | 뜻 |
|---|---|---|
| `ofonod` | common | oFono 데몬(upstream, 그대로) |
| `mgmtd` · `vrild` | common | 관리 데몬 · 벤더 RIL 데몬 |
| `datad` · `imsd` · `simd` · `networkd` (`datad2` 류 `<cat>d2`) | data · ims · sim · network | 카테고리 구성요소(`<cat>d2` = 같은 카테고리 두 번째) |
| `chatterd` | noise | 노이즈 태그 |
| `VRIL` · `VRIL-SVC` · `VRIL-IMS` · `VRIL-MODEM` · `VRIL-DATA` · `VRIL-NETWORK` | Android | 벤더 RIL · 텔레포니 서비스 · IMS · 모뎀/IPC · 프레임워크(data·network) 태그 |
| `VRIL-LINK` · `VRIL-INFO` · `VRIL-TEST` | Android | 수집 안 함(샘플 tags.yaml에 없는 벤더 태그) |
| `IpcCtx_<n>` · `OnIpcComplete` | — | 벤더 IPC 문맥 접두어 · 완료 낱말(②의 `vendor_ipc.context`·`complete`) |

표식 `{{site:<cat>}}`도 사내 스냅샷이 채울 자리다. 덮어쓴 파일에 위 이름·표식이 남아 있으면 `make_module_repo.py`가 "스냅샷이 불완전"으로 종료 1이다.

명령은 사내 레포 폴더에서, `claude`를 실행하는 것과 같은 Python으로 한다(SITE_INSTALL.md 3절).

## ⓪ 스냅샷 꺼내기 (새 묶음 반입 **전**)

반입 전 사내 레포 HEAD(사내에서 쓰던 상태)에서 꺼낸다. 옛 clone은 필요 없다.

```
if [ -e docs/site/module-skills ]; then echo "이미 있음 — ⓪을 건너뛴다(덮어쓰지 않는다)"; else
  SHA=$(git rev-parse HEAD)
  LABEL=$(git show $SHA:.draft-manifest.json | python3 -c 'import json,sys; print(json.load(sys.stdin)["label"])')
  DATE=$(date +%F)
  echo "$LABEL $SHA $DATE"                      # 지금 쓰는 반입 라벨이 맞는지 본다
  SNAP=$(mktemp -d)
  git archive $SHA templates/module-skills | tar -x -C $SNAP
  find $SNAP/templates/module-skills -mindepth 3 -maxdepth 3 -type d -name evals -exec rm -rf {} +   # */*/evals/ 제거
  mkdir -p docs/site && mv $SNAP/templates/module-skills docs/site/module-skills && rm -rf $SNAP
  echo "label=$LABEL sha=$SHA date=$DATE" > docs/site/module-skills/SOURCE
  git add docs/site/module-skills && git commit -m "사내 스냅샷: module-skills ($LABEL)"
fi
```

- 묶음을 이미 반입했다면 `SHA`는 반입 커밋의 부모(`git rev-parse <반입 커밋>^`)로 둔다 — 반입 뒤 HEAD면 `restore.overlay`가 "불완전"으로 실패한다.
- 스냅샷 범위는 템플릿 트리 전체에서 `*/*/evals/`만 뺀 것이다(`modules.yaml`, `README.md`, `<p>/_common/*`, 모듈마다 `SKILL.md`·analyzer·explore·references).
- `.draft-manifest.json`이 없으면(첫 반입을 압축 풀기로 했으면) SITE_INSTALL.md 8절 3으로 기준선을 먼저 만든다.
- `SOURCE`는 한 줄 `label=<반입 라벨> sha=<sha> date=<yyyy-mm-dd>`다. `sha` = 스냅샷을 꺼낸 커밋(바꾸지 않는다), `label`·`date` = 스냅샷 반영을 확인한 마지막 반입과 날짜(⑦에서 갱신).

## ① 재반입과 SITE_PATHS 확인

SITE_INSTALL.md 8절대로 새 묶음을 반입한다(작업 브랜치 → `import_draft.py --check-boundary` → pytest → main에 ff 병합).

```
git status --short docs/site plugin/site-defaults.yaml SITE_PROFILE.md   # 출력 없음 — SITE_PATHS는 반입이 건드리지 않는다
cat docs/site/module-skills/SOURCE                                       # ⓪의 한 줄 그대로
grep '^- 완료 단계' SITE_PROFILE.md                                      # S-1 … S-6이 그대로 있다
python3 tools/site_step.py check S-6                                     # 반입 뒤에도 통과
```

## ② 벤더 IPC 값 (site-defaults, **첫 분석보다 먼저**)

요청 완료 줄의 두 낱말만 설정으로 옮긴다(오류 코드·성공 토큰은 코드 상수). 값은 사내 로그의 요청 완료 줄 `[<context><n>] <complete> Request ID=<id>, result=<n>`에서 확인한 두 낱말이다(사내 레포 이력에 같은 값이 있으면 그것). 출력은 사내 터미널에서만 본다.

| 키 | 줄에서 옮길 글자 |
|---|---|
| `context` | `[` 뒤, 숫자 앞의 글자(끝의 `_` 포함) |
| `complete` | `]`와 공백 뒤의 낱말 |

값은 식별자 모양 `^[A-Za-z][A-Za-z0-9_]{0,63}$`이고, 키를 빼거나 `null`이면 placeholder를 쓴다. 다른 키는 "알 수 없는 키"로 종료 2다(기준: `contracts.md` 설정 키 표). 켠 플랫폼마다 둔다 — 기본 플랫폼은 `platform.vendor_ipc`, 그 밖은 `platform.others.<p>.vendor_ipc`:

```yaml
platform:
  enabled: [android, ofono]
  vendor_ipc: {context: "<문맥 접두어>", complete: "<완료 낱말>"}
  others:
    ofono:
      vendor_ipc: {context: "…", complete: "…"}
```

`python3 plugin/scripts/config.py check --plugin-root plugin`이 종료 0이어야 한다. 값이 없으면 사내 로그에서 `vendor_request_failed` 이벤트가 0개다(④에서 확인). vendor_ipc 값은 분석 재사용 키(`compiled.environment`)에 들지 않아 ② 전에 만든 분석 캐시는 무효화되지 않는다.

## ③ 모듈 스킬 레포

**레포가 아직 없으면** — 만들고 MS-1로 연결한다(SITE_INSTALL.md 10절, `site_step.py modules`).

```
OUT=~/tt-module-skills                         # 없거나 빈 디렉토리, 레포 밖
python3 tools/make_module_repo.py $OUT --site-overlay docs/site/module-skills
git -C $OUT remote add origin <사내 GHE>/<org>/<모듈 스킬 레포>.git
git -C $OUT push -u origin main                # 빈 레포·보호 켜기 전 한 번. 그 뒤 main 보호(+1·up to date)
```

**레포가 이미 있으면** — 임시 디렉토리에 같은 명령으로 렌더하고 차이만 PR로 보낸다.

```
OUT=$(mktemp -d)/render
python3 tools/make_module_repo.py $OUT --site-overlay docs/site/module-skills
CUR=$(mktemp -d)/cur && git clone -q <module_skills.remote> $CUR
diff -rq -x .git -x evals $CUR $OUT            # 출력 없음이 정상
```

- evals 차이는 보내지 않는다(모듈 레포의 evals를 그대로 둔다). `Only in $CUR`(레포에만 있는 사내 파일)도 그대로 둔다.
- 다른 파일 `<f>`마다: `git -C $CUR log --format=%h --invert-grep --grep='^restore: ' -- <f> | wc -l`(이 절차의 커밋은 뺀다)이 1보다 크면 모듈 레포에서 사내가 고친 것이다 → `cp $CUR/<f> docs/site/module-skills/<f>`로 스냅샷에 반영하고 커밋한 뒤 렌더·diff를 다시 한다. 1이면 렌더본이 보낼 변경이다. ⑦에서 방금 스냅샷을 고친 파일은 렌더본이 맞다.
- 보낼 파일만 `$CUR`에 복사 → `git -C $CUR switch -c restore/<label>` → `git -C $CUR commit -am "restore: <label>"`(새 파일은 add) → push → GHE PR(+1 뒤 병합, 스쿼시면 제목도 `restore: <label>`).

## ④ 검사

```
python3 tools/site_step.py restore check       # 아래 표, 실패·건너뜀·사용자 필요면 종료 1(경고는 0)
python3 tools/check_boundary.py --mode site
python3 -m pytest -q tests/test_modulefilter.py tests/test_module_templates.py
```

| 점검 | 보는 것 |
|---|---|
| `restore.snapshot` | `docs/site/module-skills/`에 `modules.yaml`, `_common`이 있는 플랫폼 2개 이상, `*/*/evals/` 없음 |
| `restore.source` | `SOURCE` 한 줄 형식 |
| `restore.overlay` | `make_module_repo.py <임시> --site-overlay … --json` 종료 0(placeholder·표식 남음, evals 포함은 실패) |
| `restore.tags` | 렌더된 `modules.yaml`의 데몬·태그 ⊆ 사내 이슈 DB `tags.yaml`(빠진 이름은 이 출력에만) |
| `restore.vendor_ipc` | 켠 플랫폼마다 ②의 블록(값은 보이지 않는다). 없으면 사용자 필요, 플랫폼 설정을 못 읽으면 실패 |
| `restore.deny` | `TT_DENY_FILE`의 항목이 SITE_PATHS 밖 추적 파일에 0건. 변수가 없으면 사용자 필요 |
| `restore.label` | 지금 반입 라벨(`.draft-manifest.json`, 없으면 `import-*` 태그) = `SOURCE` label. 다르면 경고 |

⓪ 뒤 새 묶음을 반입했으면 `restore.label`이 경고인 것이 정상이다. ③까지 마쳤으면 `SOURCE`의 `label`·`date`를 지금 반입으로 고쳐 커밋한다(`sha`는 그대로).

`vendor_request_failed` 이벤트 수가 반입 전과 같은지(`vendor_ipc_error`는 설정과 무관) O-1 폴더의 사내 oFono 로그(마스킹본) 하나로 본다. 반입 전 코드는 `SOURCE`의 `sha` worktree에서 그때 site-defaults로 돌린다. 넷째 줄(`git worktree add`)이 실패하면 멈춘다 — site-defaults가 없으면 ② 전 사본을 `~/tt-before/plugin/`에 두고 잇는다.

```
LOG=<벤더 요청 실패 줄이 있는 사내 oFono 로그>; RULES=<oFono 이슈 DB clone>/parser-rules
n() { python3 -c 'import json,sys; e=json.load(sys.stdin)["events"]; print(sum(x["event"]=="builtin.common.vendor_request_failed" for x in e))'; }
SHA=$(sed -n 's/.* sha=\([0-9a-f]*\) .*/\1/p' docs/site/module-skills/SOURCE)
git worktree add --detach ~/tt-before $SHA && ls ~/tt-before/plugin/site-defaults.yaml   # 실패·없음이면 여기서 멈춘다
python3 ~/tt-before/plugin/scripts/parse_logcat.py parse $LOG --full --rules $RULES --plugin-root ~/tt-before/plugin | n   # 반입 전
python3 plugin/scripts/parse_logcat.py parse $LOG --full --rules $RULES --plugin-root plugin | n                          # 같아야 한다
git worktree remove --force ~/tt-before
```

설정이 없으면 지금 결과는 0이다. 반입 전 결과가 0이 아닌데 지금 0이면 ②가 빠졌거나 틀렸다.

## ⑤ 거부 목록 운영

- `TT_DENY_FILE`은 **레포 밖** 파일(한 줄에 하나, `#` 주석)이다. 레포·묶음·문서에 넣지 않는다.
- 사내 구성요소 이름·벤더 토큰이 새로 생기면 한 줄 더한다. 사내 이름은 SITE_PATHS(스냅샷·site-defaults·`tests/site/`)에만 둔다 — `restore.deny`가 그 밖 0건을 본다(가린 경로·건수만, `tools/deny_scan.py`).
- 사외에서 묶음을 만들 때(`make_bundle.py`)는 `deny-file` 검사가 0건이어야 묶음이 생긴다(SITE_INSTALL.md 1절).

## ⑥ (선택) 실제 로그 사례

기존 절차대로 `tests/site/module-evals/`(SITE_PATHS)에 둔다: `plugin/scripts/parse_logcat.py cut --around`로 마스킹된 구간만 자르고 `plugin/scripts/module_eval.py --templates`로 돈다(비용 승인 뒤, MS-2 2항).

## ⑦ 이어서

S-7·MS-*를 이어 간다(`python3 tools/site_step.py`). 이후 새 묶음을 재반입하면:

1. SITE_INSTALL.md 8절로 반입한다. 스냅샷은 SITE_PATHS라 그대로다.
2. `restore check`의 `restore.label`이 경고가 된다. 덮어쓰기는 스냅샷 파일을 통째로 쓰므로 **사외 템플릿의 변경은 ③의 diff에 보이지 않는다.** `SOURCE` label의 반입 커밋과 지금 HEAD의 diff로 보고, 필요한 것은 스냅샷 파일에 직접 옮긴다:
   ```
   for c in $(git log --format=%H -- .draft-manifest.json); do echo "$c $(git show $c:.draft-manifest.json | python3 -c 'import json,sys; print(json.load(sys.stdin)["label"])')"; done | head
   git diff <SOURCE label의 반입 커밋> HEAD -- templates/module-skills ':!templates/module-skills/*/*/evals/*'
   ```
3. ③의 "이미 있으면" 갈래를 다시 돈다 → `SOURCE`의 `label`·`date`를 새 반입으로 고친다 → `restore check` 경고가 사라진다.
