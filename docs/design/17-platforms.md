# 17. 플랫폼 분리 (Android 기본 / oFono / 이후 추가)

> 10/11 사용자 요청. oFono는 Android와 동작·로그·원인·해결책이 달라 **플랫폼마다 이슈 DB를 따로** 둔다. 플랫폼은 계속 더할 수 있어야 한다(이름을 하드코딩하지 않는다). 표·정의가 다르면 `contracts.md`가 맞다. 사내 고유 구성요소 이름은 쓰지 않는다(placeholder `daemon-a`·`daemon-b`, `14-site.md` S24~S29).

android만 쓰는 설치(site-defaults에 `platform.enabled`·`others`·`parser.by_platform`이 없고 사용자 config에 `platform`·`platforms`가 없음)는 경로·lock 위치·lock JSON·`config.py show/doctor`·guard 판정(규칙 10 제외)·pre-push·`analysis.json`·`report.md`·이벤트·`db_regress`·골든이 모두 이전과 바이트 단위로 같다. 이슈 DB에 `platform`이 없으면 android다. 예외: guard 규칙 10과 Jira 게시 원문 줄 검사는 **설치된 모든 플랫폼** 형식(`known()` 합집합, §5)을 원문으로 보므로 android 단독 설치도 journald·BSD syslog 모양 줄을 거부한다(더 엄격한 쪽).

## 1. 계약 (`plugin/scripts/platforms/`)

```
platforms/
  __init__.py   # 레지스트리: known·get·label·enabled·default_name·load·backend_name·select·원문 줄 판별. 플랫폼 이름을 모른다
  base.py       # 계약 타입: PlatformSpec·LogFormat·PairProtocol·CaptureSpec·SourceTree·PhoneIdRules·VendorRules·LogLine·FileStats·Component·MsgView·PlatformConfigError
  session.py    # 사용자 세션 선택(--platform)과 사용자 config 프로필을 잇는 유일한 곳(resolve·resolve_lenient·implicit·add_arg)
  sniff.py      # 로그 파일 형식으로 플랫폼 판별(§11). 플랫폼 이름을 모른다
  android/      # SPEC + logcat·ril·bugreport·backend
  ofono/        # SPEC 뼈대 + journal(형식 가정 placeholder)·msgformat·pairing(§9)·backend
common/logtime.py                       # 플랫폼 무관 시각 함수·시계 이상 기준·coverage
parser_backends/<p>_reference/          # 그 플랫폼 BACKEND 재수출 (android는 reference/)
```

- 플랫폼 하나 = `platforms/<name>/__init__.py`의 `SPEC: PlatformSpec`. frozen dataclass와 Callable 필드다(상수와 함수가 섞이고 site-defaults로 덮어쓴 복사본을 만들어야 해서 ABC를 쓰지 않는다).
- `PlatformSpec`: `name`, `label`(출력 라벨 "Android"/"oFono"), `log: LogFormat`, `phone: PhoneIdRules`(빈 규칙 허용), `protocols: tuple[PairProtocol, ...]`(0개 이상), `source_tree: SourceTree`, `primary_root`(주 소스 루트 키, android `aosp`), `default_root_keys`(DB `code_root_keys`가 없을 때), `capture: CaptureSpec | None`(bugreport류 묶음 입력), `default_backend`(android `reference`, ofono `ofono_reference`), `block_keys`(site-defaults에서 받는 상수 키). 뒤쪽 기본값 필드 `components`·`msg_formats`·`protocol_kinds`는 한 플랫폼 안의 여러 구성요소(데몬)용이다(§9, 기존 플랫폼은 비워 둔다).
- `LogFormat`: `read_file(path, file_index, tz, year) -> (list[LogLine], FileStats)`, `raw_line(줄)`(줄 맨 앞이 원문 로그 줄인가, guard 규칙 10), `find_raw(문장)`(문장 안에 원문 줄이 끼었나, Jira 게시 검사), `epoch_break(LogLine)`(재부팅 등 불연속).
- `PairProtocol`: `name`·`default_tags`·`annotate`·`pair`. 주석은 이벤트 `ril` 칸을 같이 쓰고 `name != "ril"`이면 `proto: <name>`을 단다. `pair`는 **자기 주석만** 다룬다(다른 프로토콜 주석은 짝·pid 분할에 쓰지 않는다). 태그 덮어쓰기는 ril이면 `<블록>.ril.tags`, 그 밖은 `<블록>.protocols.<name>.tags`. 코드 없이 설정으로 만드는 프로토콜은 §9-3.
- `CaptureSpec`: `looks_like`·`extract`·`error`·`default_rules`·`sniff_line`(guard 머리 판별), `block_key`·`configure`(site-defaults 블록 검증·덮어쓰기, 레지스트리는 규칙 모양을 모른다).
- 파서 백엔드(`parser_backends/base.py`): 클래스 속성 `platform`(기본 `"android"`, 기존 site 백엔드 호환), `log_format()`(기본 `SPEC.log`). 백엔드 이름 공간은 `16-existing-assets.md §16.3`.

### 1-1. 레지스트리 API

- 이름 `^[a-z][a-z0-9_]*$`, `base`·`_`로 시작하는 것 제외. `get(name)`은 `importlib.import_module("platforms.<name>")` → `SPEC` 타입과 `SPEC.name == name` 확인 → 프로세스 안 캐시. 오류는 `PlatformConfigError`(호출자 종료 코드 2). 플랫폼 모듈 안의 하위 의존성 누락은 그대로 올린다.
- `known()`: 설치된 플랫폼 패키지(메시지 "지원 플랫폼: android, ofono (…)").
- `enabled(defaults)`: site `platform.enabled`(목록·중복 없음·기본 이름 포함·모두 설치됨), 없으면 `[platform.name]`.
- `load(defaults, name=None, require_enabled=True)`: 기본 플랫폼은 `platform:` 블록, 그 밖은 `platform.others.<name>` 블록을 `SPEC.block_keys`로 검증해 `PlatformProfile`(`spec`·`protocol_tags`·`components`·`protocols` 포함, §9)을 준다. `platform.others`는 요청과 상관없이 모두 검증한다. `require_enabled=False`는 DB에 고정된 도구용(K6).
- `backend_name(defaults, name)`: 기본 플랫폼이면 `parser.backend`, 그 밖은 `parser.by_platform.<name>`, 없으면 `SPEC.default_backend`.
- `select(defaults, cli, user)`: K3 순서, `enabled` 관문. `triage.py run`은 그 뒤 로그 형식으로 다시 고를 수 있다(§11).
- `detect_rules(defaults)`: site `platform.detect.tracker_field` 검증(§11-5, 없으면 None). `load()`도 부른다.
- `known_raw_line_finders()`: 설치된 **모든** 플랫폼의 원문 줄 판별(guard 규칙 10·Jira 게시 검사, 설정과 무관, 플랫폼마다 따로 불러와 하나가 깨져도 나머지는 쓴다). `raw_line_finders(defaults)`: 켠 플랫폼만.

### 1-2. 계층 규칙 (테스트로 강제)

- `common/`은 `platforms`를 import하지 않는다. 핵심(매처·`db_*`·guard·`config.py` 등)은 레지스트리 경유로만 플랫폼을 쓴다(`platforms.android` 직접 import 없음).
- `platforms/<a>`는 `platforms/<b>`를 import하지 않는다(공용은 `platforms.base`와 레지스트리 밖 모듈: `common.logtime`·`common.events`, 백엔드 `backend.py`는 `parser_backends.base`도). 플랫폼 코드는 핵심 스크립트(`parse_logcat`·`triage`·`config`·`code_roots`·`db_*`)와 `parser_backends.site`를 import하지 않는다.
- `platforms/<p>/__init__.py`는 표준 라이브러리 + 같은 패키지 하위 모듈 + `platforms.base`·`common.logtime`·`common.events`만(guard가 규칙 10에서 불러오므로 가벼워야 한다. `backend.py`는 `__init__`이 불러오지 않는다). `__init__`이 불러오는 하위 모듈(ofono `journal`·`msgformat`·`pairing`)도 같은 제한이다. 검사는 `tests/test_platforms.py`.

## 2. 선택·경로·프로필 규칙

| 층 | 키 | 의미 |
|---|---|---|
| site-defaults | `platform.name`, `platform.enabled`, `platform.others.<p>`, `parser.by_platform.<p>`, `platform.detect` | 팀 기본, 켤 수 있는 플랫폼, 그 밖 플랫폼의 상수·백엔드 (`02-config.md`), 트래커 필드 → 플랫폼(§11-5) |
| site-defaults | `platforms.<p>.analyzers` | android 밖 플랫폼의 분석 스킬 팀 기본(§10-1). 최상위 `analyzers`는 android |
| 사용자 config | `platform` | 개인 기본 선택(`enabled` 안의 이름) |
| 사용자 config | `platforms.<p>.{issue_db, work_dir, log_dir, code_profiles, recent_code_roots}` | 경로 프로필(`PROFILE_KEYS`). 최상위 같은 키 = android 프로필 |
| 사용자 config | `platforms.<p>.analyzers` | 그 플랫폼 분석 스킬 개인 값(`PLATFORM_SCOPED_KEYS`, §10-1). 최상위 `analyzers` = android |
| CLI | `--platform <p>` | `triage.py`·`config.py`·`db_pr.py`·`db_verify.py`·`issue_post.py`·`code_roots.py`·`db_add.py`·`db_search.py`·`db_review.py`·`job_status.py`·`usage_stats.py`·`skill_patch.py`(그 밖 스크립트 — `mask_pii`·`parse_logcat` 등 — 은 받지 않는다) |
| env | `TT_PLATFORM` | triage → 하위 스크립트(사람이 쓰지 않는다) |

- 선택 순서: `--platform` > `TT_PLATFORM` > 사용자 config `platform` > site `platform.name` > `android`. `enabled` 관문은 **사용자 세션 흐름만** 적용한다. DB에 고정된 도구(`db_regress`·`db_lint`·`parse_logcat --rules`)는 DB 선언 플랫폼(설치돼 있으면 허용). `triage.py run`은 켠 플랫폼이 2개 이상이고 명시(`--answer platform=`·`--platform`·`TT_PLATFORM`)가 없으면 하나로 정해진 로그 형식이 사용자 config `platform`·site 기본보다 앞선다(§11, K18).
- 프로필: android가 아닌 플랫폼의 cfg는 공통 키에 `platforms.<p>`를 얹은 것이고 android 값을 **물려받지 않는다**(ofono 프로필이 실수로 android clone을 가리킬 수 없다). 기본 `work_dir` `<home>/work-<p>`, 보류 피드백 `<home>/pending-feedback-<p>`. 최상위 프로필 없는 config(따로 설치)도 된다.
- 경로 규칙(`userconfig.path_problems`): `work_dir`·`issue_db.path`는 비어 있지 않은 절대 경로(`~` 허용), `work_dir`은 clone 밖, 프로필끼리 `work_dir`·clone·원격 겹침 금지. `platforms.<p>`의 프로필·`analyzers` 밖 키(예: `source_tree`)는 거부(RF-4). `config.py show`·`set`·`doctor`는 이런 문제가 있어도 동작하고(set 경고, doctor `platform` 행 fail), 그 밖 스크립트는 종료 코드 2.
- `--db`가 없을 때의 대체 경로(사용자 config `issue_db.path`, `common/dbpath`의 ③)도 **선택 플랫폼** 프로필의 값이다(`db_add`·`db_search`·`db_review`·`config`·`code_roots`). 이 스크립트들도 이슈 DB 선언과 선택 플랫폼을 대조한다(`platform-mismatch`). 단 `db_add`의 `apply`·`drift`·`renumber`·`check-ids`는 `db_pr publish`·`db_verify`·stage 검사가 그 DB에 대고 부르는 **DB 고정** 하위 명령이라 DB 선언을 따르고, `--platform`·`TT_PLATFORM`이 있을 때만 대조한다(사용자 config 없이 도는 비기본 DB 검사가 막히지 않게). 사용자 흐름인 `similar`는 항상 대조한다.
- 쓰기: `config.py set --platform <p> <키>`·`code_roots remember`는 `profile_key(p, key)`(android면 그 키, 그 밖 `platforms.<p>.<키>`)에 쓴다. `config.py init --platform <p>`는 그 프로필만 더한다(트래커(`tracker.*`)·gh 설정은 공유). 이미 있으면 `--force`로 그 프로필에서 입력한 항목만 갱신한다(없는 키·Enter는 유지, 빈 값·`-`·팀 기본값과 같은 답은 지움 — android `--force`와 같은 규칙). android도 최상위 프로필이 없는 config(따로 설치)면 `--force` 없이 그 프로필만 더한다. `init`의 플랫폼은 `--platform` > `TT_PLATFORM` > site(사용자 config `platform`은 보지 않는다 — `init --force`가 다른 플랫폼 프로필을 덮지 않게)이고, 새 config에 경로 규칙 문제가 있으면 저장하지 않는다(종료 코드 2).
- 출력: `analysis.json`·lock 기록·`triage-state.json`의 `platform`은 android가 아닐 때만(켠 플랫폼 2개 이상이면 출력은 `--platform` 없이 고르는 플랫폼 또는 지정(`--platform`·`TT_PLATFORM`)과 다를 때도, §11-4). 라벨은 `SPEC.label`. 같은 작업 키를 다른 플랫폼으로 다시 실행하면 종료 코드 2.

## 3. 플랫폼별 lock

lock·`session.guard`는 각 플랫폼 `work_dir`에 있다(`Lock(work_dir, platform)`, 시그니처 불변). 그래서 원칙은 **"사용자·이슈 DB(플랫폼)별 한 번에 한 작업"**이고(`12-principles.md`) android 작업과 oFono 작업은 동시에 할 수 있다. 같은 플랫폼 안에서는 이전과 같다. 스냅샷·`snapshot.json`·JOB 디렉토리·분석 재사용 캐시도 그 `work_dir` 안이다.

## 4. 이슈 DB 분리와 `platform-mismatch`

- 선언: `issue-db.config.yaml` 최상위 `platform: <name>`(없으면 android, android 샘플에는 넣지 않는다). `db_lint`가 형식과 설치 여부(`known()`)를 본다.
- 버전 키: `platform_versions_supported`. 옛 이름 `android_versions_supported`는 읽지 않고 `db_lint` config 오류다(트래커 범용화 때 원칙 (d)로 정리, `18-trackers.md` T4).
- 세션 선택과 DB 선언이 다르면 **거부**(`platform-mismatch`, `contracts.md §공통 규칙`). 분석도 멈춘다(읽기 전용으로 계속하지 않는다). 원인·해결책이 다른 DB에 대고 매칭하는 것은 의미가 없기 때문이다.
- 옛 플러그인 + oFono DB: 옛 플러그인은 `platform`을 모르고 android로 보지만, oFono DB의 `parser_backend.name`(`ofono_reference`)이 백엔드 불일치를 일으켜 쓰기가 막힌다. oFono DB는 이 플랫폼 분리가 들어간 플러그인부터 쓴다.
- 카테고리 목록은 그 DB의 `categories`, 로그 출처 → 카테고리 매핑은 그 DB의 `parser-rules/tags.yaml`이 정한다(코드에 카테고리 6종 가정 없음).

## 5. guard 다중 프로필 (`08-safety.md §9`)

- 사용자 config의 **모든** 프로필(`enabled`·선택과 무관)의 clone·`work_dir`·원격·base를 보호한다: 규칙 2(승인 기록 파일)·8·11, git 규칙(cwd가 속한 프로필의 base). 이름이 잘못된 프로필의 clone도 보호한다.
- 규칙 8은 가장 구체적인 경로 기준이다: clone **안의** 유효한 `work_dir`만 제외 근거이고, 잘못된 `work_dir`은 근거가 아니다.
- 규칙 10은 설치된 모든 플랫폼(`known()`) 판별 합집합 + 플랫폼을 못 불러오면 내장 최소 판별, 판별 예외는 거부.
- jira_bridge: 읽기 결과 = 선택 플랫폼 `work_dir`, 게시 결과 = 본문 sha가 맞는 승인 프로필, 없으면 모든 프로필 fail-closed.
- pre-push(이슈 DB 안): push 커밋의 `platform` 선언(읽지 못하면 거부)으로 `platforms.<p>`의 `work_dir`·base를 고른다.

## 6. 새 플랫폼 추가 절차 (체크리스트)

1. `plugin/scripts/platforms/<p>/__init__.py`에 `SPEC = PlatformSpec(...)`. 이름은 `^[a-z][a-z0-9_]*$`. import는 §1-2. 모르는 값은 `TODO(SITE:S<n>)`(`14-site.md §14.2`에 행 추가)와 placeholder로 둔다.
2. 줄 해석(`LogFormat`): `read_file`·`raw_line`·`find_raw`·`epoch_break`. 해석 못 한 줄은 `FileStats.unparsed`로 센다(파일 단위 경고 `file-unparsed`).
3. 백엔드: `platforms/<p>/backend.py`(`ParserBackend` 상속, `name = "<p>_reference"`, `platform = "<p>"`, `version()`, `builtin_events()`) + `parser_backends/<p>_reference/__init__.py`(재수출만). 다른 플랫폼 모듈은 import하지 않는다(본보기 `platforms/ofono/backend.py`).
4. 짝 규칙이 있으면 `SPEC.protocols`(`PairProtocol`), 슬롯 표기가 있으면 `SPEC.phone`, 묶음 입력이 있으면 `SPEC.capture`. 한 로그 스트림에 구성요소(데몬)가 여럿이면 `SPEC.components`·`msg_formats`·`protocol_kinds`와 `block_keys`의 `components`·`protocols`(§9).
5. site-defaults: `platform.enabled`에 이름 추가, 상수는 `platform.others.<p>`(그 플랫폼 `block_keys`만), 기본 아닌 백엔드면 `parser.by_platform.<p>`, 분석 스킬 팀 기본은 `platforms.<p>.analyzers`(선택, §10-1). `site-defaults.example.yaml`에 주석 예시.
6. 이슈 DB: 새 레포. `issue-db.config.yaml`에 `platform: <p>`, `platform_versions_supported`, `parser_backend.name: <p>_reference`, `code_root_keys`(그 플랫폼 루트), 그 플랫폼 `categories`·`parser-rules`. 뼈대는 `tools/make_db_skeleton.py <out> --platform <p>`(위 키를 그 플랫폼 기본값으로 넣고 parser-rules는 스키마 최소 placeholder 항목, 카테고리는 일반 6종 시작점)로 만든 뒤 메인테이너가 채운다. pre-push는 플랫폼 분기가 있는 hook(샘플 DB `.githooks/pre-push`)을 쓴다.
7. 사용자: `/telephony-triage:setup`에서 그 플랫폼을 고르거나 `config.py init --platform <p>` → `platforms.<p>.issue_db.path` 등.
8. 테스트: 합성 로그 fixture(손으로 쓴 것, README에 "합성·형식 가정·placeholder"), 변형 DB(`tests/helpers/make_variant_dbs.py`), 전환 검증(같은 명령이 DB에 따라 백엔드·태그·카테고리·이벤트·매칭이 바뀌고, 섞으면 `platform-mismatch`), 계층 테스트, `tools/check_boundary.py --mode external`. android 바이트 동일성(골든·`db_regress` 샘플·fixture)이 그대로인지 본다.
9. 문서: 이 문서 §7에 결정, `14-site.md`에 TODO(SITE) 행, 사용자용 로그 수집 체크리스트(본보기 `docs/development/OFONO_LOG_COLLECTION.md`), 탐색 지식 `plugin/skills/telephony-triage/reference/platforms/<p>/*.md`(선택, placeholder + TODO(SITE), §10-2).

## 7. 결정 기록

| # | 결정 | 이유 |
|---|---|---|
| K1 | 레지스트리 = `platforms/<name>/__init__.py`의 `SPEC` 하나, 이름으로 동적 import. "등록"은 site `platform.enabled`. `SUPPORTED` 튜플은 없앴다 | `parser_backends.load`와 같은 방식. 추가 = 디렉토리 하나 + `enabled` |
| K2 | 사용자 config 최상위 경로 키는 항상 android 프로필, 그 밖은 `platforms.<name>`(기본 `work_dir` `<home>/work-<name>`) | 기존 config·경로 그대로. 두 벌 설치도 같은 config를 충돌 없이 쓴다 |
| K3 | 선택 순서 `--platform` > `TT_PLATFORM` > 사용자 `platform` > site `platform.name` > android. `enabled` 관문은 사용자 세션 흐름만. `triage.py run`은 켠 플랫폼 2개 이상·명시 없음이면 하나로 정해진 로그 형식이 사용자·site 기본보다 앞선다(K18) | triage가 하위 스크립트에 env로 넘긴다(기존 `TT_LOCK_OWNER` 방식) |
| K4 | **lock은 플랫폼(이슈 DB)별**(사용자 결정 10/11, 설계 초안의 "사용자당 하나"를 바꿈). lock·`session.guard`는 각 플랫폼 `work_dir`, 기록 `platform`은 android 아닐 때만 | android·oFono 작업을 동시에 할 수 있다. 원칙 문구를 "사용자·이슈 DB(플랫폼)별 한 번에 한 작업"으로 고쳤다 |
| K5 | 이슈 DB `platform` 선언, 세션 선택과 다르면 거부(`platform-mismatch`) | **동작·원인·해결책이 플랫폼마다 달라** 다른 DB에 대고 매칭하는 것은 의미가 없다. 시그니처에 platform 표시를 다는 "합치기" 안은 쓰지 않는다(사용자 결정) |
| K6 | DB에 고정된 도구는 DB 선언 플랫폼, 사용자 세션 흐름은 선택과 DB 선언을 대조 | oFono DB의 CI는 사용자 config 없이 돈다. `parse_logcat`은 사용자 config를 읽지 않는다 |
| K7 | **RF-4 유지**: 플랫폼 상수(정규식·디렉토리·태그·섹션 헤더)는 site-defaults에서만. 사용자 config는 이름 선택과 경로 프로필 + 사용자 수준 키 `analyzers`(K16)만, `platforms.<p>`의 그 밖 키는 거부 | 상수는 결정적 파서 출력과 이슈 DB 회귀 기준을 정한다. 사람마다 다르면 같은 fixture가 다르게 판정된다. 이번 요구는 "어느 상수 묶음을 쓸지 고르기"다 |
| K8 | 출력 `platform` 키는 android 아닐 때만(켠 플랫폼 2개 이상이면 `--platform` 없이 고르는 플랫폼 또는 지정과 다를 때도, K18), 라벨은 `SPEC.label` | android 바이트 불변, 기존 "있을 때만" 키 관례 |
| K9 | (해소, 트래커 범용화) 스키마 필드 `android_version(s)`·`code_profiles[].android_version`·`field_map.android_version`을 `platform_version(s)`로 개명했다. DB 키는 `platform_versions_supported` 하나(옛 키는 읽지 않고 `db_lint` config 오류) | 처음에는 이슈 DB 마이그레이션이 필요해 미뤘다. 배포된 이슈 DB가 없어 원칙 (d)로 v1을 직접 고쳤다(`18-trackers.md` T4·T10). 옛 사용자 config 키는 감지만 한다(T5) |
| K10 | 짝 규칙은 `SPEC.protocols`(0개 이상), 비-ril은 `proto` 주석, `pair`는 자기 주석만. `ril.yaml` 요청 이름은 DB 전체에서 유일 | oFono는 RIL 계층과 D-Bus 등 둘 이상일 수 있다 |
| K11 | 카테고리는 플랫폼 DB `categories`, 출처 → 카테고리는 플랫폼 DB `tags.yaml` | 코드에 카테고리 가정 없음(조사 결과) |
| K12 | 구성요소(데몬) 계약은 `platforms/base.py` 공통 타입(`Component`·`MsgView`)과 `PlatformSpec` 뒤쪽 기본값 필드. 플랫폼은 `block_keys`의 `components`로 opt-in(ofono만, android SPEC·`block_keys` 불변). ident·루트·형식은 site-defaults, 카테고리·허용 루트 키는 DB (§9-1) | 사용자 답: oFono DB 하나에 모든 데몬(K5 유지). 레지스트리가 루트 키·형식을 일반 검사하고 다음 플랫폼도 쓴다(ofono 전용 모듈이면 `code_roots`가 플랫폼을 알아야 해 §1-2 위반). 파서 출력 상수라 site-defaults(K7) |
| K13 | 메시지 하위 형식 hook(`msgformat.py` 함수 하나 + 등록 한 줄) + 선택 `split_tag`(기본 꺼짐, tag `<ident>/<subtag>`) (§9-2) | 기본 출력 바이트 동일. 한 데몬이 여러 카테고리에 걸치는 사이트만 켠다 |
| K14 | 데몬 사이 짝 = 설정 프로토콜(`protocol_kinds`, ofono `regex`). 이름은 site, 기본 꺼짐, 짝 키 `serial`, 짝은 한 스트림 안에서만, 짝 없는 요청의 `observed_until` = 구간 끝. 대화 키는 없다(S26) (§9-3) | 엔진은 이미 스트림 구간 전체를 `pair()`에 준다. 프로토콜마다 `proto`·대기 표가 따로라 계층이 섞이지 않는다(규칙 목록 하나인 고정 프로토콜은 serial이 충돌). 형식 미정이라 코드 없이 설정으로 |
| K15 | 여러 소스 루트: 구성요소 루트의 `required_dirs` 검사와 `component_versions`(참고 출력, 구성요소가 있는 플랫폼만), 주 루트 계속 필수, `platform_version`은 하나 (§9-4) | android 출력 불변. 버전 뜻(S28)이 정해지기 전에 비교 기준을 늘리지 않는다 |
| K16 | 분석 스킬(5-1): 최상위 `analyzers` = 항상 android, 그 밖 플랫폼은 site·사용자 `platforms.<p>.analyzers`를 deep-merge한 것만(android 것으로 대신하지 않음 — 없으면 질문 없이 리포트 `해당 없음`). 키 목록 `PLATFORM_SCOPED_KEYS`(`PROFILE_KEYS` 밖), site `platforms.android`·모르는 키는 종료 코드 2, guard 규칙 12는 모든 층·플랫폼 합집합 (§10-1) | oFono 1위 `data`에 Android 분석 스킬(site `analyzers.data`)이 제안됐다. 최상위 = android는 K2와 같은 뜻(site `platform.name`에 따라 바뀌지 않는다). `platform.others.<p>`는 RF-4 파서 상수 블록(바꾸면 `db_regress`)이라 분리. `source`는 개인 경로라 사용자 층이 필요하다 |
| K17 | 탐색 지식(5-2): 내장 `reference/platforms/<p>/*.md` 관례 + `triage.py explore` 출력 `platform`·`refs`(android 아닐 때만), `reference/explore.md` 한 항목. 사이트 지식 스킬 연결은 S-4a (§10-2) | 다른 스택의 태그·요청·원인 이름은 가설을 틀린 쪽으로 끈다. 어느 문서를 읽을지 스크립트가 알려 SKILL.md(크기 상한) 불변, 추가 = 디렉토리 하나. 동의 뒤에만 필요해 `analysis.json`·캐시 밖 |
| K18 | 이슈 시작 때 플랫폼 = 로그 자동 + 애매하면 질문(사용자 결정 D1~D6). `run`만, `resolve` 뒤·`Driver` 전(lock·JOB 전), 켠 플랫폼 2개 이상·`--offline-db` 아님. 명시 = `--answer platform=` > `--platform` > `TT_PLATFORM`, 사용자 `platform`·site는 기본값(로그 형식이 이김), 명시와 형식이 다르면 한 번 묻기(답은 이어 하는 작업에 `platform_answer`로 남아 다시 묻지 않음), 출력 `platform`은 암묵 선택·지정과 다를 때도 (§11) | lock·work_dir가 플랫폼별(K4)이라 그 전에 정해야 한다. 판별은 스크립트(guard 규칙 10과 같은 `raw_line`), LLM 추측 없음. 질문은 일반 `needs_input`이라 SKILL.md 불변. 단일 플랫폼 설치는 파일을 열지 않아 바이트 동일 |

그 밖: `compiled.environment(defaults, platform)`은 `parser.backend`가 없으면 `SPEC.default_backend`를 쓴다(그런 설치만 분석 재사용 해시가 한 번 바뀐다). 두 벌 설치는 커맨드 이름 공간과 hook이 두 번 걸리므로 권장은 한 벌 설치 + `enabled` 2개다.

## 8. 미룬 것

- **oFono 실제 파서 규칙·이슈 DB 내용**: 사내 로그를 받은 뒤 사내 모드에서(S24~S29, `docs/development/OFONO_LOG_COLLECTION.md`). 지금 `platforms/ofono`는 형식 가정(journald `short-iso-precise`·BSD syslog) placeholder이고 합성 로그로 전환만 검증한다. 실제 로그·형식은 사외로 가져오지 않는다.
- **`external_parsers`는 기본 플랫폼만** 쓴다(그 밖 플랫폼은 `{}`). 비기본 플랫폼 어댑터는 필요할 때 `platform.others`·DB `external_parsers`와 함께 정한다.
- **트래커 설정 플랫폼별 덮어쓰기**: `tracker.*`(트래커 종류·`field_map` 등)는 플랫폼끼리 공유한다. oFono 트래커나 프로젝트가 다르면 `platforms.<p>.tracker` 덮어쓰기(`PROFILE_KEYS` 확장)를 다음 작업으로(S28·S32, `18-trackers.md` T9).
- parser-rules 스키마가 `ril.yaml` 항목 1개 이상과 요청 이름 `^[A-Z][A-Z0-9_]*$`를 요구한다. oFono DB에 placeholder 항목이 필요하고, D-Bus식 이름(`GetProperties` 등)은 넣을 수 없어 설정 프로토콜(§9-3)의 파생 이벤트(`ril_error`·`ril_timeout`·`ril_no_response`)가 생기지 않는다(짝·지연은 이벤트에 보인다). 이름 정규화(`regex` 옵션)나 프로토콜별 규칙 파일(스키마 마이그레이션, 메인테이너)은 S26이 정해진 뒤에.
- **site-defaults ↔ 이슈 DB 교차 점검**(구성요소 ident가 `tags.yaml`에 없음, `root_key`가 `code_root_keys`에 없음 → doctor·site 점검 경고)은 미룬다.
- **탐색 지식 스킬 연결**(사이트 로그 분석 스킬을 Step 5-2에서 부르기, 키는 `platforms.<p>` 아래)은 S-4a에서(`16-existing-assets.md §16.5`). 지금은 내장 `reference/platforms/<p>/`(§10-2).
- **감지가 기본 아닌 플랫폼을 고르는 eval**(플랫폼 말 없이 다른 플랫폼 로그)은 eval 하네스가 둘째 플랫폼 프로필을 만들 수 있을 때. 지금은 pytest(`tests/test_platform_detect.py`)가 덮는다. Jira 실제 필드 → 플랫폼 대응(`platform.detect.tracker_field`)은 S28·S32.

## 9. 한 플랫폼 안의 여러 구성요소(데몬)

> 10/30 사용자 요청("oFono 외에 여러 데몬도 같이 돈다"). 사용자 답: (1) 모든 데몬을 oFono 이슈 DB 하나에 둔다(플랫폼은 `ofono` 그대로, K5 불변), (2) 로그는 한 스트림(journald/syslog)이고 줄마다 데몬 식별자(ident)가 있다, (3) 데몬마다 소스가 따로 있다, (4) 데몬 사이 요청·응답 짝이 필요하다(형식 미정 — placeholder). 결정은 §7 K12~K15. 기본 설정의 출력은 이전과 같고, 새 기능이 있어 `ofono_reference`는 0.0.2다(DB가 `min_version`으로 요구할 수 있다).

### 9-1. 구성요소 계약 (`platforms/base.py`)

- `Component(name, idents, root_key=None, source_tree=None, msg_format=None, split_tag=False)`: 로그 ident 묶음 ↔ 소스 루트 키 ↔ 그 루트의 필수 디렉토리·버전 출처 ↔ 메시지 하위 형식. `name` `^[a-z][a-z0-9_-]*$`, `idents`는 `LogLine.tag`의 정확한 이름(1개 이상, 구성요소끼리 겹치지 않음), `root_key`는 code_ref 키 형식 `^[a-z][a-z0-9_]*$`(겹치지 않음), `source_tree`는 `root_key`가 주 루트가 아닐 때만(주 루트 것은 블록 `source_tree`), `msg_format`은 `SPEC.msg_formats`의 이름, `split_tag`는 `msg_format`이 있을 때만.
- `MsgView(body, subtag=None)`: 형식 함수 `(msg) -> MsgView | None`의 결과. `body`는 앞머리를 뗀 본문(짝 규칙 annotate 입력), `subtag`는 모듈 등 하위 식별.
- `PlatformSpec` 뒤쪽 기본값 필드: `components`(기본 구성요소), `msg_formats`(`(이름, 함수)`), `protocol_kinds`(`(kind, 팩토리)`, §9-3). `PlatformProfile`에 `components`·`protocols`(SPEC 것 다음 설정 것 순서).
- opt-in: `block_keys`에 `components`가 있는 플랫폼만(ofono) site-defaults `platform.others.ofono.components.<이름>: {idents, root_key, source_tree, msg_format, split_tag}`를 받는다. 쓰면 SPEC 기본을 **통째로 바꾼다**(`{}` = 구성요소 없음, `null` = 생략과 같음). 잘못된 값은 키 경로와 종료 코드 2. android에서 `components`는 지금처럼 모르는 키 오류다.
- ofono 기본: 구성요소 `ofono`(ident `ofonod`, 루트 `ofono`, 형식 `file_func`) 하나 — 공개 upstream 값, `TODO(SITE:S24·S25)`. 사내 데몬은 코드에 넣지 않는다.

### 9-2. 한 스트림 안의 줄 해석

- 이벤트 `tag`는 ident 그대로다(`journal.py` 불변). 백엔드가 ident로 구성요소를 찾고 `msg_format`이 있으면 그 함수로 앞머리를 뗀 본문을 annotate에 준다. 이벤트 `msg`는 원문, 이벤트 키 추가 없음(EVENT_KEYS·분석 스키마 불변).
- 형식 더하기 = `platforms/ofono/msgformat.py`에 함수 하나 + `FORMATS` 한 줄(유일한 코드 hook), 고르기 = 설정 `msg_format: <이름>`. 기본 `file_func`는 upstream 디버그 앞머리(`src/x.c:func() `) 가정 placeholder(TODO(SITE:S24)).
- `split_tag: true`(기본 꺼짐)면 이벤트 `tag` = `<ident>/<subtag>`(이벤트 tag는 마스킹되지 않으므로 `subtag`가 글자로 시작하는 식별자 `^[A-Za-z][A-Za-z0-9_-]{0,63}$`일 때만, 아니면 나누지 않는다). 한 데몬이 여러 카테고리에 걸칠 때 쓰고 `tags.yaml`·extractor는 `tag_regex`로 맞춘다 — 정확한 `tag:` 규칙과 마커의 태그 매칭도 바뀐 tag를 본다.
- ident → 카테고리는 계속 DB `tags.yaml`(K11). 구성요소별 카테고리를 둘지는 메인테이너 결정(S25).

### 9-3. 데몬 사이 짝 (설정 프로토콜)

- 엔진 변경은 없다: `pair()`는 한 스트림 구간의 레코드를 모두 받으므로 `tags`가 여러 데몬을 묶은 프로토콜은 pid·tag와 무관하게 짝을 짓는다. 없던 것은 코드 없이 설정으로 만드는 프로토콜이다.
- `platform.others.ofono.protocols.<이름>: {kind: regex, tags: [...], request: '<정규식>', response: '<정규식>'}`. 이름은 site가 짓는다(`^[a-z][a-z0-9_]*$`, `ril` 금지. SPEC 고정 이름이면 지금처럼 `tags`만). 각자 `PairProtocol`이라 `proto: <이름>`과 대기 표가 따로다. `kind`는 그 플랫폼 `protocol_kinds`에 있어야 한다(ofono `regex` = `platforms/ofono/pairing.py`). 설정이 없으면 프로토콜도 없다(TODO(SITE:S26)).
- `regex`: `tags`는 ident다(`split_tag`와 무관). annotate 본문에 `re.search`, 요청을 먼저 본다. `request`는 이름 그룹 `serial` 필수·`name` 선택, `response`는 `serial` 필수·`name`·`error` 선택. serial이 10진이 아니거나 `name`·`error`가 식별자 모양(글자로 시작, `[A-Za-z0-9_.]`, 128자 이하 — 숫자로 시작하는 전화번호·IMSI·IP와 `:`이 든 MAC은 안 된다)이 아닌 줄은 주석을 달지 않는다(자유 문장을 싣지 않는다). `--mask`면 `parse_logcat`이 `proto` 주석의 `request`·`error`도 마스킹하고 파생 이벤트 필드는 그 값으로 만든다(android 주석은 `proto`가 없어 그대로). 짝 키는 그 프로토콜 안의 `serial`(같은 키의 나중 요청이 대기 요청을 바꾼다). 한쪽에 없는 요청 이름은 다른 쪽에서 채우고 둘 다 `paired_ts`·`latency_ms`를 받는다. 짝 없는 요청은 `observed_until` = 그 구간의 가장 늦은 레코드 시각(태그 무관)이라 `ril_no_response`가 생길 수 있다. 같은 serial의 나중 요청에 밀려난 요청은 `observed_until`을 받지 않는다(대화 키가 없어 연결별 serial 충돌일 수 있으므로 응답 없음으로 단정하지 않는다).
- 대화 키(연결마다 serial이 다시 시작하는 경우)는 넣지 않았다: annotate는 `ril` 칸만 내고 그 키 목록이 닫혀 있어 `pair()`에 넘길 수 없다. 필요한지는 S26에서 본다.
- 짝은 **한 스트림 안에서만** 생긴다. 유닛별 파일(`journal-<유닛>.log`)은 스트림이 따로라 데몬 사이 짝이 없고, 합친 `journal.log`와 같이 넣으면 줄이 두 번 나온다 — 분석은 합친 journal 하나로 한다(`docs/development/OFONO_LOG_COLLECTION.md`).
- 파생 이벤트는 요청 이름이 DB `ril.yaml`에 있을 때만 생긴다(§8).

### 9-4. 여러 소스 루트 (`code_roots.py`)

- 이미 되던 것: `code_profiles[].roots`의 여러 키, `find-symbol`·`resolve`의 전체 루트, DB `code_root_keys`.
- `validate`: 주 루트 밖 구성요소 루트가 `roots`에 있고 디렉토리면 `component_versions: {<root_key>: 버전|null}`에 넣는다(그 구성요소에 `source_tree`가 있으면 `required_dirs`를 보고(없으면 오류) 버전을 추정, 없으면 `null`). 구성요소가 있는 플랫폼만 이 키가 있다(android 출력 불변). 빠진 구성요소 루트는 오류가 아니다. DB가 없을 때 루트 키 = `default_root_keys` ∪ 구성요소 `root_key`.
- 주 루트(ofono `ofono`)는 계속 필수, `platform_version`은 하나다(뜻은 S28). `component_versions`는 참고 출력이고 `--version`과 비교하지 않는다. `suggest`는 그대로.
- 뼈대 DB(`make_db_skeleton.py --platform ofono`)의 `code_root_keys`는 코드 기본값(`default_root_keys` ∪ `SPEC.components` 루트 키, site-defaults는 보지 않는다)만 넣고 `TODO(SITE:S27)` 주석을 단다. `tags.yaml` placeholder에는 "ident마다 한 줄, 카테고리는 S25" 주석.

### 9-5. 구성요소 하나 더하기

| 무엇 | 어디 |
|---|---|
| ident·소스 루트 키·필수 디렉토리·버전 출처·메시지 형식 | site-defaults `platform.others.ofono.components.<이름>` (S24·S25·S27) |
| ident → 카테고리 | 이슈 DB `parser-rules/tags.yaml` (S25) |
| code_ref 허용 키 | 이슈 DB `code_root_keys` (S27) |
| 데몬 사이 짝 | site-defaults `platform.others.ofono.protocols.<이름>`(`kind: regex`), 파생 이벤트는 DB `ril.yaml` (S26) |
| 새 메시지 형식 | `platforms/ofono/msgformat.py` 함수 하나(필요할 때만) |

바꾼 뒤에는 플랫폼 상수 규칙(`02-config.md`)대로 이슈 DB에서 `db_regress --all`·`db_verify rules`를 다시 돌린다. site-defaults ↔ DB 교차 점검은 아직 없다(§8).

## 10. 분석 스킬·탐색 지식의 플랫폼 분리

> 10/30 사용자 요청("이슈 DB에 맞는 규칙이 없을 때 스킬 기반 가설 분석이 Android와 다른 스킬로 동작해야 한다"). Step 5-1(분석 스킬 선택)과 Step 5-2(탐색 지식) 둘 다. 결정은 §7 K16·K17. android 출력은 이전과 같다.

### 10-1. 분석 스킬 (Step 5-1)

| 층 | 키 | 의미 |
|---|---|---|
| site-defaults | `analyzers.<cat>` (최상위) | android 팀 기본 |
| site-defaults | `platforms.<p>.analyzers.<cat>` | `<p>` 팀 기본. `platforms:` 아래 키는 `analyzers`만 |
| 사용자 config | `analyzers.<cat>` (최상위) | android 개인 값 |
| 사용자 config | `platforms.<p>.analyzers.<cat>` | `<p>` 개인 값(`source` 같은 개인 경로) |

- 병합: android가 아닌 플랫폼의 cfg `analyzers` = site `platforms.<p>.analyzers` 위에 사용자 `platforms.<p>.analyzers`를 deep-merge한 것(`userconfig._with_profile`). 최상위(android) `analyzers`는 어느 층이든 **물려받지 않는다** — 없으면 Step 5-1 질문이 없고 리포트는 `심층 분석: 해당 없음(1위 카테고리에 분석 스킬 설정 없음)`. Driver `analyzer()`·`skill_patch` `configured_source`는 선택 플랫폼 cfg를 읽으므로 따로 바뀌지 않았다. `analysis.json` `analyzer{skill, when}` 모양 불변.
- 키 목록 `userconfig.PLATFORM_SCOPED_KEYS = ("analyzers",)`: `PROFILE_KEYS` 밖이다(최상위 `PROFILE_KEYS`는 "android 프로필이 있다"는 뜻 — `_raw_profiles`·`config.py init`). 사용자 `platforms.<p>`에 둘 수 있고(`profile_problems`, 값은 `{카테고리: 매핑}`), `config.py set --platform <p> analyzers.<cat>.source <경로>`는 `platforms.<p>.analyzers.<cat>.source`에 쓴다(`profile_key`). `init --platform <p> --force`는 그 프로필의 `analyzers`를 유지한다. `set`을 `init`보다 먼저 하면 프로필이 생겨 뒤 `init --platform <p>`는 `--force`가 필요하다. 기본값으로 대신하는(fallback) 키(예: `platforms.<p>.tracker`, §8)가 생기면 다른 튜플로 둔다.
- site 검증 `userconfig.site_platform_problems`: `platforms`가 매핑, 이름 `^[a-z][a-z0-9_]*$`, `platforms.android` 금지(android는 최상위 키), `PLATFORM_SCOPED_KEYS` 밖 키 금지(플랫폼 상수는 `platform.others.<p>`), 값 모양. `session.resolve`는 종료 코드 2, `resolve_lenient`(`config.py show`·`set`·`doctor`)는 문제 목록(doctor `platform` 행).
- 리포트 `when: never` 줄의 키 경로: android `analyzers.<cat>.when: never`(바이트 동일), 그 밖 `platforms.<p>.analyzers.<cat>.when: never`.
- guard 규칙 12: site-defaults·사용자 config의 최상위와 **모든** `platforms.<p>.analyzers`의 `source` 합집합(`userconfig.analyzer_sources` — 이름이 잘못된 것도, 사용자 config에 그 프로필이 없어도, §5와 같은 "보호는 넓게").

### 10-2. 탐색 지식 (Step 5-2)

- 관례: 플러그인 `skills/telephony-triage/reference/platforms/<p>/*.md`(경로 상수 `triagelib/core.py` `PLATFORM_REFS_DIR`, 코드에 플랫폼 이름 없음). 지금은 `ofono/log-guide.md` 하나(placeholder·공개 upstream 개념만, TODO(SITE:S24~S26), 3,072B 이하 — `tests/test_triage.py`).
- `triage.py explore` 출력: 작업 플랫폼이 android가 아니면 `{timeline, lines, total}`에 `platform`과 `refs`(그 디렉토리의 `*.md`, 스킬 디렉토리 기준 경로, 이름순, 없으면 `[]`)를 더한다. 작업 플랫폼 = `JOB/analysis.json`의 `platform`(키가 없으면 android), 그 파일을 읽지 못하면 선택 플랫폼 — `--out` 오프라인 작업도 그 작업의 문서를 받는다. android는 키가 없다(출력 불변). `analysis.json`·스키마·분석 재사용 캐시에는 넣지 않는다.
- 스킬: `reference/explore.md` "읽는 것" 5번 — `platform`이 있으면 `refs` 문서만 읽고 Android 참고 자료(`log-tags.md`·`ril-requests.md`·`fail-causes.md`)는 열지 않는다, `refs`가 비면 그 이슈 DB `SNAP/parser-rules/`만. SKILL.md와 Android 참고 자료 머리말("Android 기준")은 그대로.
- 새 플랫폼 = `reference/platforms/<p>/` 디렉토리(선택) + site `platforms.<p>.analyzers`(선택). 사이트 지식 스킬 연결은 S-4a(§8).

## 11. 이슈 시작 때 플랫폼 정하기

> 10/30 사용자 결정("로그 자동 + 애매하면 질문", D1~D6). 결정은 §7 K18. 켠 플랫폼이 하나인 설치(android 단독 포함)는 파일을 열지 않고 출력이 이전과 바이트 단위로 같다.

### 11-1. 언제·무엇이 명시인가

- `triage.py main`이 `run`에서만 `session.resolve` 뒤·`Driver` 전(work_dir·lock·JOB 전)에 `triagelib/pick.py` `choose()`를 부른다. `platform.enabled`가 2개 미만이거나 `--offline-db`(DB 선언 대조, K6)면 아무것도 읽지 않는다.
- 명시: `--answer platform=<p>`(최우선) > `--platform` > `TT_PLATFORM`. 사용자 config `platform`·site `platform.name`은 기본값이라 하나로 정해진 로그 형식에 진다(D1). `--answer platform=`은 `choose()`가 꺼내 `args.answer`에서 뺀다(`answers`·입력 해시에 안 들어감, 이어 하는 작업 표시 `platform_answer`만 남음 — §11-3). 켜지지 않은 이름이면 종료 코드 2.
- 암묵 선택 = `session.implicit(defaults, user)`: `--platform` 없이 고르는 플랫폼(`TT_PLATFORM` > 사용자 `platform` > site, 잘못되면 android). hook(`jira_bridge` 읽기 결과 위치)·플래그 없는 스크립트와 같은 기준이다.

### 11-2. 로그 형식 판별 (`platforms/sniff.py`)

- 파일마다 켠 플랫폼의 SPEC 판별만 쓴다: `capture.looks_like(path)`가 참이면 그 플랫폼(zip은 줄을 읽지 않는다). 아니면 `common.logtime.open_log`로 비지 않은 줄 앞 200줄·256KiB까지(줄 하나도 256KiB까지만 — 개행 없는 큰 파일을 통째로 읽지 않는다) 읽어 `log.raw_line(줄)`이 참인 줄 수 `hits`가 `hits ≥ max(1, min(3, 표본))`이고 `hits / 표본 ≥ 0.5`면 그 플랫폼에 맞는다.
- 전체: 맞은 파일이 모두 같은 한 플랫폼이면 그 플랫폼, 파일끼리 다르거나 한 파일이 둘 이상에 맞으면 모호. 어디에도 안 맞는 파일(읽기 오류·판별 예외 포함)은 형식 미확인으로 세기만 한다 — 나머지가 한 플랫폼이면 그 플랫폼 + 노트(D4). 결과에 원문 줄은 없다.
- 상수(200줄·256KiB·3줄·0.5)는 설정이 아니다(K7과 같은 이유). 사내 형식이 다르면 `raw_line` 자체를 고친다 — guard 규칙 10과 같은 판별이라 함께 따라간다(S24). import는 `platforms`(레지스트리)·`common.logtime`만(§1-2).

### 11-3. 판정

- 명시가 있으면: 로그 형식이 하나로 정해졌고 명시와 다르면 한 번 묻는다(D2, 선택지 `<A> (지정)`·`<B> (로그 형식)`). 단 답으로 정해 질문에서 멈춘 이어 하는 작업(`pending`+`platform_answer`, 아래)이 명시나 로그 형식과 같으면 묻지 않고 그 플랫폼으로 잇는다 — 답 없이 이어 하는 작업(로그 형식으로 고른 뒤 다른 질문에서 멈춘 작업, `--more-logs`의 이전 작업)은 로그 형식과 같아도 묻는다. 그 밖(형식 모호·미확인, 로그 없음)은 명시대로이고 Jira·이어 하는 작업과 달라도 묻지 않는다.
- 명시가 없으면: 로그도 이어 하는 작업도 없으면 **lock 전** `needs_input logs`(Driver와 같은 kind·문구, 선택지 = 켠 플랫폼마다 그 프로필 `log_dir`의 파일을 최신순으로 합쳐 10개, label `<파일 이름> (<플랫폼 라벨>)`) — 기본 플랫폼으로 lock을 잡은 뒤 다른 플랫폼으로 판정되면 잘못된 work_dir에 lock·JOB이 남기 때문이다. 그 밖은 표 = {로그 형식(하나로 정해졌을 때), Jira 대응표(§11-5), 이어 하는 작업}에서 서로 다른 플랫폼이 1개 → 그 플랫폼, 2개 이상 → `needs_input platform`(선택지: 표를 낸 플랫폼(출처 라벨) 다음 나머지 켠 플랫폼, 암묵 선택에 "(기본)"), 0개(로그는 있는데 정하지 못함) → `needs_input platform`(파일별 형식 `f<순번>`을 문구에).
- 이어 하는 작업: 켠 플랫폼마다 `<work_dir>/<KEY>/triage-state.json`에 `pending`(직전 실행이 질문으로 끝남)이 있거나, 로그를 주지 않았거나 `--more-logs`면 이전 로그(`logs`·`job.logs`)가 있는 곳. 읽기만 한다. 답(`--answer platform=`)으로 정한 작업은 Driver가 lock 뒤(lock 질문에서 멈춰도) 상태 `platform_answer: <p>`를 남긴다 — 그 작업에 `pending`과 함께 있으면 답으로 정한 작업이다. 답은 그 질문이 이 KEY의 가장 늦은 활동일 때만 쓴다: 답으로 정한 작업 가운데 `pending.asked_at`이 가장 늦은 하나(같으면 없음)이고, 다른 켠 플랫폼 작업의 마지막 질문(`pending.asked_at`)·완료(`job.runs[-1].at`)가 모두 그보다 이를 때(같은 초는 막고, 시각 없는 작업은 막지 않는다). 그 밖(답한 뒤 다른 플랫폼에서 묻거나 끝난 작업이 있음)은 답을 쓰지 않는다: 이어 하는 작업이 하나면 답 없는 작업처럼 그 작업, 여럿이면 없음(답 없는 작업끼리는 고르지 않는다 — 로그 형식으로 고른 작업은 표가 다시 정한다). 답을 쓰면 그 작업은 로그 형식·Jira보다 앞서(명시가 있으면 명시나 로그 형식과 같을 때) 그 플랫폼으로 잇는다. 그래서 스킬이 다음 호출에서 `--answer platform=`을 빼거나 출력 `platform`으로 `--platform`을 붙여도, 바로잡기 전 작업(로그 형식으로 고른 뒤 질문에서 멈춘 작업)이 다른 플랫폼에 남아 있어도 다시 묻지 않는다(한 번 묻기, D2).
- 없는 로그 파일이 있으면 판정하지 않는다(Driver가 지금처럼 종료 코드 2).

### 11-4. 질문·출력·기록

- 질문은 lock·JOB 없이 낸다: `{status: needs_input, key, needs_input: {kind: platform, question, options, answer: "--answer platform=<값>"}, lock_owner: null}`. 그래서 trace·`pending`에 남지 않고 `job_status`는 이 질문을 보지 못한다. 문구에는 경로·파일 이름·트래커 값을 넣지 않는다(파일은 `f<순번>`, 플랫폼은 라벨).
- 고르면: `notes`에 한 줄(예 `로그 형식으로 oFono 선택 (기본 Android 대신)`, 형식 미확인 파일이 있으면 그 수), `report.md` 머리 쪽 `- 플랫폼: <라벨> (<근거>)`(must_show 아님, D6), trace `platform` 행 `{platform, source: logs|jira|resume|answer}`. 명시대로 진행하면 노트·행이 없다.
- 출력 `platform`(K8 보강, D5): android가 아니거나 암묵 선택과 다르거나, 이번 실행이 플랫폼을 골랐고(노트가 있음) 지정(`--platform`·`TT_PLATFORM`)과 다를 때(`Driver.platform_out`). 예: 사용자 `platform: ofono` + Android 로그 → `platform: android`(스킬이 이후 호출에 `--platform android`를 붙인다), `--platform ofono` + Android 로그에서 `android`를 답함 → `platform: android`. `needs_input`·`stopped` 출력도 켠 플랫폼 2개 이상에서 같은 규칙으로 낸다(스키마 선택 키). 켠 플랫폼이 하나면 K8 그대로.
- Jira 원문 이동(기존 틈 수정): hook은 `--platform`을 몰라 Jira 원문을 암묵 선택 플랫폼 work_dir에 둔다. `Driver.jira()`는 JOB에 `issue_raw.json`이 없고 `--issue-raw`·`--issue-file`도 없으며 작업 플랫폼이 암묵 선택과 다르면 `<암묵 work_dir>/<KEY>/issue_raw.json`을 이 JOB으로 옮기고(`os.replace`, 안 되면 move) 빈 작업 디렉토리를 지운 뒤 기존대로 `--consume` 추출한다(trace `platform-raw {moved_from}`). 켠 플랫폼 2개 이상에서 `--platform`을 명시한 경우도 같다.
- `release`·`explore`(`--out` 없음): `--platform`·`TT_PLATFORM`이 없고 선택 플랫폼 work_dir에 KEY 작업(`<KEY>/triage-state.json`, hook이 둔 Jira 원문만 있는 디렉토리는 작업이 아니다)이 없으면 켠 다른 플랫폼 중 KEY 작업이 있는 곳이 정확히 하나일 때 그 플랫폼을 쓴다.

### 11-5. Jira 대응표 (기본 꺼짐)

- site-defaults 전용 `platform.detect.tracker_field: {path, values}`: `path`는 `jira_fields` field_map 경로 표기(비지 않은 문자열), `values`는 `{트래커 값: 켠 플랫폼 이름}`(1개 이상). 플랫폼 선택 규칙이라 사용자 config로는 바꿀 수 없다(K7). 검증은 `platforms.detect_rules()`(`load()`도 부른다, 오류는 종료 코드 2). 실제 필드·값은 TODO(SITE:S28·S32).
- 읽는 곳: `--issue-file`·`--issue-raw` 파일 또는 hook이 둔 `<암묵 work_dir>/<KEY>/issue_raw.json`(`jira_fields.lookup`). 목록 값이 서로 다른 플랫폼으로 대응되거나 없는 값이면 표가 없다. 트래커 값은 출력하지 않는다(질문 문구에는 필드 경로와 플랫폼 라벨만). LLM이 Jira 문장으로 플랫폼을 추측하지 않는다.
