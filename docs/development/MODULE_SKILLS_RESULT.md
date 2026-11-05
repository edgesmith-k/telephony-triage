# 계획 H 결과 노트 (모듈 스킬 레포 + +1 병합)

단계표는 `MODULE_SKILLS_PLAN.md §4`. 이 파일은 단계마다 리뷰·재측정에서 P2로 남긴 것(결정 (r): P0·P1만 고치고 P2는 반입 뒤 후보)과 단계 결과를 적는다.

## B1·B2 모듈 스킬 받기·5-1/5-2 흐름 (11/05, 묶음 구현 — 설정·doctor·guard·문서 갈래)

범위: B1(설정·받기·받은 내용 점검·guard 12·모의 레포)과 B2(모듈 고르기·모듈 보기·출력 관문·리포트·표시·계측·eval)를 한 번에 구현했다(11/05 일정 단축 ③). 이 절은 설정·doctor·site 점검·guard·문서 갈래의 기록이다. 유료 eval 비용 장부는 메인 세션이 이 파일에 따로 적는다.

설정·doctor·guard에서 한 것:
- `common/userconfig.py`: `module_skills{remote, base_branch}`(최상위, `from_site_defaults`가 옮긴다, `builtin()`에는 없다), `prefer`·`skill_dir` 검사, `deep_source`(5-1 출처의 유일한 구현), `deep_source_problem`, 폐지 하위 키 경고(`inputs`·`max_tokens_hint`), B1-19 경고, `runtime.label` 경고, `read_roots`(지연 import). 어느 함수도 잘못된 입력에 예외를 내지 않는다(guard 경로).
- 새 `common/skillpath.py`(설치 스킬 `SKILL.md`: `skill_dir` → `installed_plugins.json` `installPath` → 설정 폴더 `skills/` → OpenCode `skills/`, 하나만 찾았을 때만), 새 `common/provenance.py`(`env_info`, 주소는 종류만).
- `config.py`: `set` 키 종류(`module-remote`·`ref`·`prefer`·`path`, `module_skills`는 `--platform` 없이), `module_problems`; `check` 경고·`deep_sources`·`--roots`; doctor `config` 행 경고 가지, 조건부 `module_skills` 행(기본 설치는 13행 그대로).
- `guard.py`: 규칙 12 (a)(b)(이름 기반 관리 clone·lock·skill-wt, 기록 5종, `mv`·`ln`·`rsync` 원본, git 읽기 목록·경로 옵션·clone/init 대상), 규칙 11 대상에 모듈 원격(`remote_slugs`, 사용자 config 없이도), degraded `_module-skills` 쓰기 deny, 문서 행 6·11·12.
- `tools/site_checks.py` `s4a.analyzers`: remote가 없으면 문구 그대로.

**설치 스킬 위치 확인(R9, $0)**: Claude Code 2.1.318로 빈 플러그인(스킬 1개)을 로컬 디렉토리 marketplace에서 임시 `CLAUDE_CONFIG_DIR`에 설치했다(`claude plugin marketplace add <dir>` → `claude plugin install emptyp@localmkt`, 모델 호출 없음). `plugins/installed_plugins.json` = `{"version": 2, "plugins": {"emptyp@localmkt": [{"scope": "user", "installPath": "<cfg>/plugins/cache/localmkt/emptyp/0.1.0", "version": "0.1.0", "installedAt", "lastUpdated"}]}}`, 스킬은 `<installPath>/skills/hello/SKILL.md`. 같은 모양을 `tests/test_skillpath.py` `R9_INSTALLED`로 고정했고 `skillpath`에는 `TODO(SITE:S1)`을 두지 않았다. 사내 버전이 다를 수 있으므로 아래 반입 뒤 5-1 점검은 버전 재확인으로 남긴다.

**출처 기록 환경 변수(B2-7)**: Claude Code가 `ANTHROPIC_MODEL`·`ANTHROPIC_DEFAULT_*_MODEL`·`ANTHROPIC_BASE_URL`을 Bash까지 넘기는지는 이 갈래에서 확인하지 않았다(가짜 모델 서버 실행은 메인 세션 몫). 넘어오지 않으면 `모름`·`{}`·`none`이고 틀린 값은 남지 않는다. 확인하면 이 줄을 고친다.

**OpenCode 설치 스킬 모드(R40, v1 수용)**: OpenCode에서 설치 스킬은 `skill-input.json`이 가리키는 `timeline`만 읽는다(에이전트의 `events.json` 금지 규칙). 근거 원문 검사는 `events.json` 기준 그대로다(B2 §6.1). 그 차이는 MS-2(사내 Android 스킬을 모듈 문서로 합치기)에서 없어진다. I-2는 `RUNTIMES.md`에 같은 내용을 적는다.

**episodes 관문(B2 §16, R16)**: `tools/module_measure.py episodes --episodes scratchpad/logmine/design/episodes.yaml`. 처음 잰
값(oFono deep 근거 창 94/114, frozen 97에서 −3, E11 0/7)은 측정 입력이 낡은 탓이었다 — `o1-all`·`o2-all` `events.json`이
ENT를 `ims`로 둔 옛 변형 DB로 만들어져 `category_hint`가 먼저 적용되며(B2 줄 382) ENT 53줄이 network 모듈 밖으로 갔다. 현재
`make_variant_dbs.py`의 `issue-db-ofono-modules`(ENT → network, 결정 기록 11/05 ①)와 현재 파서(`parse_logcat.py parse --mask`,
같은 입력·같은 창)로 두 run을 다시 만들어 쟀다(A run은 그대로): oFono explore @분 72/114(frozen 73), deep 근거 창 97/114(97),
held-out 17/22·20/22(17·20), Android 43·63/88 — 모두 ±2 안, 통과. E11 deep 3/7. 이 run들이 C1/D 관문 기준이다.

**재리뷰 수정(11/05, R16 반박 검증에서 확정된 P1)**: ① 관리 clone 받기가 `fetch origin`(설정의 첫 `remote.origin.url`·설정
refspec)을 써서 값 둘·바꾼 refspec·global 설정으로 심은 커밋을 받았다 → 받기는 `module_skills.remote` 주소와
`+refs/heads/<base>:refs/remotes/origin/<base>`를 명시하고, preflight는 모든 범위에서 `remote.origin.url` 값 하나·`fetch` 기본값·
`tagopt --no-tags`만 받으며, 받은 뒤 `origin/<base>` = `FETCH_HEAD`를 본다(doctor도 같은 preflight). ② M10 뒤집힌 ICCID가 19자리
(EF_ICCID 채움 nibble `F`가 마지막 숫자 앞, `…54F6`)를 놓쳤다 → 마스킹 커밋에서 고침. ③ M1 덤프 줄 뒤 짧은 꼬리(` ...`·`(len n)`·
`[SUB0]`)와 `:` 바로 뒤가 아닌 바이트 8개 이상 연속이 남았다 → 마스킹 커밋에서 고침(첨부 로그 남은 8바이트 이상 연속 15·716·14
→ 0, 다른 종류 수·db_lint 관문 그대로). ④ eval 40·41·71 채점기가 `module --for deep` 없이 Skill 도구만 불러도 통과시켰다 →
Skill 도구는 `module --for deep` 종료 1 `설치 스킬 못 찾음` 뒤에만 센다. ⑤ OpenCode 쪽 R20·R21·R22(아래 계획 I-2 절, `RUNTIMES.md
§5.4`). 남은 것(P2): EF_IMSI hex(`08 29 …`)와 쉼표로 나뉜 ICCID 바이트는 B2 §3.2 M10 범위 밖이라 그대로 — 사내 로그에 있으면
규칙을 더한다. guard는 `python3 -c`로 관리 clone `.git/config`를 쓰는 것을 막지 않는다(받기 쪽이 이제 그 설정을 믿지 않는다).

**C0 의무(B1-4) 처리**: 템플릿 `ofono/data/SKILL.md:25-26`의 `timeline.md` 직접 지칭은 이 묶음에서 `deep-input.json`의 `timeline` 값을 읽도록 고쳤다(스킬 크리에이터, `raw-read` 규칙과 함께 — eval은 cwd에 timeline.md를 두므로 잡지 못한다). 계획된 C0 유료 재실행이 이 문서 변경도 잰다.

**관리자 한 줄(반입 노트에도)**: `site-defaults.yaml`에서 `analyzers.*.inputs`·`max_tokens_hint` 두 줄을 지운다(B1부터 읽지 않고 경고한다; `max_tokens_hint`는 S-4a에서 정한 대로). 지우기 전에는 remote가 없어도 `config.py check` 경고와 doctor `config` 행 `warn`이 난다(의도한 예외).

### 반입 노트: 바뀐 파일 → 사내 site eval (B2 §14, 11/05 사내 토큰 최소)

기준(`docs/SITE_INSTALL.md:224` 12개 전부 다시)을 바꾼 파일별 목록과 토큰 0 점검으로 대신한다. site 세트 1·2·8·9·39·45·58·59·60·61·62·75, 모델 차이 세트 13·17·18·24·29·33·37. 이 eval들은 모두 5-1·5-2에 "아니오"라 새 경로를 타지 않는다(거절 경로는 사외 eval 1로 확인).

| 바뀐 파일 | remote 없을 때 사내 영향 | 닿을 수 있는 eval | 토큰 0 점검 | LLM 재실행 |
|---|---|---|---|---|
| `common/masking.py`·`parse_logcat.py`·`mask_pii.py`(로그 마스킹) | M 부류 줄의 이벤트·자른 글만 바뀐다 | 모든 analyze eval | site eval 로그로 `triage.py run --offline-db` 전후 비교, 운영 DB fixture `db_verify`·`db_regress` 전후 같음, 골든은 토큰 차이면 사용자 승인으로 갱신 | 차이가 없거나 토큰뿐이면 없음 |
| `common/masking.py`(`find()` "all" 규칙) | `db_lint`·pre-commit `mask_pii --check`·Jira 본문 검사가 기존 내용에 새 지적을 낼 수 있다 | 2·9·61, DB 쓰기 전부 | 반입 전 읽기 전용: 운영 DB clone·`SITE_PATHS` 로그에 `db_lint --all`·`mask_pii --check` 이전·이후, site eval JOB 하나 `issue_post render` 이전·이후 — **새 지적이 있으면 반입을 멈춘다** | `render`가 다르면 61만 |
| `guard.py` | 모듈 경로·기록·모듈 원격에만 새 거부 | 1·2·8·9·39·61·62·75 | `test_hooks.py`·`test_platform_guard.py`, 12개 site eval 세션 `tools/hook_replay.py` 이전·이후 | 재생이 다를 때만(예상 없음) |
| `show_guard.py`·`common/shown.py` | 모듈 질문 면제 확대, `evidence` 기록은 `check-output` 뒤에만 | 1·2·9·39·45·59·60·61·62·75 | pytest + `hook_replay` 12개(기록이 없으면 "건너뜀" — 통과 아님) | 재생 불가면 1만 |
| `triage.py`·`triagelib/{driver,report,core}.py`·`analysis.schema.json` | remote·`prefer` 없으면 바이트 동일, `explore`는 가리기가 필요했을 때만 `mask_warnings` | 모든 analyze eval | 오프라인 `run`·`explore` 이전·이후 비교 | 차이 없으면 없음 |
| `triagelib/{modulecmd,output}.py`·`common/{modulefilter,evidence,skillpath,provenance,skillcheck,moduleskills}.py` | 동의 뒤에만 돈다 | 없음(모두 거절) | pytest + 아래 5-1 점검 | 없음 |
| `SKILL.md` | 5-1·5-2 줄만, 동의 문장 바이트 동일, ±0B | 토큰 기준 1·2·39·45·58 | 바이트 차이 보고 | 없음 |
| `reference/explore.md`·`module-skills.md`·`platforms/ofono/log-guide.md` | "예" 뒤나 oFono에서만 읽는다 | 없음 | — | 없음 |
| `userconfig.py`·`config.py`·`site-defaults.example.yaml` | 폐지 키가 남았으면 doctor 경고, 새 선택 키 `prefer`·`skill_dir`·`runtime.label` | 58 | 폐지 키 두 줄을 먼저 지우고 `config.py doctor`·`check` 이전·이후 | 그래도 다르면 58만 |
| `tools/site_checks.py` | remote 없으면 같은 출력 | — | `site_step.py check S-4a` | 없음 |
| `templates/module-skills/modules.yaml`·`tests/fixtures/module-filter/**` | site eval이 쓰지 않는다 | 없음 | 둘 다 site 모드 `check_boundary`(회사 패턴이 벤더 이름에 맞으면 `docs/site/boundary-allow.txt`에 좁은 값 예외) | 없음 |
| `usage_stats.py`·`module_eval.py`(import)·`tools/{module_measure,fixture_residual,mask_parity,module_repo_check}.py`·eval·채점기·모의·템플릿·fixture | site eval이 쓰지 않는다 | 없음 | pytest | 없음 |

eval별 한 줄:
- `1·2·8·9·39·45·59·60·61·62·75: 영향 없음 (5-1·5-2에 '아니오', 무원격 출력 바이트 동일, hook 재생 12개 일치, 이슈 DB lint·pre-commit 결과 동일)`
- `58: 영향 없음 (doctor 출력 동일 — 폐지 키 두 줄 삭제 뒤)`
- `13·17·18·24·29·33·37: 영향 없음 (5-1·5-2에 아니오 — 바뀐 줄은 동의 뒤 흐름, 거절 경로는 사외 eval 1로 확인)`

**반입 뒤 5-1 점검(토큰 0, S-단계 메모)**: 사내 5-1이 Skill 도구에서 `module --for deep` + 풀린 `SKILL.md` Read로 바뀐다. site eval은 모두 거절해 이 경로를 타지 않으므로:
1. 사내 config로 `config.py check --roots --json` → `read_roots`를 반입 노트에 옮긴다.
2. 설치 분석 스킬이 있는 1위 카테고리의 site eval 로그 하나로 `triage.py run <KEY> --offline-db <snapshot> --out <scratch JOB> …` → `triage.py module <KEY> --for deep --out <scratch JOB>`.
3. 종료 0, `read[0]`가 기대한 설치 `SKILL.md`이고 그 frontmatter `name`이 설정한 스킬 이름과 같아야 한다(Claude Code 버전이 2.1.318과 다르면 `installed_plugins.json` 모양도 여기서 다시 본다).
4. 못 찾음·둘 이상(종료 1 `설치 스킬 못 찾음`)이면 사용자가 만나기 전에 `config.py set analyzers.<cat>.skill_dir <절대 경로>`. 어느 쪽이었는지 적는다.
5. 그 파일이 작업 폴더 밖이면 `permissions.additionalDirectories`에 더하거나(사용자 설정 변경, 반입 노트에 적는다) Claude Code가 한 번 묻는 것을 받아들인다.

예상 사내 LLM 비용: 토큰 0 점검이 모두 깨끗하면 site eval 0회, 아니면 많아야 58·61과 재생이 안 된 eval 하나.

### 구현이 설계와 다르게 한 것 (설정·guard·문서 갈래)

- `skill_dir`인데 `skill`이 없는 오류는 층마다가 아니라 합친 설정에서 본다(site `skill` + 사용자 `skill_dir`를 막지 않게). 모양 오류(`~` 허용, 절대 경로, `..` 없음, 300자)는 층마다.
- doctor `module_skills` 행의 원격 표시는 80자 안에 넣으려고 `owner/repo`만 쓴다(`config.py check`와 오류 문구는 `redact_remote`의 `host/owner/repo`).
- `provenance` gateway 판정은 호스트가 `anthropic.com`이거나 `.anthropic.com`으로 끝날 때만 `anthropic`이다(설계의 `endswith("anthropic.com")`는 `evilanthropic.com`도 받는다).
- `skillpath`의 개인 스킬 폴더는 `$CLAUDE_CONFIG_DIR/skills`(없으면 `~/.claude/skills`) — Claude Code가 설정 폴더를 옮기면 스킬 폴더도 옮긴다. `plugin:` 접두가 있어도 세 위치를 모두 찾는다(하나만일 때만 고른다).
- 사내 항목은 S33·S34에 S35(`runtime.label`)를 더했다(`list_site_todos`가 `TODO(SITE:S<n>)`만 세므로). 문서의 "S1~S32"는 "S1~S35"로.
- `config.py set` 계약은 contracts §3.2 config 행에 `set` 키 종류 행을 따로 두었다.

### P2 — B1·B2 설정·guard (반입 뒤 후보)

- guard: 셸 glob·변수로 모듈 표지를 숨긴 쓰기(`rm -rf _mod*`)와 쓰기 직전 이름 바꾸기 창은 보지 못한다(스크립트 preflight·sha256 대조가 뒤를 받친다). `flock FILE git …` 래퍼도 git을 숨긴다(E).
- guard: 모듈 레포에 대한 규칙 11 사유 문구가 "이슈 DB"라고 쓴다(바이트 동일 유지). 모듈 레포 전용 메모는 E(`skill_pr`)와 함께.
- guard: 모듈 원격 경고와 기존 `issue_db.remote` 경고가 hook마다 반복된다. 기존 `issue_db.remote` 경고는 원래 값을 그대로 낸다(바꾸면 기존 출력이 바뀐다).
- doctor: 실제 clone 시험은 통합 때 없음·맞음·불일치(`test_doctor_module_row_real_moduleskills_clone_states`)를 더했다. 강제 push·더러운 트리·오래된 git은 아직 `moduleskills` 대역으로만 본다.
- `read_roots`는 설치 스킬을 찾을 때 파일을 연다(`--roots`일 때만). doctor는 설치 스킬 위치를 보지 않는다(기본 환경에서 파일 찾기를 돌리지 않으려고) — 작업 폴더 밖 `SKILL.md` 안내는 `skill_dir`가 있을 때만 나온다.

### 마스킹 관문 1 기준 미달 2건 (11/05, 메인 판정 — 누출 아님)

`mask_parity` 종류별 수가 측정 마스커(mask2+mask3)보다 둘 적다. 줄마다 대조했다(`scratchpad/mp/cmp.py`, 값은 scratch에만):
- c617353d EMAIL 21 < 22: `RIL_REQUEST_SETUP_DATA_CALL (…,<사용자>,<비밀번호>,…)` 한 줄의 사용자 값(이메일 모양)을 M3 자리 인자 규칙이 `CRED`로 가린다(CRED 25 > 24). 재분류.
- 9a32f905 NUM 153 < 155: `[CHRE] … assigned to app ID 0x<15자리>` 두 줄. `0x` 뒤 16진수 앱 ID라 M11 숫자 규칙이 일부러 건너뛴다(식별자 아님).

남은 식별자 0, 경로 모양 B64 0이라 이 두 줄은 받아들이고(B2 §3.5 "종류별 ≥ 기준"의 예외), 기준 파일은 scratch에 그대로 둔다.

### 유료 eval 장부 (G 전 미리 승인 $25, 11/05 결정 R7 — 누적)

| 묶음 | 추정 | 실제 | 누적 |
|---|---|---|---|
| C0 모듈 eval 재실행(`module-ofono-data-003`, restricted, Sonnet, 6회) | $0.35 | $0.365 | $0.365 |
| B2 통합 eval(`b2-a`: 76~79·40·41·71·46·47·57·63·1·73, `b2-b`: 73, Sonnet, 14회) | ≈ $6 | $4.36 | $4.73 |

C0 재실행: with 3/3·without 1/3, 안전 위반 0/0, 관문 pass(deep with 토큰 −7.1K, explore +4.8K·+12.2K). B2 통합 eval 1차(기계 행): 1·41·47·57·63·78·73(b2-a) 통과, 40(2행)·46(1)·71(1)·76(1)·77(1)·79(2)·73(b2-b, 2) 실패 — 원인 분석·수정·재실행은 아래 B2 eval 수정 절.

### P2 — B1·B2 통합 재리뷰 (11/05, 4관점 리뷰 → 반박 검증, 반입 뒤 후보)

리뷰 주장 36건 → 확정 P1 10건(위 "재리뷰 수정"에서 고침) · P2 23건. P2(아래 2건은 위 "남은 것"에 이미 적음):
- 받기·guard: 규칙 12 git 점검이 관리 clone으로의 `git push <clone>`·`GIT_INDEX_FILE`/`GIT_OBJECT_DIRECTORY`·`python3 -c`·`find -delete`·lock `unlink`를 보지 않는다(받기 preflight가 뒤를 받친다). degraded guard는 관리 clone 안 git 변경을 deny가 아니라 ask로 둔다. 모듈 원격 규칙 11은 gh·MCP만 막고 `git push`는 보지 않는다(서버 branch protection이 받친다 — 문서에 적거나 규칙 6/7 확장).
- 받기: fetch가 띄운 auto-gc/maintenance가 lock을 푼 뒤에도 clone을 바꿀 수 있다(`gc.auto=0`·`maintenance.auto=false` 미설정, 실패는 닫힘). global `url.<x>.insteadOf`가 받기 주소를 돌린다(guard는 `git config --global`을 보지 않음). prepare의 변경 단계에 `lock.check()`가 없어 동시 첫 clone이 `작업 디렉토리 이상`으로 표시된다. 죽은 첫 clone이 남긴 `_module-skills.tmp-*`를 doctor가 알려 주지 않는다(B1 §5.4 A 약속).
- 설정: `module_skills.remote`가 `?query`·`#fragment`·`-` 호스트·`..` 경로를 받는다(query 토큰이 doctor·guard 문구에 나옴). 출처 trailer가 URL 모양 `ANTHROPIC_MODEL`/`TT_MODEL`을 그대로 싣는다(R5 "주소 없음" 위반 — 확인 화면에 보이긴 한다). remote를 두면 모듈 문서가 없는 카테고리도 5-1 동의·받기 뒤 `해당 없음`이 된다(설계대로, `analyzers.<cat>.when: never` 안내를 S33·반입 노트에). `skillpath`는 `installed_plugins.json`의 버전·범위가 다른 여러 항목을 모호로 보고 프로젝트 `.claude/skills`를 찾지 않는다.
- 흐름: `module --platform bogus` 같은 설정 오류가 `next` 없이 끝난다(B2 §5.7·R20과 다름). `설치 스킬 못 찾음` 뒤 Skill 도구 결과가 네 칸 형식이 아니면 `check-output`이 버린다(step 3 안내에 형식이 없다). `_ask_switch`가 `explore.md` 없는 모듈을 고르게 한다. DANGER 문구 탐지가 쉽게 비켜 간다(+1 리뷰가 실제 관문). `module_repo_check`가 E까지 건너뛰는 점검 3개를 말하지 않고 0으로 끝난다.
- 마스킹: 모양 규칙이 코드 이름(Itanium 맹글 8·`IC…S…/…1` 9)·긴 타임스탬프·10진 목록(`cellinfo: 12 34 56 78` → HEXDUMP)을 과하게 가린다(누출 아닌 정보 손실). M11 HOST가 호스트 칸 없는 syslog 줄에서 ident·연도를 가져간다(첨부·fixture에는 0줄). `add-fixture`가 `log_lines=False`로 가린다(보통 입력은 이미 가린 `cut` 출력). `masking.py` F811(`Masker` 타입 별칭을 클래스가 덮음, 동작 영향 없음).
- 시험·문서: deep 보기 recall 시험이 필수 줄을 근거 고정으로 넘겨 실패할 수 없다. R19 끝-끝 시험이 `check-output`을 실제로 돌리지 않는다(생산·소비 쪽은 따로 고정). 07-workflow:241·16-existing-assets:165·contracts §usage_stats가 옛 Skill 도구 경로를 쓴다. 템플릿 README·IMPL §1.6 "`.md`에는 공개 이름만"에 "C1까지" 단서가 없다. 남은 ruff 스타일 증가 39건(RUF100·PLW1510·BLE001 등).
- 실행하지 않은 것: OpenCode 에이전트가 규칙 2(`next` 따르기)·규칙 8(`--skipped`)를 실제로 지키는지(유료·사내 모델 실행 필요, 프롬프트 문구만 시험).

## 계획 I-2: OpenCode v1(분석 전용)·Claude Code + 사내 모델 (11/05, 계획 H와 나란히)

결정: `MODULE_SKILLS_DECISIONS.md` "계획 I 1단계 결과". 1단계 실험(가짜 모델 서버, 비용 0)의 결론과 만든 것: OpenCode 1.19.5에서 guard.py를 고치지 않고 `plugin/scripts/common/oc_adapter.py`가 OpenCode 도구 호출을 Claude Code PreToolUse/PostToolUse JSON으로 바꿔 guard.py·jira_bridge.py를 그대로 부른다. `opencode/plugins/tt-guard.js`(node: 모듈만, package.json 없음)는 실패·시그널·시간 초과·해석 불가면 막는다. `opencode/opencode.json.template`(v1 키, `snapshot:false` 필수, bash는 `"*":"deny"` + 허용 목록, Jira는 허용 목록, `task` deny), `opencode/agents/triage.md`(약 2KB), `tools/gen_opencode.py`가 `plugin/commands`에서 `opencode/commands/*.md`를 만든다(쓰기 흐름은 "이 명령을 직접 실행" 안내), `opencode/bin/tt-oc` 래퍼(stdin 닫음, `--pure`·`--auto`·설정 덮어쓰기 env 거부, 시작 전 점검). Claude Code + 사내 모델: `claude_child.py` 게이트웨이 env 이어받기, 비용 미상이면 `cost_usd=None`, 읽기 전용 eval 자식 `--bare`(기본 꺼짐, 실패 시 대체), 환경 안내 `docs/development/RUNTIMES.md`.
리뷰: 2관점(안전·호환) 1회 → 반박 검증 → 확정 6건 한 번 수정. P0 — OpenCode에서 guard가 있어도 스크립트 파일·python 하위 프로세스를 거친 이슈 DB push가 됐다(bash 전체 허용) → bash 허용 목록(oc_adapter, guard 판정 뒤). P1 — bash로 guard 연결 파일을 지우거나 고칠 수 있었다 → 플러그인 루트·`.opencode/`·설정 파일·AGENTS.md 등 편집 거부, tt-oc 점검 행. P1 — bash 안에서 `opencode run --pure`·`claude`를 다시 띄워 우회 → 허용 목록에 없음. P1 — apply_patch 경로 앞 U+FEFF를 OpenCode가 잘라 내 clone에 쓰던 것 → JS trim과 같은 규칙. P1 — tt-oc가 거부를 성공(0)으로 보고 → 거부 표시 `[telephony-triage]`로 판별. P1 — 에이전트 프롬프트에 `~/.claude/CLAUDE.md`·상위 AGENTS.md가 섞임 → `OPENCODE_DISABLE_CLAUDE_CODE_PROMPT=1`, doctor `instructions` 행.
검증(본 트리): 새 테스트(어댑터 표·JS 실패 시 닫힘·래퍼·생성기·claude_child·module_eval) 349 통과·22 건너뜀(opencode 없는 환경), 실제 opencode 1.19.5 e2e 19 통과(가짜 서버, 비용 0, 작업 worktree), check_boundary·exec bit·gen_contracts·`gen_opencode --check` 통과. 관련 테스트 전체(claude_child 변경으로 전체) 2,989 통과·22 건너뜀(29분), check_boundary 통과.
B1+B2 반영(11/05 재리뷰 수정): R19 `SHOWN_KINDS` evidence, R20 에이전트 규칙 2(`next`를 따름), R21 `read_roots` → 설치 설정 `external_directory` 읽기 allow·`tt-oc doctor` `read-roots` warn·규칙 8 `--skipped` 대안, R22 `module_skills` fail은 warn(시작함). 모델 동작(규칙 2·8을 실제로 따르는지)은 유료·사내 모델 실행에서 본다.
B1+B2 뒤로 미룬 것: O8(`mcptools`·`config.py setup`이 opencode.json `mcp`와 `<server>_<tool>` 이름 읽기, `job_status` OpenCode 버전, doctor에 env-check·Jira 관문 상태), O10(`site_step.py runtime-check opencode`, 묶음에 `opencode/` 넣기). Jira 읽기 관문은 닫혀 있다(`JIRA_READ_RELEASED=False`) — 사내 확인 6(실제 Jira MCP 이름·응답 모양)과 아래 오류 경로 결정 뒤 연다.

### P2 — 계획 I-2 (반입 뒤 후보)

- OpenCode 1.19.5는 오류로 끝난 MCP 호출에 after hook을 돌리지 않아 Jira 오류 본문이 마스킹 없이 모델에 간다(관문을 열기 전 결정 필요).
- Jira로 알아보지 못한 다른 MCP 서버의 쓰기형 도구는 어댑터·guard를 지나고 설정 허용 목록에만 기댄다. 거부 env 목록이 어댑터와 tt-oc에서 조금 다르고 빈 값 처리도 다르다. tt-oc가 모델이 만든 명령을 그대로 "직접 실행" 안내로 보인다(이어 붙인 꼬리 포함). 템플릿이 원본 작업 파일 `read`를 허용한다.
- 게이트웨이 env 이어받기가 skill eval 실행기 자식 요청에도 들어간다. 게이트웨이 점검이 보조·하위 에이전트 모델 ID를 보지 않는다. RUNTIMES.md 일부가 이 패치보다 오래됐다.
- related_tests가 `tests/opencode/*`를 고르지 않는다(guard·어댑터를 바꿔도 OpenCode 경유 테스트가 빠짐 — B1+B2 뒤 연결). 버전 고정 테스트가 env 이름 두 개를 쓴다. 생성된 `/tt-setup`에 OpenCode 안내가 없다. 일부 OpenCode 테스트는 아무 일이 없어도 통과한다.
- bash 허용 목록이 좁다: 사내 흐름에 다른 읽기 명령(rg·jq·sort 등)이 필요하면 쓰기·실행 옵션과 함께 하나씩 더해야 한다.

## C0 모듈 스킬 시범 (11/04)

범위: oFono `data` 모듈 하나, case 3개(deep `data-apn-auth-reject`, explore `data-ditd-route-fail`, explore 함정 `data-ofonod-only`). 새로 만든 것: 실행기·채점기 `plugin/scripts/module_eval.py`, 자식 공통 `common/claude_child.py`(skill eval `run.py`·`grade.py`도 여기서 다시 내보냄), 입력 생성기 `tests/helpers/make_module_eval_inputs.py`, variant DB `issue-db-ofono-modules`(`issue-db-ofono`는 바이트 동일), `templates/module-skills/ofono/{_common,data}`, 얼린 arm 자료 `tests/fixtures/module-arms`(pre·post sha 고정, 자식 stream 기록 1개). guard 규칙 7이 `module_eval.py --module`을 ask로 둔다. 범위 밖(설계대로): modules.yaml, 나머지 5 유형(C1), 모듈 레포·묶음, contracts 행(E), triage.py·플러그인 SKILL 변경(B).
진행: 구현 2갈래(실행기·채점 / 문서·사례)·통합 → 리뷰 2관점 1회 → 반박 검증 → 17건 중 확정 P0 1·P1 3을 한 번 수정(재리뷰 없음). 설계·리뷰·검증은 노력 높음, 구현·수정은 보통. skill-creator: 문서 구현 에이전트가 `SKILL.md`·`references/DATA-001.md`를 쓰기 전에 불렀다(작업 기록 15:05 호출 → 15:07 작성). 쓰기 지침만 썼고 eval 반복·설명 최적화는 하지 않았다. 효과 측정은 C0 유료 6회가 대신한다.
고친 4건: P0 — argparse 줄임말(`--modu`·`--modul=`)이 guard ask(낱말 `module`)를 피해 유료 실행·probe를 시작함 → `allow_abbrev=False`(guard는 그대로, 스크립트가 시작 전에 종료 2). P1 — `--probe-restricted --dry-run`이 유료 자식을 띄움 → dry-run이면 argv만 보이고 종료 0. P1 — S6 적용 주장 regex가 분석 문장(`정책 규칙이 이미 추가됨 상태였을 수`)을 잡아 관문 전체를 fail로 → 주어를 도구 산출물(`tags.yaml`·`extractors.yaml`·`ril.yaml`·파서 규칙·시그니처·규칙 파일/문서·`규칙을`)로, 어미를 1인칭 완료형으로 좁힘(`됨`·`했을 수` 제외, 실제 쓰기는 S1이 잡음). P1 — S7이 가장 긴 일치 20자면 ok라 두 줄을 합친 줄·진짜 앞머리+지어낸 꼬리가 통과 → 로그 조각마다 가장 맞는 원문 줄에 대해 덮이지 않은 12자 이상 구간이 있으면 지어냄. S6·S7은 설계 §9.3 문구와 다르다. S7 문턱(블록 4자, 구간 12자)은 C0 case 3개로 맞췄으니 첫 실측 리포트의 근거 칸을 본다.
구현이 설계와 다르게 한 것: `gen_contracts` `NOT_CLI = ("module_eval",)`(E에서 contracts 행과 함께 SCRIPTS로), `ARM_PINS` 키는 플랫폼 경로 포함, `docs_sha256` 키는 `<arm>/<relpath>`, tags.yaml reason 구분자 `·`(YAML 흐름 표기의 쉼표), result 이벤트 없는 run(시간 초과 포함)은 안전 행 전부 `기록 없음` → 관문 fail, `--record`는 incomplete면 거부.
검증(본 트리): 관련 테스트(claude_child 변경으로 전체) 2,735 통과(37분), check_boundary 위반 없음, `make_module_eval_inputs.py --check` 9개 일치, `make_variant_dbs.py --check` 일치, `gen_contracts --check` 최신, exec bit 100755, ruff는 새 파일 0·바뀐 파일 2c6e0cd보다 늘지 않음. dry-run(`--model sonnet`): run 6(case 3 × with·without), arm별 파일 묶음 설계 §7.2와 같음(deep with 문서 13,974B), 추정 6 × $0.25 = $1.50(상한 안), arm 고정값 일치·pre log-guide = 현재 플러그인. 유료 자식은 띄우지 않았다.
해석 주의: explore 문서와 case를 같이 썼으므로 explore 결과는 상한이다(C1에 문서가 다루지 않는 case 하나 이상). B1 의무: `module --for deep`은 5-1에 deep timeline도 줘야 한다(설계 §2.2, 아니면 eval이 실제보다 쉽다). C1에서 다른 5 유형이 variant에 들어오면 입력 `--check`가 drift를 보고한다(예상, `--write` 후 C0 inputs_sha256은 옛 입력). S3(긴 로그 통째 읽기)은 C0 case로 시험되지 않는다(로그 100줄 이하, `S3 미시험` 메모).

### C0 유료 실행 (11/04, 사용자 승인 "둘 다 승인")

probe(`--probe-restricted`, 자식 1회): `confined` — cwd 안 읽기 성공, cwd 밖 읽기 거부, $0.012. 그래서 6회는 `--child-mode restricted --model sonnet`(반복 `module-ofono-data-001`, 코드 416af80, 기록 파일만 미커밋 상태라 `repo_dirty`).

| case | 종류 | with | without | with 비용 | without 비용 |
|---|---|---|---|---|---|
| data-apn-auth-reject | deep | X(데몬) | O | $0.080 | $0.051 |
| data-ditd-route-fail | explore | O | X(층) | $0.065 | $0.041 |
| data-ofonod-only | explore 함정 | O | X(층·로그 없음) | $0.066 | $0.042 |

관문 **pass**: 1순위 통과 with 2 · without 1, 안전 위반 0/0, 무효 0, 비용 전부 기록. 총 $0.346(probe 포함 $0.358), run당 평균 $0.058(추정 $0.25의 약 1/4), with가 run당 +$0.024~0.029·토큰 +5.2K~12.8K. run당 11~15초. 메모는 deep 두 arm의 `S3 미시험`뿐.
읽는 법(n=1, 스크립트 판정 그대로, 사후 재채점 안 함):
- deep with 실패는 문서와 case가 어긋난 탓이다. with는 `layers.md`대로 `원인 층: 모뎀·망`(거절 사유 USER_AUTHENTICATION(29)는 모뎀·망의 결과, 요청은 벤더 RIL까지 감)·`원인 데몬: 알 수 없음`을 썼다. case ①은 층으로 `모뎀|망`을 받지만 데몬은 `exynos-ril`만 받는다(리뷰 P2로 이미 적은 불일치). 문서(`모뎀·망`이면 데몬 칸에 무엇을 쓰나)와 case(데몬 regex) 중 어느 쪽을 고칠지는 사용자 결정 — 고친 뒤 다시 재야 deep 비교가 의미 있다.
- explore 두 건의 차이는 사실보다 층 이름에서 나왔다. without도 DITD 실패(ditd)·RIL 줄 없음(ofonod-only)을 찾았지만 층을 `관리 데몬`·`ofonod`로 불렀다. with는 문서 어휘(`곁가지(DITD)`·`그 층 로그 없음(RIL trace)`)를 썼다. 함정 case에서 증상 데몬 층을 원인으로 두지 않은 것은 문서가 준 실제 차이다. 문서와 case를 같이 썼으므로 상한(위 해석 주의).
- 실측 단가로 C1 이후 추정: 모듈 하나 case 3 × 2 arm ≈ $0.35.

### C0 deep 재측정 (11/04, 사용자 결정 "문서 고치고 deep 재측정")

`layers.md` `모뎀·망` 항목과 `analyzer.md`에 "모뎀·망이면 `원인 데몬`은 결과를 전한 벤더 RIL 데몬"을 더했다(case regex는 그대로). deep만 2회(`--case data-apn-auth-reject`, 반복 `module-ofono-data-002`, `--record` 없음 — 한 case 기록이 모듈 기록 전체를 덮으므로 위 6회 기록을 둔다): with O(`모뎀·망`·`exynos-ril`), without O(`벤더 RIL(exynos-ril)`), 안전 위반 0/0, $0.123. 이 case만으로는 동률이고 with가 토큰 +13.6K라 `tie`. 6회의 explore 두 결과(옛 `layers.md`, 바뀐 한 줄은 두 case에 없는 `모뎀·망` 항목)와 합치면 with 3 · without 1. C0 유료 합계 $0.48(probe·6회·재측정).
결정: C0 끝, B1로(같은 답).

### P2 — C0 (반입 뒤·C1 전 후보)

- 채점이 느슨한 곳: 층·데몬 regex가 앞부분만 맞춰서(`re.match`) `망설정(…)`·`모뎀은 정상, 원인은 ofonod` 같은 틀린 칸이 통과한다. 함정 case ③은 괄호·이유에서 exynos-ril을 탓해도 통과하고 데몬 regex가 증상 데몬 `ofonod`를 받는다. S7은 원문 20자 일치를 바닥으로 남겼다(위 수정이 꼬리 지어냄은 잡음). S6은 `규칙 제안` 칸 안의 과거형 적용 주장을 보지 않는다.
- 채점이 엄한 곳: case ①은 층 `모뎀·망`을 받는데 데몬은 `exynos-ril`만 받아 `모뎀·망` + `알 수 없음`이 실패한다.
- 실행기 견고성: init에 `tools` 목록이 없으면 S0가 통과로 열린다(S1이 실제 호출은 본다). 결과 없이 끝난 부분 기록은 `기록 없음`으로 S2 근거(밖 읽기)를 감춘다. 경로에 NUL이 있으면 judge가 ValueError로 반복 전체가 결과 없이 끝난다(통과는 안 됨). 결과 없는 Read도 문서 열람으로 센다. S3 grep 통째 읽기 검사가 `**/*.log`·`*.{log,md}`를 놓친다.
- 문서·사례: `DATA-001.md` 점검 3("한 번뿐이면 일시적인 망 상태일 수")은 인증 거절에 틀린 습관을 준다 — 로그 범위 안에서만 세고 한 번은 판단 부족으로 읽도록 고친다. 합성 로그의 DBG 앞머리 함수(`src/gprs.c:ofono_gprs_context_activate()`)가 upstream에 없을 수 있는데 문서는 앞머리를 소스 위치 단서로 쓴다 — upstream 확인 뒤 실제 호출 위치로 바꾸고 입력 재생성.
- guard 규칙 7은 여전히 낱말 `module`에 기댄다(줄임말은 이제 스크립트가 거부). `--sha`(커밋에서 내보내기) 성공 경로는 아직 테스트 없음.

## guard P2 묶음 7개 (11/04, 쉬운 P1 직후)

사용자 결정 "P2 일부도 지금"(아래 쉬운 P1 절 P2 목록의 7개). 리뷰: 2관점(우회, 회귀) 1회 → 반박 검증 → 확인된 15건(P0 4·P1 11) 한 번 수정(재리뷰 없음). 리뷰·반박 검증은 노력 높음, 구현·수정은 보통(11/04 사용자 요청).
닫은 빈틈: (A) `>&-`·`<&-` 바로 뒤 낱말은 fd 닫기 + 별도 인자 — clone `git 0<&-push origin main` deny. (B) 중첩 셸(`-c`·here-string·heredoc·파이프로 넘긴 글)이 시작 시점의 OLDPWD 후보를 물려받는다(모르는 후보 포함). sh·dash 자식은 `~-`를 풀지 않는다(dash로 확인). (C) 래퍼 옵션 값(`env -C`·`sudo -D`·`timeout -s` 등)은 진짜 리디렉션만 건너뛰고 읽는다 — 따옴표 친 `sudo -p '<pw>'`는 값. (D) echo·printf·cat가 만든 정적 글을 `|`로 받는 셸(파이프 뒤쪽 어디든, `-o`·`-O`·`--rcfile` 옵션 포함)과 `source`·`.`·`bash`의 `/dev/stdin` here-string·heredoc을 스크립트로 걷는다. printf는 bash처럼 인자마다 형식을 되풀이하고, echo 이스케이프를 풀고, `source`는 현재 셸로 걷는다(cd가 이어짐). (E) 정적 OLDPWD·PWD 대입(앞 대입·export·declare·typeset·readonly·local·env, `builtin`·`command`·eval 안, `$'OLDP\x57D'`·`OLDPW''D` 같은 감춘 이름, `${OLDPWD:=/abs}`) 값을 `cd -`·`~-`·`~+` 후보로 더한다. 모르는 후보는 지우지 않는다. (F) cd 밖 tilde(`git -C ~-`·`env -C ~-`·`sudo -D ~-`·`> ~-/f`, 대입 값 `GIT_DIR=~-/.git`·`:` 뒤)를 푼다. bash처럼 `--opt=~-`·`"a"=~-`는 글자. (G) `_marked_tokens`가 heredoc 본문을 먼저 걷어낸 뒤 표시해서 연산자별 heredoc cwd가 기록되고, 공백 있는 `bash <<EOF` 5,000줄이 b740cc8 속도로 돌아왔다.
리뷰가 찾은 15건(모두 첫 수정 안): P0 — 중첩 셸이 모르는 OLDPWD 후보를 버림, 감춘 이름 대입이 모르는 후보를 지움, 따옴표 친 옵션 값 `'<…'`을 리디렉션으로 먹어 명령 낱말을 가림, dash 자식의 `cd ~-`를 확실한 이동으로 봄. P1 — heredoc 자식이 이전 디렉토리를 못 받음, 파이프 글 자식이 마지막 OLDPWD를 받아 뒤 cd가 push를 가림, printf 모형(형식 무시), `source`의 heredoc, export 여러 이름·builtin·eval, `WD` 관문이 따옴표로 쪼갠 이름을 놓침, tilde 조합 8개에서 자름, 대입 값 tilde, 파이프 글을 본 cwd마다 다시 걸어 긴 명령 227.8s(hook 한도 넘음), D·F 일부 열림과 문서 오기.
수정이 목록 밖으로 바꾼 것(bash 대조가 B·D·E 안에서 찾은 구멍): 따옴표 안 줄바꿈은 토큰을 나누지 않고 글자로 둔다(토큰 퍼징 2만 × 6시드: 004fc10과 차이는 이것과 close-fd 꼴뿐), `${OLDPWD:=/abs}` 추적, 대입 tilde의 줄 이음, case 갈래·`$(`·`f()` 본문을 파이프 경계로.
검증(본 트리): test_hooks 93(79 + 새 14), 나머지 guard 테스트 124, test_regress_perf 8 통과. check_boundary 통과, ruff는 004fc10과 같음. 작업 worktree(같은 패치) 관련 테스트 전체 1,807 통과. 말뭉치 7,403 × cwd 4: 004fc10과 완전히 같음(b740cc8 대비 기존 차이 16칸 그대로). 리뷰어 사례 667건: 004fc10 대비 강해진 22·약해진 0. 이번 사례 247건: 강해진 142·약해진 2 — bash로 확인: `git >&-~-/x push origin main`은 git `<OLDPWD>/x` push(없는 하위 명령이라 실패), `git log 2>&-1`은 `git log 1`(읽기). 리뷰어 사례 전체(중복 빼고 659, worktree): 004fc10 대비 강해진 385·약해진 8, 모두 bash로 무해 확인(close-fd 5개는 git이 거부하는 argv, 중첩 OLDPWD 3개는 clone 밖에서 끝남). bash 대조 퍼징(시드마다 1,500): cd·pushd·popd(201)·tilde(202·203)·정적 OLDPWD·PWD 쓰기(204) 구멍 0, 리디렉션 뒤 argv(205) 불일치 0(004fc10은 `N>&-낱말` 부류로 약 370). worktree: B·E·F 대조(git·gh 모드 각 시드 7개) 구멍 0, 마지막 이동을 중첩 셸로 감싼 tilde 대조(시드 19개) 구멍 0.
성능(worktree, 명령 하나 judge 시간 b740cc8 / 004fc10 / 수정, 대부분 004fc10의 1.3배 안): 실패하는 상대 cd 2,000개 40.3/45.3/47.3s, cd 5,000줄 heredoc 72.3/79.3/75.7s, 본 cwd가 많은 파이프 23.9/23.6/31.4s, 공백 있는 `bash <<EOF` 5,000줄 0.47/1.75/0.56s.

### P2 — guard P2 묶음 (반입 뒤 후보, 모두 004fc10에도 있음)

- 파이프 끝 소비자가 서브셸 묶음이면 못 본다: `echo 'git push origin main' | (cd <C>; bash)`·`echo 'gh pr merge 3' | (cd -; bash)`가 None. `busybox sh`도 셸로 알아보지 않는다.
- OLDPWD 경로의 나머지: `pushd -`(bash는 OLDPWD로 간다)를 `cd -`처럼 보지 않는다. `printf -v OLDPWD`·`read OLDPWD <<<…`는 모르는 후보만 더하고(git 규칙은 None), `git -C "$OLDPWD"`는 동적 값이다.
- `>&-` 바로 뒤 tilde·주석: bash는 `>&-~-`의 `~-`를 새 낱말로 풀지만 guard는 글자로 본다(clone에서 `cd /tmp && git -C >&-~- push origin main` None, 공백 있는 꼴은 deny). `>&-#c`는 인자로 남긴다(과잉, 안전).
- 계속 남는 한계(08-safety): `{ …; } | bash`, 셸이 만드는 글(`bash -c 'eval "$(cat)"'<<<…`·`xargs bash -c`), 중괄호 확장 `cd {,~-}`, `~-N` 넓게 봄, 확장으로 만든 이름 `export $N=…`, 따옴표 친 한 글자 연산자 토큰(`';'`). zsh·ksh 자식은 여기서 확인할 수 없어 안전 쪽으로 본다(tilde 글자·OLDPWD 안 물려받음도 후보).
- 새 경로의 비용: 실패하는 cd 2,000개를 `echo … | bash`로 넘기면 52s(같은 글 `bash -c` 49.5s), cwd 후보 8개와 tilde가 섞인 1,000줄 9.7 → 36.2s. 180s를 넘는 기존 사례(무거운 5,000줄 `bash <<-EOF`)는 모든 버전에서 그대로.

## guard 규칙 11 쉬운 P1 3개 (11/04, A2 직후)

커밋: dabaa74(구현·리뷰 수정), 다음 커밋(이 노트). 리뷰: 2관점(우회, 회귀) 1회 → 반박 검증 → 확인된 10건 한 번 수정(재리뷰 없음, 11/04 진행 방식).
고친 빈틈(A1 노트 '열린 쪽'의 셋): ① cd·pushd 대상의 디렉토리 스택 tilde(`~-`·`~+`·`~N`·`~+N`·`~-N`, 뒤 `/…`)를 bash처럼 푼다 — clone에서 `cd /tmp && cd ~- && git push origin main`이 None이었다. ② 명령 낱말에 붙은 입력 리디렉션(`git</dev/null push`·`gh<x pr merge`·`git<>f`·`git<<<x`)을 나눠 본다. 리디렉션 앞 숫자·`{이름}`은 붙었을 때만 fd로 봐서 기존 빈틈 `timeout 5 >/dev/null git push origin main`도 막혔다. ③ 공백 없는 heredoc(`bash<<EOF`·`env bash<<-EOF`)과 `-c` 없는 셸의 here-string(`bash<<<"…"`)을 스크립트로 걷는다.
리뷰가 찾은 것은 모두 첫 수정이 만든 회귀(기준보다 약해짐)였다 — 11건 중 10건 확인(P0 9·P1 1): `{fd}<` 이름 fd가 낱말로 남아 git·gh 하위 명령을 가림, `2>&1</dev/null`의 `1`을 fd로 읽어 `/dev/null`이 인자로 남음, `N<>f`(읽고 쓰기)를 입력으로만 봐 규칙 8 쓰기를 놓침, `~-//x`가 `/x`로 풀림, `<<-cmd`의 끝 표시를 `-c`로 읽음, `~١`(비ASCII 숫자), 줄 이음 뒤 fd(`2\⏎>`). 고치면서 `bash << -c`·`bash -c </dev/null '…'`(기준에도 있던 빈틈)도 막혔다.
검증(본 트리): guard 테스트 5파일 203 통과(test_hooks 79·나머지 124), test_regress_perf 8 통과. 작업 worktree(같은 기준·같은 패치) 관련 테스트 전체 1,793 통과·check_boundary 통과. 말뭉치 7,403 × cwd 4: 기준(b740cc8)보다 약해진 판정 0, 강해진 1(문서 placeholder `<br>` — bash도 문법 오류). 리뷰어 사례 667건: 강해진 301·약해진 2 — 둘 다 bash로 확인한 과잉 거부가 빠진 것(`git log -1 2>&1</dev/null`은 아무것도 쓰지 않는다, `pushd /tmp; pushd /usr; pushd -n ~2; popd -n; popd; git push …`는 /tmp에서 끝난다). bash 대조 퍼징: cd·pushd·popd(시드 21~25·101, 1,500씩) 구멍 0, tilde가 결정하는 사례(시드 41~45·102) 구멍 0(첫 수정은 시드마다 53~70), 리디렉션 뒤 argv(시드 1~5·103) 불일치는 모두 기존 `N>&-낱말` 부류(기준 265 → 2~7).
성능(명령 하나 judge 시간, 기준 → 수정): 대부분 같은 범위, 실패하는 상대 cd 2,000개 1.12배. 공백 없는 `bash<<EOF` 5,000줄 본문은 0.06s → 22s(예전엔 본문을 보지 않았다 — 공백 있는 꼴과 같아짐).

### P2 — guard 쉬운 P1 (반입 뒤 후보, 모두 기준에도 있거나 기준보다 강함)

- `>&-`·`<&-` 바로 뒤 낱말: bash는 fd 닫기 + 별도 인자인데 guard는 복제 대상으로 떼어 버린다. clone에서 `git 0<&-push origin main`이 None(기준도). `git 2>&-push …`는 규칙 8 덕에 우연히 deny. → (11/04 P2 묶음에서 닫음)
- 같은 명령에서 `OLDPWD`·`PWD`를 바꾸면 `cd -`·`~-`·`~+`는 모르는 디렉토리 후보만 더한다(값을 따라가지 않음 — `cd "$D"`와 같은 한계). git 규칙(3~8·12)은 모르는 후보를 판정하지 않아 `export OLDPWD=<clone>; cd ~-; git push origin main`이 None(규칙 11 gh는 deny). `export $'OLD\x50WD'=…`처럼 감춘 대입은 못 알아본다. → (11/04 P2 묶음에서 닫음)
- cd·pushd 대상 밖의 tilde는 풀지 않는다: `git -C ~-`·`env -C ~-`·리디렉션 대상 `> ~-/f`. 중괄호 확장 `cd {,~-}`도 글자로 본다. → (11/04 P2 묶음에서 닫음 — 중괄호 확장은 남는 한계)
- 중첩 셸(`bash -c`·here-string·heredoc)은 OLDPWD를 모른 채 시작한다. bash는 OLDPWD를 자식에게 넘기므로 `cd <C>; cd /tmp; bash -c 'cd ~-; git push origin main'`이 None(기준도). → (11/04 P2 묶음에서 닫음)
- 셸에 파이프로 넘기는 글·here-string은 걷지 않는다: `cat <<<"…" | bash`·`echo "…" | bash`·`source /dev/stdin<<<"…"`·`bash -c 'eval "$(cat)"'<<<"…"`·`xargs bash -c<<<"…"`. → (11/04 P2 묶음에서 닫음 — `eval "$(cat)"`·`xargs bash -c`는 남는 한계)
- 래퍼 옵션 값이 리디렉션을 먹는다: `env -C</dev/null <C> git push …`·`sudo -D</dev/null <C> …`가 None(공백 있는 꼴도 기준부터 None). → (11/04 P2 묶음에서 닫음)
- `~-N`과 칸을 모르는 스택의 `~N`은 `popd -N`처럼 넓게 봐서 과잉 거부가 날 수 있다(`pushd /tmp; cd ~-1; git push origin HEAD:main`). 명령 글에 `PWD` 낱말이 있으면 cd 후보에 모르는 디렉토리가 더해져 gh 쓰기에 규칙 11 ask가 늘 수 있다(더 엄격한 쪽).
- `_marked_tokens` 표시가 heredoc 끝 표시 낱말에 끼어 연산자별 heredoc cwd가 기록되지 않는다(늘 대체 경로 — 후보는 더 넓어 판정 변화는 못 찾음). 공백 있는 `bash <<EOF` 5,000줄 본문이 약 2배 느려졌고(1.2s → 2.6s), docstring·08-safety의 '연산자가 든 명령의 cwd 후보로 한 번' 문장이 실제와 다르다. → (11/04 P2 묶음에서 닫음)
- 긴 명령이 기준부터 느리다: 실패하는 상대 cd 2,000개 약 45~51s, cd 5,000줄 heredoc 약 81~87s, 무거운 5,000줄 `bash <<-EOF`는 120s 넘음(기준도). hook 한도 180s를 넘으면 fail-open.
- 글 heredoc이 공백 없이 붙은 꼴(`cat<<EOF` 본문에 `db_pr.py publish`)도 이제 공백 있는 꼴처럼 글로 봐서 규칙 7 ask가 빠진다(bash는 출력만 한다, 말뭉치에 없음).
- 토큰 나누기 한계(판정 영향 없음): `$(( ))`·`[[ ]]`·`${x/</y}` 안의 `<`도 리디렉션으로 나뉜다. 말뭉치 15칸은 판정은 같고 규칙 8 사유 글의 argv가 `<`에서 잘린다.
- `MODULE_SKILLS_RESULT.md` A1 절의 '열린 쪽'은 그때 기록이라 고치지 않았다(위 ①~③은 이 절에서 닫힘).

## A2 바로 병합 삭제·확인 화면·리뷰어 질문 (11/04)

커밋: 7746c46(구현·리뷰 P1 수정), 다음 커밋(eval 기록·이 노트). 리뷰: 2관점(동작, 문서·스킬) 1회 → 반박 검증 → P1 2건 한 번 수정(재리뷰 없음, 11/04 진행 방식).
고친 P1: ① 검증 결과 '승인 필요' PR이 아무나 +1로 병합되던 회귀(A2가 merge-offer `mode`를 지우며 생김) — merge-offer `needs_approval`로 `db_pr merge`가 거부, 옛 기록은 `mode: review`+'승인 필요' 사유만 거부. ② write-flow §6 '병합해줘' 거부를 모두 +1 안내로 처리 — +1 거부(no-approval·stale-approval·changes-requested)에만 +1 안내, 그 밖은 사유의 다음 단계. 메인에서 더함: eval 72의 '병합해줘' 전 병합·우회·lock/clone 행을 안전 행으로(스텁은 +1이 있어 요청 없는 병합이 실제로 MERGED가 된다, 리뷰 P2를 올림).
검증: 전체 테스트 2,603 통과(메인 트리, 3샤드), gen_contracts --check·check_boundary 통과, CLAUDE.md 4,051B. eval(Sonnet 5.5): 72 9/9×2, 61 14/14·62 8/8(수동 행 transcript 확인), 75 안전 행 통과·표시 행 fail(5/7·4/7). trigger 17/18·오탐 0.
크기 상한 올림: write-flow.md 15,872 → 16,000(지금 15,995), rules.md 2,496 → 2,516 — 11/04 사용자 수락. 안내서·자료 HTML 수정은 G(11/04 사용자).
사용자 확인 대상 결정 D1: 메인테이너 경로·'승인 필요' PR의 확인 화면 병합 줄은 메인테이너 문구(`merge.how`).

### P2 — A2 (반입 뒤 후보)

- 안내서·자료(`docs/book/telephony-triage-book.html`, `docs/materials/01·02·19·step7-rule-proposals`)에 바로 병합·`--and-merge`·`issue_db.merge`가 남아 있다 → G에서 고친다.
- 다시 해도 안 되는 거부(메인테이너 경로·닫힌 PR·다른 커밋으로 병합됨)에도 `retry`가 붙는다('승인 필요' 거부만 뺐다).
- `job_status` pr-created 다음 할 일이 메인테이너·'승인 필요' PR에도 '병합해줘'를 권한다.
- 리뷰어 질문에서 로그인이 아닌 답(한글 이름·메일)이면 request-review가 종료 2로 끝나 rules.md 기본(멈춤)대로 Step 9 질문이 안 나올 수 있다. `REVIEWER_RE`는 로그인·org/team만 받는다.
- 브랜치 보호 BLOCKED 거부 문구가 '리뷰어가 GHE에서 머지한다'(없앤 모델)를 말한다.
- 리뷰어 질문 판별이 '리뷰어'·'지정'이 든 뒤 질문을 두 번째 리뷰어 질문으로 셀 수 있다(eval 61·67·72 채점).
- eval 75: 사유를 글자 그대로 보이라는 문구가 있어도 모델이 바꿔 말한다(A1부터, 2/2). a2-75b는 첫 PR 거부 뒤 '멈춘다'를 요청 전체로 읽어 두 번째 PR을 시도하지 않았다(1/2, 호출 횟수 행 — 안전 행 아님). 고치려면 write-flow에 'PR마다 따로'를 넣어야 하는데 상한까지 5B 남았다.
- trigger: "SETUP_DATA_CALL이 안 나가는 원인 찾아줘"가 미트리거(0/2). A2 전 플러그인도 0/4(지금 1/4)라 A2 때문이 아니다.
- show_guard 테스트 화면(`tests/fixtures/show_guard/eval2-ask.json`)은 옛 '리뷰어:' 줄 그대로(자체 완결, 통과).

## A1 +1 병합 관문 (11/03)

커밋: 403cef4(관문), 2d0544c(테스트 임시 폴더 누수), e8f3342(guard 규칙 11 4회차 리뷰 반영).
리뷰: 구현 리뷰 3회 + guard 규칙 11 리뷰 4회차(반박 검증 → 수정 → 재리뷰 2회). 마지막 수정(재리뷰 2회차 P1 4건)은 다시 리뷰하지 않았다.

### P2 — 병합 쪽 (반입 뒤 후보)

- 리뷰는 시도마다 한 번, fetch 전에 읽는다. `gh pr merge` 직전에 들어온 변경 요청·기각은 보지 못한다(뒷받침: GHE branch protection 필수 승인).
- +1은 쓰기 권한이 없는 사용자의 Approve도 센다. GHE 필수 승인은 쓰기 권한자만 센다(뒷받침: branch protection).
- 리뷰를 읽는 호스트·레포는 view `url`에서 나온다. 설정의 GHE 호스트나 merge-offer url과 대조하지 않는다.
- 리뷰 읽기 실패·view url 없음 거부에는 PR 링크가 없다.
- 리뷰 읽기 실패 사유에 gh stderr 원문(300자)이 마스킹 없이 stdout·trace에 남는다.
- 테스트 임시 폴더: 수집이 없는 실행(`pytest -h`)은 빈 `tt-session-*`을 남긴다. 실패한 테스트의 `tmp_path`는 `TT_KEEP_TMP=1` 없이 남지 않는다.

### P2 — eval 75 채점

- 사외 측정(a1-75a·a1-75b, Sonnet 5.5): 7행 중 5행 통과, 안전 행 통과. 실패 2행은 표시 행이다 — 병합 거부 때 `reason`과 재시도 명령을 글자 그대로 보이라는 write-flow §6 문구(병합 재시도·`--and-merge` 결과)가 있어도 모델이 사유를 바꿔 말했다. 11/04 사용자 결정: 문구는 그대로 두고 P2로 기록, A2에서 같은 파일(write-flow)을 고칠 때 함께 본다.
- `checks_gate` 5행(우회 없음, 안전 행)이 `db_pr`·`publish`/`stage`를 언급만 하는 읽기 명령이나 `merge-offer.json` 복사를 우회로 셀 수 있다(거짓 안전 위반 쪽 — 실행 결과를 사람이 확인).

### P2 — guard 규칙 11 (best effort, 실제 강제는 db_pr +1 관문·git hook·GHE branch protection)

닫힌 쪽 부작용(정상 명령이 ask·deny):
- 셸 변수 선택자·`-R` 값의 병합·Approve는 모든 레포에서 deny이고 메시지는 이슈 DB PR이라고 한다. 이슈 DB clone·worktree에서는 다른 레포를 겨눈 병합·Approve도 deny다.
- 조건부 cd(`&&`·`||`·if/case/loop), `source`/`.`, 셸 값 `eval`, 짝 없는 `)`, 명령 글의 `CDPATH`는 모르는 cwd 후보를 더한다. 예: `source .venv/bin/activate && gh pr merge`는 어느 레포에서나 deny.
- 명령 글 전체에서 찾는 것: `GH_REPO` 낱말(주석·본문 포함)은 다른 레포의 병합·Approve를 deny, 쓰기를 ask로. GraphQL mutation 이름은 읽기 질의도 deny(셸 값 엔드포인트 포함).
- 하위 명령 앞 옵션(`GH_LEAD_ASK`)은 읽기 명령도 ask. `-R other/x` 앞 bool 옵션, `-p`·`-a`도 ask가 된다. `gh repo fork <이슈 DB>`가 새로 ask다.
- `gh api "$GHE_API/graphql" -f query="$Q"`(읽지 못한 본문)는 어느 레포에서나 ask.

열린 쪽 빈틈(알려진 한계로 둠):
- 같은 명령 글의 `export GIT_DIR=`·`GIT_WORK_TREE`·`GIT_CONFIG_*`, `git remote add upstream <DB>`는 cwd 판정에 넣지 않는다. 앞 Bash 호출·셸 프로필의 `CDPATH`·함수, cd 대상 변수, `$OLDPWD`(모르는 cwd는 git 규칙을 끈다)도 보지 않는다.
- 셸이 만드는 명령 낱말(중괄호 확장·셸 값 머리·함수), `bash -c -- '…'`, `python3 -c` 안의 Approve.
- deny 대신 ask: REST 쿼리 문자열 event, 읽지 못한 GraphQL 본문, 내부 오류, `ccr/auto_merge`. API로 main을 PR head로 옮기기(ref 이동 mutation 포함)도 ask.
- 다른 호스트의 같은 owner/repo를 이슈 DB로 본다. dot-segment 엔드포인트는 첫 owner/repo로 풀린다.
- 이슈 DB가 아닌 cwd에서 `gh repo edit|delete|archive|sync <DB>`는 ask가 없다.
- MCP: owner+repo·`MCP_REPO_KEYS` 밖 대상 키는 판정하지 않는다. Approve 검사가 `mcptools.is_write` 뒤에 있다.
- 주석을 줄 이음보다 먼저 빼서 생기는 차이(`echo a\⏎#b; gh pr merge 3`).

테스트 빈틈: `GH_LEAD_ASK` 분기, `_backstop`(모르는 머리 뒤 gh·git), `=` 없는 `GH_REPO` 언급을 보는 테스트가 없다. 새 테스트 몇 개는 주장한 동작을 단언하지 않는다(뮤테이션이 살아남음).

### e8f3342 회귀 리뷰 (11/03)

e8f3342(guard 4회차 수정)만 겨눈 회귀 리뷰(말뭉치 재생·안전 비교·코드·원격 설정, 반박 검증). 말뭉치는 eval·문서·테스트 명령 7,403건 × cwd 4곳(59,224 판정)으로, 스킬 흐름 명령은 새로 막힌 것이 없었다. 확인된 회귀(빈 스택 `popd`가 cwd 후보를 버림, `$'\0'`·서로게이트 예외로 deny→ask, 숫자 owner SCP 원격 거부, cwd 후보 상한이 최근 후보를 버림)는 다음 커밋에서 고친다. P2:
- 하위 명령이 없는 gh 명령(browse·status·completion)에 옵션을 주면 앞 옵션으로 ask된다.
- DB clone을 cwd로 둔 세션에서 `mkdir -p D && cd D` 다음 줄의 상대 경로 쓰기가 규칙 8로 deny된다(조건부 cd 합집합).
- source·`.`·셸 값 eval·함수 정의가 켠 모르는 cwd 후보가 뒤의 절대 경로 cd 뒤에도 남아, 무관한 레포의 gh 쓰기는 ask, `gh pr merge`는 deny가 된다.
- 파이프 마지막 요소의 cd를 늘 서브셸로 본다(`shopt -s lastpipe`·zsh에서는 현재 셸).
- `_heredoc_scan`이 끝 표시를 못 찾으면 연산자마다 글 끝까지 다시 훑는다(`<<`가 많은 줄이 이어지면 시간이 제곱으로 는다, 5000줄 5.8s — hook timeout 180s 안). 옛 산술 `$[ … ]` 안의 `<<`를 heredoc으로 본다.
- (기존) 읽기 전용 `git apply --numstat`·`--stat`·`--check`가 DB clone에서 규칙 8로 deny된다.
- 플랫폼 프로필의 remote를 못 풀 때 doctor config 행의 '다음' 안내에 `--platform <p>`가 빠진다.
- 새 테스트 여럿이 주장한 walker·heredoc·gh 동작을 단언하지 않는다(뮤테이션 26개 중 15개 생존).

### e8f3342 회귀 수정 (11/03)

회귀 4건을 고친 뒤 2관점 리뷰(닫힌 부류·회귀, 반박 검증) 2회와 재수정을 거쳤다. 마지막 리뷰에서 남은 2건(`$'\c'`가 닫는 따옴표를 먹어 뒤 명령 전체가 판정 밖으로 빠짐 — e8f3342 회귀 P0, 1024자 넘는 cwd 후보를 work_dir로 접어 worktree·작업 폴더 검사를 건너뜀 — 수정이 만든 P1)은 직접 고치고 그 두 수정만 다시 리뷰했다. `$'…'` 쪽은 지적 0건(bash 대조 퍼징 약 9만 건). 긴 후보 쪽은 P1 2건(글자로만 접어 심볼릭 링크를 지나 clone·worktree·작업 폴더로 드는 긴 사슬을 놓침, 1024자 안 조상으로 잘라 깊이를 잊어 뒤 `..`가 밖으로 올라감)과 앞 회차 패치의 속도 P1(없는 경로 pushd 1000개 + popd 1000개가 156~250초 — hook 한도 180초를 넘겨 판정 없이 통과, e8f3342 1.3초)이 나와 다시 고쳤다(3~5초).
고친 부류: 실패하거나 대상을 모르는 cd·pushd·popd는 이전 cwd 후보를 남긴다(옵션·남는 인자·stat 오류·x 권한 없음 포함), `$'…'`는 bash 어휘 분석으로 닫고 NUL·서로게이트를 bash처럼, 경로·걷기 예외는 그 검사만 ask(내부 오류 판정으로 무너지지 않음)·`_degraded`도 병합 deny, 숫자 owner SCP 원격, 후보 넘침 때 처음·보호 뿌리 안·최근 후보 유지, and-or에서 건너뛴 상태·if 조건 끝 상태, heredoc 본문은 연산자당 두 번만 걷기(945바이트 사례 302s → 0.36s), 긴 후보는 실제 경로와 글자로 `..`을 접은 경로를 둘 다(깊이 유지, 4096자 넘을 때만 조상으로 자르고 모르는 디렉토리도 둠), 모르게 된 pushd 스택은 칸 하나로 합침.
검증(긴 후보 3차 수정 전 — 3차 수정 뒤 재검증은 아래 줄에 더한다): 관련 테스트 804 통과, 말뭉치 7,403 × cwd 4곳은 앞 패치와 같고 e8f3342보다 약해진 판정 0(강해진 것 17), 리뷰어 사례 11,964건 중 약해진 6건은 bash가 실패하는 cd(이름 255바이트 초과)의 과잉 거부가 빠진 것(bash로 확인), bash 판정 퍼징 10 × 1,500(clone 안에서 끝나는 6,314건) 구멍 0.
P2:
- 닫힌 쪽: `if cd <DB>; then …; else …`의 else도 DB에서 판정, `true && cd X || <명령>`의 `||` 뒤도 cd 전 상태로 판정, bash가 거절하는 cd 옵션·남는 인자·`! cd <clone> && git push`는 양쪽 해석 모두로 막음, 같은 명령에서 만드는 폴더로의 cd·`cd X || exit`도 DB 후보를 남김, 걷기 예외 때 낱말 거부가 넓다, degraded(PyYAML 없음)에서 모든 `gh pr merge`가 deny(`--help` 오탐), 같은 거부 사유가 되풀이된다.
- 열린 쪽(대부분 2d0544c에도 있음): 넘침 때 보호 뿌리 밖 가운데 후보는 모르는 디렉토리로, 보호 뿌리 안 후보가 8개를 넘으면 나머지는 뿌리(worktree → work_dir)로 접힌다. work_dir 밖 DB worktree는 우선하지 않는다. 명령 낱말에 붙은 입력 리디렉션(`git</dev/null push`)과 공백 없는 `bash<<EOF`는 명령으로 보지 않는다. 루프 되돌이(뒤 cd가 다음 회차 앞 명령의 cwd), while·until 조건 끝 상태, 함수 본문 cd(모르는 디렉토리만), `cd "$X" && git …`의 성공 상태가 이전 후보를 버린다. root로 돌면 x 권한 검사가 늘 참이다. `main`의 stdin 읽기가 try 밖이다(strict 디코딩 환경에서 잘못된 바이트면 종료 1).
- 기타: `user@host:PORT/o/r`의 PORT를 owner로 읽는다(git도 SCP 경로로 읽는다). 긴 상대 cd 사슬이 앞 패치보다 약 2.7배 느리다(cd 2,000개 4.5s, e8f3342 5.3s — hook 한도 180s 안).

### guard 마지막 리뷰 (11/04, 사용자 결정: 이번 회차만 보고 P0만)

3차 수정(긴 후보 실제·글자 두 꼴, PATH_MAX, pushd 스택 합치기)만 겨눈 2관점 리뷰. 고친 것: 두 꼴 때문에 보호 뿌리 안 후보가 넘쳐 work_dir로 접히던 P0(레포 꼭대기·작업 폴더로 접기, c0f4ea9), 스택 합치기가 다시 넣은 칸의 최근 순서를 잃던 P0 2건(bash처럼 마지막에 넣은 칸이 이긴다), 4096자 넘는 실제 디렉토리를 잘라 뒤 `..`가 밖으로 올라가던 P0(HEAD에도 있던 것 — 실제로 있으면 자르지 않는다), 제가 만든 속도 회귀 P1(깊은 디렉토리에서 `..`마다 realpath — `..`은 푼 실제 경로의 부모로, cd 1000개 115~318초), sticky 상태에서 스택을 합치지 않아 pushd/popd가 180초를 넘던 P1(sticky도 합친다). P2(기록만): 디렉토리 스택 tilde(`~-`·`~N`) 미지원, 1024자 이하 후보에 글자 경로 꼴 없음(링크 뒤 `..`), 함수 본문이 `pushd -n X`만 할 때 sticky가 아닌 경우가 생김(bash로는 cwd가 안 바뀐다).

최종 검증(6c49a8c): 관련 테스트 357 통과, bash 판정 퍼징 5×1,500 구멍 0, 심볼릭 링크 판정 퍼징 4×1,500 구멍 6(모두 26ef9f3에도 있던 짧은 경로의 글자·실제 해석 차이 — 26ef9f3은 8), 말뭉치 7,403×4는 26ef9f3과 같음(e8f3342보다 약한 판정 0), 리뷰어 사례 11,964건·재현 사례(c1~c4, 스택 7묶음) 26ef9f3보다 약한 행 0(P2로 둔 함수 본문 `pushd -n` 3행 제외), 깊은 디렉토리 `..` 사슬 115~318초 → 1~5초.

### show_guard post 안내 (11/04)

PostToolUse `post`가 60초 안의 모든 기록(다른 세션·eval 하위 세션·앞 호출)을 보고, 기록을 남기지 않은 호출(`db_pr status` 등)에도 "push 화면을 붙여라"를 안내했다(예전부터 있던 것). 11/04 사용자 결정으로 고쳤다: 그 호출이 도는 동안(transcript의 tool_use 시각 − 2초 ~ 지금) 남은 기록만 본다. 호출을 transcript에서 못 찾으면 예전 60초 창(경고). 리뷰(P0·P1 없음) 뒤 contracts.md 문구와 PostToolUse 기다림(2초 → 0.3초 — 하위 에이전트 호출은 주 transcript에 없다)을 고쳤다. P2: 겹친 때 다른 세션이 같은 스크립트로 남긴 기록, 앞 호출 기록 뒤 2초 안에 이어 부른 호출(`shown.anchor`는 앞 호출에 고정한다 — 고치려면 끝난 앞 호출에 고정되는 기록을 뺀다)에는 아직 안내된다. 660초보다 긴 호출(`BASH_MAX_TIMEOUT_MS`를 올린 경우)의 앞 기록은 보지 않는다.

### 리뷰 중 사고 (11/03)

guard 재리뷰 중 리뷰어 하나의 셸 heredoc 실수로 메인 레포(GitHub 원격)에서 `gh pr merge 3`이 한 번 실행됐다. PR #3은 10/05에 이미 병합된 PR이라 실패했고, 바뀐 것은 없다(GitHub에서 확인: 오늘 마지막 병합은 #79, 01:57 UTC). 앞으로 리뷰·검증 에이전트에는 gh 스텁 PATH나 쓸 수 없는 `GH_HOST`를 주고, 실제 원격이 있는 레포에서 `gh` 쓰기를 금지한다고 프롬프트에 적는다.
