# telephony-triage 총정리 가이드

> 사람이 읽는 요약입니다. Claude Code가 따르는 상세 지침은 `CLAUDE.md`와 `docs/design/`에 있습니다.

## 1. 무엇을 만드나

| 구성 | 설명 |
|---|---|
| **플러그인** `telephony-triage` | Claude Code에 설치하는 도구. Jira + logcat으로 이슈를 분석하고, 결과를 이슈 DB에 PR로 올린다 |
| **이슈 DB** `telephony-issue-db` | 사내 GitHub 레포. 카테고리(data/call/network/sim/sms/ims) > 이슈 유형(증상) > 원인 + 해결책 + Jira 이력. README가 사람이 보는 목록 |

한 줄 흐름: **Jira + 로그 → 파서(이벤트) → 시그니처 매칭 → 원인·해결책 제시 → 사용자 확인 → 이슈 DB에 PR → 리뷰어 머지**

---

## 2. 전체 진행 순서

```
[사외 PC]                                  [사내]
Phase D0  모의 환경 구축                    S-1  사내 값 조사 → SITE_PROFILE.md
Phase 1~13 모의 환경으로 전부 구현           S-2  사내 Claude Code 동작 확인
반입 체크리스트                   ──반입──▶  S-3  사내 설정 입력 (site-defaults.yaml)
                                           S-4a 기존 자산 연결 (파서 포팅·분류 import·분석 스킬)
                                           S-4  나머지 카테고리 실제 로그 반영
                                           S-5  실전 시험 (dry-run, 샌드박스 PR)
                                           S-6  남은 검토 항목 정리
                                           S-7  배포 + 파일럿
```

원칙: **구현은 사외에서 최대한, 사내는 끼워 맞추기만.** 사내 값과 사내 코드는 `SITE_PATHS`에 적힌 경로(`site-defaults.yaml`, `SITE_PROFILE.md`, 포팅한 파서, 골든 등)에만 둡니다. 사외 코드를 다시 반입할 때는 **통째로 교체하지 말고** `tools/import_draft.py`로 덮어쓰면 이 경로들은 보존됩니다. 실행 환경은 **Ubuntu**입니다(다른 OS 미지원).

플러그인 코드는 사내/사외를 판별하지 않습니다. `plugin/site-defaults.yaml`(S-3에서 만들고 사내 깃헙에 커밋)이 있으면 그 값으로 동작하고, 없으면 모든 커맨드가 "사내 기본값 없음"으로 멈춥니다. 사외 테스트는 `site-defaults.example.yaml`을 복사한 임시 플러그인 루트로만 돌아갑니다.

---

## 3. 사외 PC에서 만들기

### 준비
1. `telephony-triage-docs.zip`을 풀어 빈 폴더(플러그인 레포 루트)에 둔다.
2. 그 폴더에서 Claude Code를 연다.

### 진행 (세션마다 한 Phase 정도)
| 입력 | 결과 |
|---|---|
| `사외 초안 모드로 Phase D0부터 시작해` | 가짜 Jira MCP(`mock-jira`), 가짜 GitHub(로컬 원격 + `gh` 흉내), 합성 logcat, 가짜 소스 트리, 가짜 기존 파서 백엔드·분석 스킬, 재반입 도구(`SITE_PATHS`, `import_draft.py`) |
| `다음 Phase 진행해` (반복) | Phase 1~13. 끝날 때마다 완료 기준 점검 후 확인 요청 |

- 파서는 **인터페이스 + 공통 처리(참고 구현)** 까지만 만든다. data 판별은 사내에서 검증된 기존 파서를 포팅해서 넣는다.
- SKILL.md는 Phase 13에서 skill-creator로 만들고 eval(`tests/skill_evals/evals.json` 전체, 10/07 기준 58개)을 모의 환경으로 통과시킨다.
- 진행 상태는 `DRAFT_NOTES.md`에 기록되므로 세션을 끊고 이어가도 된다. D0에서 사외 PC에만 두는 표식 `.local-draft`를 만들므로, 이후 세션은 모드를 다시 묻지 않는다.
- 합성 샘플 이슈 DB는 플러그인 레포 테스트 데이터(`tests/fixtures/issue-db-sample/`)로만 쓴다. 반입할 이슈 DB는 `tools/make_db_skeleton.py`로 만든 **뼈대**(합성 샘플 없음)다.

### 반입 전
```
반입 체크리스트(15-local-draft.md §15.4) 확인하고 DRAFT_NOTES.md(상태 파일) 갱신해줘
```
- 테스트 전부 통과, `site-defaults.yaml` 없음, `.local-draft`·`.mcp.json`이 반입 묶음에 없음, 이슈 DB 뼈대 생성, `TODO(SITE:...)` 목록 정리를 확인한다.
- 경계 검사: `python3 tools/check_boundary.py --mode external`(사외 CI에서도 돈다), `python3 tools/sync_schemas.py --check`.
- 사내 문자열 검색: 실제 회사명·서버명·팀명이 없는지 (`grep -rniE '<회사명>|<사내 도메인>' .`).
- 사내 **외부 작성 코드 반입 규정**(오픈소스 의존성 승인 포함)을 확인한 뒤 플러그인 레포 + 이슈 DB 뼈대를 반입한다.

**반입 묶음 만들기** (사외 PC, 작업 트리가 깨끗한 상태에서)

실행 전 할 일: `plugin/.claude-plugin/plugin.json` description에서 "사외 초안"을 빼고 커밋한다(도구의 첫 자동 검사 `plugin-json`, version은 두지 않는다).
```
python3 tools/make_bundle.py --label import-v1     # 이 이름이 사내 .draft-manifest.json의 label
```
- 도구가 자동 항목을 싼 것부터 검사하고(첫 실패에서 중단), 모두 통과하면 묶음을 만든다: 레포 zip(`git archive`), 이슈 DB 뼈대 zip, `SHA256SUMS`(`sha256sum -c` 형식), `make_bundle-result.json`, `logs/`. 위치는 기본 `<레포 상위>/tt-import-bundles/<label>/`이다 (`--out`으로 바꾸고, 이미 있으면 `--force`). 전체 pytest를 돌리므로 시간이 걸린다.
- **종료 3 = 정상 완료**: 자동 검사 통과, 묶음 생성, 사람 확인 3건 대기. 이 도구는 0으로 끝나지 않는다. 종료 1은 자동 검사 실패 또는 `--skip`(묶음 없음, `--skip`은 통과로 세지 않는다), 종료 2는 사용·환경 오류(트리가 깨끗하지 않음, 태그가 다른 커밋을 가리킴 등)다.
- 사람이 확인할 3건: ① 실제 회사명·서버명·팀명 검색(`grep -rniE '<회사명>|<사내 도메인>' .`), ② `list_site_todos.py` 결과를 직접 봄, ③ `DRAFT_NOTES.md`가 최신인지.
- 확인을 마치면 도구가 출력한 명령으로 **직접** 태그를 만들고 push한다 (도구는 태그를 만들지 않는다): `git tag import-v1 <HEAD sha> && git push <remote> import-v1` (remote는 도구가 출력한 이름. 결과의 `on_remote_main`이 false면 경고가 나온다 — 병합 후 main에서 다시 만든다)
- 사내에서는 `SHA256SUMS`로 대조한다 (`sha256sum -c SHA256SUMS`).
- `git archive`는 커밋된 파일만 담으므로 `.local-draft`, `tests/skill_evals/workspace/`, `__pycache__` 같은 비추적·무시 파일이 자동으로 빠진다. 도구가 zip 안에 `.local-draft`·`.mcp.json`·`SITE_PATHS` 경로가 없는지도 다시 확인한다.
- 전송 수단·승인은 회사 반입 절차를 따른다.

---

## 4. 사내에서 보완하기

### 미리 준비할 것
- Ubuntu PC (다른 OS는 지원하지 않음), Python 3.11+, git, `gh`
- 샘플 Jira 키 2~3개(카테고리가 다른 것), 각 Jira의 발생 시각 필드 이름·형식·타임존
- 카테고리별 실제 logcat 1개씩 + 정상 로그 1~2개(16/17), 듀얼 SIM 로그 1개 이상
- Android 16/17 소스 경로, 빌드명 예시 3~5개, GHE 주소·조직·카테고리별 팀 이름, Gerrit CL 링크 예시, Jira URL 예시
- 샌드박스 이슈 DB 레포(빈 레포)
- **기존 자산**: 검증된 로그 파서 코드 경로, 파서가 판별하는 경우별 실제 로그, data 이슈 분류 자료, data 분석 스킬 이름
- 과거 해결 Jira 20~30건 목록(카테고리별 3건 이상, S-5 재현 평가용)
- Jira MCP가 **사용자 범위(user scope)** 로 등록돼 있는지

### 반입 전에 사내 PC에서 할 것

사내 레포에 커밋하기 **전에** 묶음을 임시 폴더에 풀어서 확인한다. 막히는 것을 S 단계 전에 찾기 위해서다.

**1) 환경 점검** (30분)

| 항목 | 확인 | 필요 조건 / 이유 |
|---|---|---|
| OS | `lsb_release -a` | **Ubuntu** |
| Python | `python3 --version` | **3.11+** |
| 패키지 | 사내 미러 접근(`pip download pyyaml` 등)과 `python3.11 --version`(22.04는 `python3`가 3.10) | 의존성은 `pyproject.toml`에 고정돼 있다. `python3 -c "import yaml; print(yaml.__with_libyaml__)"`가 True면 YAML을 C 로더로 읽어 빠르다(False여도 동작) |
| git | `git --version` | **2.31+** (guard의 `rev-parse --path-format`, worktree `--no-track`, `push --force-with-lease=<ref>:<sha>`) |
| gh | `gh auth status --hostname <GHE 호스트>` | 실패하면 쓰기 작업 전부 불가(읽기 분석은 가능) |
| Claude Code | `claude --version`, `claude mcp list` | 플러그인·hooks 지원 버전, Jira MCP 서버 이름과 사용자 범위 등록 (정밀 확인은 S-2) |
| GHE 권한 | 웹 | 레포 3개(플러그인, 샌드박스 이슈 DB, 운영 이슈 DB) 생성, **브랜치 보호·CODEOWNERS 필수 리뷰 설정 권한**(없으면 로컬 hook이 유일한 방어선, S5) |

**2) 묶음 확인과 테스트 재현** (15분)
```
mkdir -p ~/tt-draft && cd ~/tt-draft && unzip ~/telephony-triage-import-v1.zip
sha256sum ~/telephony-triage-import-v1.zip   # 사외에서 적은 값과 같은지
python3.11 -m venv .venv && . .venv/bin/activate   # `python3`가 3.11+면 python3. 3.10이면 python3.11
pip install '.[test]'   # 사내 미러. 고정 버전이 미러에 없으면 `test_r10_dependency_manifest_has_complete_pins` 1건 실패는 예상, `SITE_PROFILE.md`에 기록
python3 -m pytest -q tests                    # 사외와 같은 결과여야 한다 (10~15분)
```
사외에서 통과한 테스트가 실패하면 환경 차이(파이썬·git 버전, 로케일, 경로)다. 반입 전에 원인을 잡는다.
개발 중 코드를 고친 뒤에는 전체 대신 `python3 tools/related_tests.py --run`(바뀐 파일의 관련 테스트 + 경계 검사)을 돌린다. 전체 `pytest tests`는 도구가 `full: true`로 판단할 때, 반입 묶음을 만들기 직전, 요청할 때만 쓴다.

**3) S-0 선행 확인** (권장, Claude 없이 30분) — 사내 로그 형식이 사외 파서 가정과 얼마나 다른지
```
ROOT=$(python3 tests/helpers/make_plugin_root.py | tail -1)   # site-defaults.yaml 없이 돌리는 임시 루트
unzip ~/issue-db-skeleton-v1.zip -d ~/tt-skel
python3 tools/s0_stats.py <logcat1> <logcat2> <logcat3> \
    --rules ~/tt-skel/parser-rules --tz Asia/Seoul --year 2026 --plugin-root $ROOT
```
- 로그 3~5개(카테고리 섞어서, 듀얼 SIM 1개 이상). 숫자는 `SITE_PROFILE.md`에만(아직 없으면 메모 후 S-1에서 옮김).
- 읽는 법·판정은 `docs/development/S0_PROBE_CHECKLIST.md`. 시각 파싱 90% 미만·RIL 요청 0건·phone_id 0%처럼 많이 다르면, **반입 전에** 정성 결론("슬롯 표기가 `[SUB<n>]`")을 사외로 가져가 고치고 묶음을 다시 만드는 게 싸다.

### 첫 반입
```
git clone <사내 GHE>/<org>/telephony-triage-plugin.git && cd telephony-triage-plugin   # 사내에 만든 빈 레포 (README·.gitignore 없이 생성 — 초안과 같은 경로의 파일이 있으면 첫 반입이 멈춘다)
git switch -c draft-import/<날짜>
python3 ~/tt-draft/tools/import_draft.py ~/tt-draft --dest . --label import-v1 --dry-run
python3 ~/tt-draft/tools/import_draft.py ~/tt-draft --dest . --label import-v1 --check-boundary   # 첫 반입: 전체 복사 + .draft-manifest.json 생성
python3 -m pytest -q tests
git status --short                                     # .venv/ 등 무시돼야 할 파일이 없는지
git add -A && git commit -m "사외 초안 반입: import-v1"     # .draft-manifest.json 포함 → PR → main 머지
```
- `.local-draft`는 원본에 있어도 가져오지 않는다.
- 이슈 DB: **샌드박스**는 뼈대를 그대로 push(S-5 시험용). **운영**은 S-4a 시작 때 뼈대로 만든다(브랜치 보호·CODEOWNERS). placeholder 규칙은 S-4에서 실제 태그·문구로 바꾸고, 그 전에는 파일럿·사용자에게 열지 않는다.
- GHE 서버에서 **브랜치 보호**(main 직접 push 금지, CODEOWNERS 필수 리뷰)를 켠다.
- Claude Code를 플러그인 레포 루트에서 열고 아래 "첫 사내 세션에 붙여 넣을 컨텍스트"로 S-1을 시작한다.

### 세션별 입력 (플러그인 레포 루트에서 Claude Code 열기)

첫 사내 세션에서 Claude가 "사외 초안 계속 / 사내 보완 시작"을 물으면 **사내 보완**을 고릅니다(이후에는 `SITE_PROFILE.md`로 자동 판별).
| 단계 | 입력 | 하는 일 |
|---|---|---|
| S-0 (선택) | `S-0 진행해줘` — 또는 Claude 없이 `tools/s0_stats.py` (절차 `docs/development/S0_PROBE_CHECKLIST.md`) | 반입 전·S-1 전 언제든. reference 파서·매처만 실제 로그 3~5개에 Python으로 돌려 시각 파싱 비율·RIL 페어링·phone_id 추출·시계 이상을 봄. 결과 숫자는 `SITE_PROFILE.md`에만, 사외로는 정성 결론만. 로그 형식이 다르면 S-4가 커지므로 **권장** |
| S-1 | `사내 보완 모드야. S-1 진행해줘` | TODO 목록 확인, 자료 받고 `SITE_PROFILE.md` 작성, 오프라인 평가 기준(1위 정확도 등) 합의 |
| S-2 | `S-2 진행해줘` | 플러그인 로드·hook·MCP 도구 이름 형식 확인, 다른 점만 수정 |
| S-3 | `S-3 진행해줘` | `site-defaults.yaml`(Jira 서버·도구 매핑·필드 매핑, GHE 등), 이슈 DB 설정 |
| S-4a | `S-4a 진행해줘` | **① 기존 파서 포팅**: 포팅 전 골든 출력 저장 → 이벤트 매핑 확인 → 사내 백엔드로 포팅 → 골든 테스트 통과. **② 기존 data 분류 import PR**. **③ 분석 스킬 연결** |
| S-4 | `S-4 진행해줘. 이번엔 call만` | 운영 이슈 DB의 placeholder 규칙을 실제 태그·문구로 바꾸고, 카테고리마다 자주 나오는 유형 5~10개를 실제 마스킹 fixture와 함께 `import` PR로 시드 (카테고리별로 세션 분리 권장) |
| S-5 | `S-5 진행해줘. 샌드박스는 <주소>` | 실제 Jira·로그로 dry-run, 샌드박스에 PR 1건. 과거 해결 Jira 20~30건 라벨셋으로 `tools/offline_eval.py` 정확도 게이트 |
| S-6 | `S-6 진행해줘` | 남은 `REVIEW-OPEN.md` 정리, 운영 이슈 DB에 합성 fixture·placeholder가 남았는지 확인 |
| S-7 | `S-7 진행해줘` | 마켓플레이스 등록, 카테고리별 파일럿(10~20건), 첫 월간 리뷰 → 전체 확대 결정 |

### 첫 사내 세션에 붙여 넣을 컨텍스트 (S-1 기동용, 한 번)

사내 Claude Code가 설계 문서 전체를 읽지 않고 시작하게 하는 머리말입니다. `<...>`만 채워서 그대로 붙입니다.

```
[무엇] telephony-triage — Android Telephony 이슈를 Jira+logcat으로 분석해 사내 이슈 DB 레포(telephony-issue-db)에
카테고리>유형>원인으로 누적하는 Claude Code 플러그인. 사외에서 만든 초안을 지금 사내로 반입했다 (반입 label: <.draft-manifest.json의 label>).
판정은 스크립트(파서→매처→검증)가 하고 Claude는 설명·초안·사용자 확인만 한다.

[모드] 사내 보완. 개발 Phase D0~13은 사외에서 끝났으니 다시 하지 않는다. 할 일은 15-local-draft.md §15.5의 S-1~S-7뿐이다.
처음 물으면 "사내 보완"을 고르고, S-1에서 SITE_PROFILE.md를 만들어 "모드: 사내 보완"을 적는다. 이후 세션은 그 파일로 이어간다.

[읽을 것 — 이것만]
`python3 tools/context_pack.py S-n` 출력(그 단계의 §15.5 행·비고·읽을 파일과 절, 목록은 docs/tasks.md). CLAUDE.md는 자동 로드.
읽지 않는다: docs/history/ 전체, 11-phases.md, pack에 없는 docs/design/ 파일, ARCHITECTURE_REVIEW(개선 작업은 사외 트랙).
파일럿 지표(PR까지 시간·중도 취소 비율·작업당 질문 수)는 `python3 tools/usage_stats.py`로 뽑는다.
TODO(SITE) 목록은 문서가 아니라 `python3 tools/list_site_todos.py`로 뽑는다.

[지킬 것]
- 사내 값·코드는 SITE_PATHS에 적힌 경로에만 (SITE_PROFILE.md, docs/site/, plugin/site-defaults.yaml, parser_backends/site/, adapters/site_*, tests/golden/, tests/site/).
  그 밖의 사외 파일(docs/design/, plugin/scripts/ 공통 코드, 테스트)에 사내 문자열을 넣지 않는다 — 재반입(tools/import_draft.py) 때 충돌한다.
- 설계 문서는 고치지 않는다. 사내 확인값·결정·차이는 SITE_PROFILE.md에만 쓴다 (형식: 14-site.md §14.3).
- 새 md 파일을 만들지 않는다. 로그는 채팅에 붙이지 말고 파일 경로로 다룬다. 마스킹되지 않은 로그를 이슈 DB·fixture·문서에 남기지 않는다.
- 단계가 끝나면 완료 기준을 점검하고 요약한 뒤 사용자 확인을 받고, SITE_PROFILE.md 진행 상태를 갱신하고 세션을 닫는다.
- 막히면 우회하지 말고 보고한다 (git 충돌, 인증, MCP 부재, 버전 불일치, site-defaults.yaml 없음).

[내가 줄 자료] Jira 키 <2~3개>, 카테고리별 logcat 경로 <...>, Android 16/17 소스 경로 <...>, 빌드명 예시 <...>,
GHE <호스트/org/팀>, 샌드박스 이슈 DB <주소>, 기존 파서 코드 경로 <...>, Jira MCP 서버 이름 <...>.
[시작] S-1 진행해줘. 먼저 확인 목록(TODO(SITE) 도구 출력 + REVIEW-OPEN.md)을 S번호별로 묶어 보여주고, 위 자료로 채울 수 있는 것부터 SITE_PROFILE.md에 적어라.
```

이후 세션은 머리말 없이 `S-n 진행해줘`면 됩니다(`SITE_PROFILE.md`로 판별). 긴 공백 뒤나 다른 PC면 위 블록의 **[모드]·[읽을 것]·[지킬 것]** 세 단락만 다시 붙입니다.

### 기존 파서 포팅의 핵심 (S-4a ①)
- **검증된 판별 로직은 코드 그대로** 두고 `builtin.data.*` 이벤트로 노출합니다. 시그니처가 이 이벤트를 참조합니다.
- **새로 생기는 유형은 코드가 아니라 규칙 파일**(`parser-rules`)로 추가합니다. 팀원이 PR만으로 파서를 발전시킬 수 있게 하기 위해서입니다.
- **포팅 전 골든 출력**을 저장하고, 포팅 후 결과가 같은지 테스트합니다. "검증된 파서"라는 가치를 지키는 장치입니다.
- 이슈 DB fixture는 마스킹돼 있습니다. 마스킹은 같은 값을 같은 번호(`<CELL#1>`)로 바꾸므로 값 비교 로직은 유지되지만, **원본과 마스킹 로그에서 판별이 같은지** 포팅 전에 확인합니다.
- 이슈 DB에 필요한 파서 백엔드 버전(`parser_backend`)이 기록되어, 팀원마다 결과가 달라지지 않습니다.
- 포팅이 어려우면(다른 언어 등) 기존 파서를 그대로 실행하고 출력만 변환하는 어댑터 방식으로 갑니다.

### 사내 토큰 절약
- 세션 시작은 `S-n 진행해줘`만. 진행 상태는 `SITE_PROFILE.md`에 있습니다.
- 로그는 채팅에 붙이지 말고 **파일 경로**로 줍니다.
- 에러는 "테스트 실패한 것만 봐줘".
- 단계가 끝나면 세션을 닫고 새로 엽니다.

### 사외 코드를 다시 반입할 때
```
git switch -c draft-import/<날짜>
python3 <새 초안>/tools/import_draft.py <새 초안> --dest . --label import-v2 --dry-run
python3 <새 초안>/tools/import_draft.py <새 초안> --dest . --label import-v2 --check-boundary
python3 -m pytest -q tests        # 골든 포함, 그 뒤 운영 이슈 DB에 db_regress --all → 병합
```
- `SITE_PATHS` 경로(사내 코드·값)는 건드리지 않는다.
- 사내에서 사외 파일을 고친 게 있으면 목록을 보여주고 **멈춘다(종료 코드 1)**. 그 변경 요지를 사용자가 사내 정보 없이 직접 타이핑해 사외에 전달하거나, 되돌린 뒤 다시 실행한다. 이미 새 초안과 같은 사내 수정은 멈추지 않는다.
- 되돌리기: `git restore --source=$(git log -1 --format=%H -- .draft-manifest.json) -- <파일>` (마지막 반입 커밋의 사외 버전. manifest는 `import_draft.py`만 바꾼다).
- 새 초안 `SITE_PATHS`에만 있는 줄은 경고로 나온다 — 사내 `SITE_PATHS`에 직접 추가한다(도구는 사내 `SITE_PATHS`를 쓰지 않는다).
- `--check-boundary`: 반입 뒤 모습을 사내 패턴(`docs/site/boundary-patterns.txt`, 실제 회사·서버·팀 이름)으로 검사한다. 위반이면 **반입하지 않고** 종료 코드 1. 적용 중 실패하면 자동으로 되돌린다.
- 사외에서 지운 파일은 지우고, 사내에서 새로 만든 비-`SITE_PATHS` 파일은 지우지 않고 알려준다(사내 전용이면 `SITE_PATHS`로).
- 설계 문서가 바뀌었으면 `14-site.md §14.5`대로 `SITE_PROFILE.md`와 비교해 영향을 본다.

### 막혔을 때
- 사내 환경 문제 → 사내에서 수정.
- 설계 문제 → 사내 Claude에게 아래 틀로 정리시킨 뒤 **사용자가 직접 타이핑해** 사외 세션에 전달(파일·로그·diff·요약 파일은 반출하지 않는다) → 사외에서 문서·코드 수정 → 재반입.

  사내 세션 입력:
  ```
  이 문제를 사외 수정 요청 틀(어디/증상/형식/요청/확인, 각 한 문장)로 정리해줘. 실제 로그 문구·태그·숫자·경로·이름은 넣지 말고 형식만 서술해.
  ```
  틀 (5줄, 타이핑 2분):
  ```
  [사외 수정 요청 #n]
  어디: plugin/scripts/platforms/android/logcat.py (슬롯 표기 regex)
  증상: 사내 로그에서 phone_id 추출률이 매우 낮음. 슬롯 접두어 형식이 사외 가정([PHONE<n>])과 다름
  형식: 메시지 앞에 대괄호+영문 3자+숫자 1자리 (실제 문자는 전달하지 않음)
  요청: 접두어 패턴을 site-defaults 또는 parser-rules 설정으로 뺄 것
  확인: 합성 로그로 재현 후 tests/test_parse_logcat.py에 케이스 추가
  ```
  | 넣어도 됨 (형식·구조 서술) | 넣지 말 것 (값) |
  |---|---|
  | "타임스탬프에 연도가 있음", "로그가 3개 파일로 회전됨" | 실제 로그 줄, 태그 이름, 문구 |
  | "슬롯 표기가 대괄호+영문+숫자 형태" | 그 영문이 무엇인지 |
  | "시각 파싱이 절반 이하"(방향) | 정확한 비율·건수 |
  | "Jira 발생 시각이 커스텀 필드이고 KST 문자열" | 필드 ID, Jira 키 |
  | 고칠 사외 파일·함수 이름 | 사내 경로, 서버·팀·사람 이름 |

  판단 기준: **사외 Claude가 그 문장만 보고 합성 로그를 만들 수 있으면** 충분하고, 만들려면 실제 값이 필요하면 넘기지 않는다.

---

## 4-1. 다른 PC·다른 에이전트에서 이어가기 (사외·사내 공통)

**레포에 있는 것만 따라온다.** 새 에이전트는 이전 대화를 모르므로, 떠나기 전에 상태 파일을 최신으로 만드는 것이 절차의 절반이다.

| 따라옴 (git) | 안 따라옴 (PC마다 다시) |
|---|---|
| 코드·테스트·설계 문서, `DRAFT_NOTES.md`(사외 상태), `GUIDE.md`, `REVIEW-OPEN.md` | `.local-draft`(gitignore, 사외 모드 표식) |
| 사내 레포면 `SITE_PROFILE.md`·`plugin/site-defaults.yaml` 등 `SITE_PATHS` 전부 | `~/.telephony-triage/config.yaml`(사용자 config), `~/.telephony-triage/work/`(**작업 계획·lock·worktree·스냅샷**) |
| | Python 패키지(`pyyaml`, `jsonschema`, `pytest`), `gh` 인증, Jira MCP 등록, Claude Code·플러그인 설치 |
| | `tests/skill_evals/workspace/`(eval 산출물), 대화 기록 |

**떠나기 전 (항상)**
1. 진행 중인 이슈 DB 쓰기 작업을 끝내거나 버린다 — `plan.json`·lock은 PC에 있어 따라오지 않는다. `python3 plugin/scripts/db_pr.py lock status`, 끝난 작업은 `db_pr.py discard <wt>`. 계획이 있는 열린 PR의 `sync-pr`는 원래 PC에서 하거나, 새 PC에선 수동 재동기화(`06 §6.3`).
2. 상태 파일 갱신 — 사외 `DRAFT_NOTES.md` "진행 상태"·"남은 일", 사내 `SITE_PROFILE.md` "진행 상태". 에이전트에게: `지금까지 한 일을 진행 상태에 반영하고 커밋·push해줘.` 같은 트랙을 다른 에이전트가 동시에 하지 않게 "남은 일"에 "진행 중 — 브랜치 X"를 적는다.
3. 작업 브랜치에 커밋·push.

**사외, 새 PC**
```
git clone <사외 레포 URL> && cd telephony-triage
python3.11 -m venv .venv && . .venv/bin/activate   # `python3`가 3.11+면 python3
pip install '.[test]'
touch .local-draft            # 안 만들면 Claude Code가 모드를 묻는다 → "사외 초안"
python3 -m pytest -q tests    # 기준선 (Ubuntu 10~15분)
```
첫 메시지: `DRAFT_NOTES.md의 "남은 일"에서 다음 할 일을 확인하고, 그 작업의 근거 문서만 읽고 시작해줘. docs/history/는 읽지 마.`
원본 문서 zip·eval 산출물은 레포에 없어도 된다(`docs/design/`이 정본, eval은 새 iteration 경로로 다시 만든다).

**사내, 새 PC** (`SITE_PROFILE.md`가 커밋돼 있어 모드는 자동)
```
git clone <사내 GHE>/<org>/telephony-triage-plugin.git && cd telephony-triage-plugin
python3.11 -m venv .venv && . .venv/bin/activate   # `python3`가 3.11+면 python3
pip install '.[test]'
python3 -m pytest -q tests    # 골든 포함, 이전 PC와 같은 결과여야 한다
claude mcp list               # Jira MCP 사용자 범위 등록 확인
```
- S-1~S-3 중이면 바로 `S-n 진행해줘`.
- S-4 이후(이슈 DB 사용)면 Claude Code에서 `/telephony-triage:setup` — config 작성, `scripts_path`, 이슈 DB clone, Jira 도구 매핑, `core.hooksPath .githooks`, 스냅샷. S-5 이후면 `gh auth status` 통과 필요.
- 긴 공백 뒤·새 에이전트면 위 "첫 사내 세션에 붙여 넣을 컨텍스트"의 **[모드]·[읽을 것]·[지킬 것]** + `S-n 진행해줘`.

**Claude Code가 아닌 에이전트(Codex 등)**: `AGENTS.md`만 자동으로 읽고 `CLAUDE.md`·`@SITE_PROFILE.md` import는 안 될 수 있다. 첫 메시지에 `먼저 CLAUDE.md, docs/design/12-principles.md와 DRAFT_NOTES.md(사내면 SITE_PROFILE.md)를 읽어라. Claude 전용 기능(플러그인 로드, hooks, skill-creator, /telephony-triage:* 커맨드)은 쓸 수 없으니 스크립트·테스트·문서 작업만 한다.`를 붙인다. Phase 13(스킬 eval)·S1 실험·S-2는 Claude Code에서만 가능하다. 사내에서 다른 에이전트를 쓸 수 있는지는 회사 정책이 정한다.

---

## 5. 설치와 첫 설정 (팀원 공통)

1. 사내 마켓플레이스에서 `telephony-triage` 설치
2. 이슈 DB 레포 clone
3. `/telephony-triage:setup`
   - GHE 아이디, 이슈 DB 경로, 로그 폴더, (선택) Android 16/17 소스 트리 프로필
   - 이미 등록된 Jira MCP를 찾아 도구 매핑을 확인 (팀 기본값이 있으면 확인만)
   - git pre-commit hook 설치, 읽기 스냅샷 생성
4. 연습: `/telephony-triage:analyze <샘플키> <로그> --dry-run` (아무것도 올리지 않음. gh 로그인 전에도 가능)

---

## 6. 사용법

### 커맨드 한눈에
| 커맨드 | 언제 |
|---|---|
| `analyze <JIRA> [로그...] [--code <프로필>] [--dry-run] [--failed-step <한 줄>] [--steps-file <파일>] [--clock-offset <±시간>] [--analyzer \| --no-analyzer] [--explore \| --no-explore]` | 로그로 이슈 분석하고 분류·기록. 실패 스텝은 선택 보조 정보이고, 시험 절차(`--steps-file`: txt/csv·html·zip·붙여넣기)의 PASS 스텝 순서를 로그의 흔적과 맞춰 분석 범위를 정한다(`--answer anchor=off`로 끔). 맞는 규칙이 없으면 Claude 탐색 분석(가설)을 할지 묻는다 |
| `record <JIRA> [--cause <ID> \| --new-cause <유형> \| --new-type <카테고리> \| --unresolved <유형>] [--fixture <로그>] [--resolved-fixture <로그>] [--failed-step <한 줄>] [--steps-file <파일>]` | 직접 해결한 이슈를 히스토리만 기록 |
| `search <증상 문장\|키워드\|JIRA\|ID>` | 비슷한 이슈가 있었는지 찾기. 예: `search 데이터 안 붙어, 이슈 번호 알려줘` |
| `fix-submitted <원인 ID> --ref <CL> --fixed-in <브랜치>[:<빌드>]` | 수정 CL이 머지됐을 때 |
| `verify-fix <원인 ID> <수정 빌드 로그>` | 수정 빌드에서 재발 안 하는지 확인 → fixed |
| `validate [--cause <원인 ID> <적용 후 로그>] [--extra <로그...>]` | 직접 편집 검사 / 해결책 효과 검증 |
| `sync-pr [브랜치]` | 내 PR이 머지 대기 중인데 main이 바뀌었을 때 (내 작업 계획을 최신 main에 다시 적용) |
| `sync`, `preview`, `review [카테고리]`, `setup` | 최신화, 생성 결과 미리보기, 월간 리뷰, 설정 |
| `migrate --to <N>` | (메인테이너) 자기 `migrate/schema-v<N>` 브랜치에서 스키마를 올림. PR은 직접 만든다 |

### 시나리오 1: 이슈 분석 (가장 흔함)
```
/telephony-triage:analyze ABC-12345 ~/logs/radio.txt ~/logs/main.txt
```
1. 이슈 DB 최신화 (분석은 별도 스냅샷에서, 내 clone은 main이고 깨끗할 때만 fast-forward)
2. Jira 읽기(텍스트는 즉시 마스킹, 원문은 저장 안 함) → 발생 시각(없으면 로그에서 증상 시각 후보 제시) → Android 버전 확인 → 코드 경로 선택(16/17 프로필 추천)
3. 로그 파싱(bugreport를 주면 logcat 섹션만 추출. 발생 시각이 로그 범위 밖이면 "로그 범위 밖"으로 따로 알림, 듀얼 SIM은 슬롯별로 판별) → 시그니처 매칭(맞는 유형이 없으면 "후보 없음" 절에 설명 기반 유사 후보와 타임라인 요약) → 코드 분석 → (data면) 분석 스킬 심층 분석을 할지 물어봄 (토큰 추가 사용). 후보 없음·원인 미확인이면 Claude 탐색 분석(타임라인·소스로 가설 1~3개, 점수·분류에는 안 씀)을 할지 물어봄
   - **실패 스텝 기준 분석(선택)**: 실패 스텝이 **어디를(시간 범위)·무엇을(우선 유형)** 볼지 정하고, **왜(원인 S/C)** 는 여전히 로그 시그니처가 정한다. 실제 logcat에는 시험 스텝 마커가 없고 시험 장비 시계가 단말과 다를 수 있어 스텝 시각은 대개 모른다. 그래서 시험 절차(Jira 첨부 zip의 `report.html`, 또는 개발자가 붙여넣은 스텝 목록)의 **PASS 스텝 순서**를 이슈 DB `step_events` 규칙(스텝 → 로그 흔적, CP 스텝은 관측 불가)으로 로그에서 찾아, 마지막으로 확인된 스텝 뒤를 실패 구간으로 분석한다(시험은 첫 FAIL에서 멈춘다). 장비-단말 시계 차를 `--clock-offset`으로 직접 주면 steps-file의 시각도 쓴다(모르면 쓰지 않고 경고). 못 맞추면 사유와 함께 Jira 발생 시각 기준으로 분석한다. Jira 시각과 많이 다르면 경고만 낸다(구간은 안 바뀜). 구간이 너무 좁아 원인이 안 잡히면 `--answer anchor=off`로 다시 실행한다. 같은 스텝이 쌓인 유형(또는 `step_focus.map`)은 순위에서만 우선한다(점수·S/C 불변). 로그 마커(`failed_step.marker_patterns`)는 기본 꺼짐이다. steps-file이 없으면 이전과 같다.
4. 리포트: 분류 후보, 근거 로그, 원인, **해결책**, 수정 상태(이미 수정됨/회귀 의심), 기존 사례 Jira
5. "이 분류가 맞나요?" → 예 / 다른 원인 / 새 원인 / 새 유형 / 원인 미확정
6. 분석하는 동안 main이 바뀌어 내 계획이 건드리는 원인이 먼저 수정됐으면(drift) 항목마다 어느 값을 쓸지 물어봄
7. **push 전 확인 화면**(변경 파일, README 미리보기, 검증 결과, 커밋 메시지) → 승인 → PR
8. 카테고리 오너가 리뷰 후 머지

### 시나리오 2: 새 원인·새 유형 발견
- 5단계에서 "새 원인" 또는 "새 유형" 선택 → 제목·해결책·시그니처 초안 제시
- 필요한 파서 규칙 초안과 fixture(로그 최소 구간, 마스킹)를 함께 제시
- **자동 검증**: 새 규칙이 이 로그를 잡는지(R1·R2), 정상 로그를 잘못 잡지 않는지(R3), 기존 분류를 깨지 않는지(R4), 기존 이벤트를 바꾸지 않는지(R5)
- 새 시그니처가 **다른 카테고리의 기존 fixture**에서도 잡히면(그 로그에 실제로 두 현상이 있는 경우) "시그니처 좁히기 / 그 fixture에서 이 원인도 허용(`also_allowed`)"을 묻는다. 허용하면 그 카테고리 오너가 리뷰어로 붙는다
- 새 유형은 증상 시그니처가 필수. 새 원인은 원인 시그니처를 나중에 넣도록 보류할 수 있음(리뷰 대상)

### 시나리오 3: 직접 해결한 이슈 기록
```
/telephony-triage:record ABC-12345 --cause DATA-001-02
/telephony-triage:record ABC-12346          ← 대화형: 비슷한 유형을 보여주고 고르게 함
```
- 로그 분석 없이 기록. 검증과 PR 절차는 analyze와 같고, PR에 "수동 기록" 표시.
- "고쳤다"는 `fix-submitted`까지만. `fixed`는 verify-fix로만.
- 해결책 효과는 근거(다른 Jira 키, 적용 후 로그)가 있어야 "검증됨".

### 시나리오 4: 코드 수정 후 재발 확인
```
/telephony-triage:fix-submitted CALL-001-01 --ref <CL> --fixed-in main-dev:BUILD_X
/telephony-triage:verify-fix CALL-001-01 ~/logs/after_fix.txt
```
- 수정 빌드 이후 로그인지, 재현 시나리오를 수행한 로그인지 확인 후 판정: 통과(fixed) / 부분 통과 / 실패(open으로 되돌림) / 판단 불가
- 통과하면 수정 후 로그가 회귀 테스트에 추가되어, 이후 누가 규칙을 넓혀도 재발 판정이 깨지지 않음

### 시나리오 5: 기존 카테고리에 안 맞는 이슈
- 가장 가까운 카테고리에 태그와 함께 넣어 기록.
- 같은 성격이 3개 이상 쌓이면 메인테이너가 새 카테고리 PR.

### 모델 선택 (3C~3E eval 근거)

- Sonnet 기본: analyze·record·fix-submitted·verify-fix·sync-pr·search·5-1 분석 스킬.
- verify-fix: W3부터 흔적 시그니처 없는 코드·설정 수정 유형을 `db_verify fix`가 종료 코드 2로 막아 Sonnet 기본(eval 25 Sonnet 3/3, W3). 사내 S-2 재실행에서 다시 확인한다.
- 5-2 탐색은 Sonnet. 가설 품질이 중요하면 Opus를 고른다.
- 바꾸는 법: `/model`. 커맨드 frontmatter `model` 고정은 사내 S1 확인 뒤(`14-site.md` S1).

### 팀 운영
| 누가 | 무엇을 |
|---|---|
| 기여자 | analyze/record로 PR. 머지 대기 중 main이 바뀌면 `sync-pr`(작업 계획이 작성자 PC에 있으므로 작성자가 실행). 직접 편집한 브랜치는 rebase → `db_build --write` → `validate` 후 push |
| 카테고리 오너 | 자기 카테고리 PR 리뷰(다른 카테고리가 내 fixture에 `also_allowed`를 넣은 PR 포함), 월 1회 `/telephony-triage:review <카테고리>` (미확정 누적, 품질 낮은 시그니처, 중복, 급증, 미검증 해결책, `also_allowed` 누적). 조치는 직접 편집하거나 Claude와 계획 파일을 만들어 PR |
| 메인테이너 | 파서 규칙·스키마·hook 변경 리뷰, 새 카테고리(`category/<key>` 직접 편집), 스키마 마이그레이션(`migrate/schema-v<N>` 브랜치에서 `migrate --to` 후 직접 PR), 사후 lint가 알린 ID 중복·Jira 중복 정리(수동) |
| 모두 | 이슈 DB README(카테고리별 유형·원인·해결책·Jira)와 STATS(Top 원인, 모델·SW별 분포, 수정 필요 순위) 확인 |

---

## 7. 지켜지는 안전장치 (자동)

- Jira는 **읽기만** (쓰기 도구 호출 차단)
- push 전 **항상 사용자 확인**, main 직접 push 차단
- 로그의 IMSI·전화번호·SIP URI·인증 값 등 **자동 마스킹**, 마스킹 안 된 커밋 차단. Jira 텍스트도 마스킹하고 원문은 저장하지 않음(구조화 필드 + 확인한 한 줄 요약만)
- 사용자의 이슈 DB clone은 **브랜치를 바꾸거나 파일을 고치지 않음** (작업은 임시 폴더에서, 최신화는 main이고 깨끗할 때 fast-forward만. Claude의 Write/Edit 도구로 clone 안 파일을 쓰는 것도 차단)
- `git pre-push` hook이 main 대상 push와 승인 토큰 없는 push를 거부. 단, 로컬 장치는 우회 가능하므로 **GHE 브랜치 보호(직접 push 금지, CODEOWNERS 필수 리뷰)가 서버에서 켜져 있어야 함**
- 검증을 건너뛴 항목은 **통과로 표시하지 않음**
- 한 사람이 동시에 두 작업을 하지 않음 (세션 lock. 이전 세션이 비정상 종료했으면 확인 후 해제)
- 분석 중에 main에서 바뀐 내용을 **자동으로 덮어쓰지 않음** (drift를 물어봄)

## 8. 문서 위치

| 보고 싶은 것 | 파일 |
|---|---|
| Claude Code 지침 진입점, 모드 판별 | `CLAUDE.md` |
| 원칙(사용자 확인·push 승인 등) | `docs/design/12-principles.md` |
| 설계 문서 지도 | `docs/design/README.md` |
| Phase별 할 일·완료 기준 | `docs/design/11-phases.md` |
| 사외 초안·사내 보완 절차 | `docs/design/15-local-draft.md` |
| 기존 Jira MCP·파서·분류·분석 스킬 활용 | `docs/design/16-existing-assets.md` |
| 사내 확인 항목 목록 | `docs/design/14-site.md` |
| 워크플로우 상세 | `docs/design/07-workflow.md` |
| 공통 규칙 원본 | `docs/design/contracts.md` |
| 사내 정보가 있어야 판단할 남은 항목 | `REVIEW-OPEN.md` |
| v1에서 뺀 설계(3-way replay 등) | `docs/design/99-deferred.md` |
| 11차 변경안(동작 검토 U1~U17, 이력) | `docs/history/REVIEW-11.md` |
| 변경 이력 | `docs/history/CHANGES.md` |
