# 17. 플랫폼 분리 (Android 기본 / oFono / 이후 추가)

> 10/11 사용자 요청. oFono는 Android와 동작·로그·원인·해결책이 달라 **플랫폼마다 이슈 DB를 따로** 둔다. 플랫폼은 계속 더할 수 있어야 한다(이름을 하드코딩하지 않는다). 표·정의가 다르면 `contracts.md`가 맞다. 사내 고유 구성요소 이름은 쓰지 않는다(placeholder `daemon-a`·`daemon-b`, `14-site.md` S24~S29).

android만 쓰는 설치(site-defaults에 `platform.enabled`·`others`·`parser.by_platform`이 없고 사용자 config에 `platform`·`platforms`가 없음)는 경로·lock 위치·lock JSON·`config.py show/doctor`·guard 판정(규칙 10 제외)·pre-push·`analysis.json`·`report.md`·이벤트·`db_regress`·골든이 모두 이전과 바이트 단위로 같다. 이슈 DB에 `platform`이 없으면 android다. 예외: guard 규칙 10과 Jira 게시 원문 줄 검사는 **설치된 모든 플랫폼** 형식(`known()` 합집합, §5)을 원문으로 보므로 android 단독 설치도 journald·BSD syslog 모양 줄을 거부한다(더 엄격한 쪽).

## 1. 계약 (`plugin/scripts/platforms/`)

```
platforms/
  __init__.py   # 레지스트리: known·get·label·enabled·default_name·load·backend_name·select·원문 줄 판별. 플랫폼 이름을 모른다
  base.py       # 계약 타입: PlatformSpec·LogFormat·PairProtocol·CaptureSpec·SourceTree·PhoneIdRules·VendorRules·LogLine·FileStats·PlatformConfigError
  session.py    # 사용자 세션 선택(--platform)과 사용자 config 프로필을 잇는 유일한 곳(resolve·resolve_lenient·add_arg)
  android/      # SPEC + logcat·ril·bugreport·backend
  ofono/        # SPEC 뼈대 + journal(형식 가정 placeholder)·backend
common/logtime.py                       # 플랫폼 무관 시각 함수·시계 이상 기준·coverage
parser_backends/<p>_reference/          # 그 플랫폼 BACKEND 재수출 (android는 reference/)
```

- 플랫폼 하나 = `platforms/<name>/__init__.py`의 `SPEC: PlatformSpec`. frozen dataclass와 Callable 필드다(상수와 함수가 섞이고 site-defaults로 덮어쓴 복사본을 만들어야 해서 ABC를 쓰지 않는다).
- `PlatformSpec`: `name`, `label`(출력 라벨 "Android"/"oFono"), `log: LogFormat`, `phone: PhoneIdRules`(빈 규칙 허용), `protocols: tuple[PairProtocol, ...]`(0개 이상), `source_tree: SourceTree`, `primary_root`(주 소스 루트 키, android `aosp`), `default_root_keys`(DB `code_root_keys`가 없을 때), `capture: CaptureSpec | None`(bugreport류 묶음 입력), `default_backend`(android `reference`, ofono `ofono_reference`), `block_keys`(site-defaults에서 받는 상수 키).
- `LogFormat`: `read_file(path, file_index, tz, year) -> (list[LogLine], FileStats)`, `raw_line(줄)`(줄 맨 앞이 원문 로그 줄인가, guard 규칙 10), `find_raw(문장)`(문장 안에 원문 줄이 끼었나, Jira 게시 검사), `epoch_break(LogLine)`(재부팅 등 불연속).
- `PairProtocol`: `name`·`default_tags`·`annotate`·`pair`. 주석은 이벤트 `ril` 칸을 같이 쓰고 `name != "ril"`이면 `proto: <name>`을 단다. `pair`는 **자기 주석만** 다룬다(다른 프로토콜 주석은 짝·pid 분할에 쓰지 않는다). 태그 덮어쓰기는 ril이면 `<블록>.ril.tags`, 그 밖은 `<블록>.protocols.<name>.tags`.
- `CaptureSpec`: `looks_like`·`extract`·`error`·`default_rules`·`sniff_line`(guard 머리 판별), `block_key`·`configure`(site-defaults 블록 검증·덮어쓰기, 레지스트리는 규칙 모양을 모른다).
- 파서 백엔드(`parser_backends/base.py`): 클래스 속성 `platform`(기본 `"android"`, 기존 site 백엔드 호환), `log_format()`(기본 `SPEC.log`). 백엔드 이름 공간은 `16-existing-assets.md §16.3`.

### 1-1. 레지스트리 API

- 이름 `^[a-z][a-z0-9_]*$`, `base`·`_`로 시작하는 것 제외. `get(name)`은 `importlib.import_module("platforms.<name>")` → `SPEC` 타입과 `SPEC.name == name` 확인 → 프로세스 안 캐시. 오류는 `PlatformConfigError`(호출자 종료 코드 2). 플랫폼 모듈 안의 하위 의존성 누락은 그대로 올린다.
- `known()`: 설치된 플랫폼 패키지(메시지 "지원 플랫폼: android, ofono (…)").
- `enabled(defaults)`: site `platform.enabled`(목록·중복 없음·기본 이름 포함·모두 설치됨), 없으면 `[platform.name]`.
- `load(defaults, name=None, require_enabled=True)`: 기본 플랫폼은 `platform:` 블록, 그 밖은 `platform.others.<name>` 블록을 `SPEC.block_keys`로 검증해 `PlatformProfile`(`spec`·`protocol_tags` 포함)을 준다. `platform.others`는 요청과 상관없이 모두 검증한다. `require_enabled=False`는 DB에 고정된 도구용(K6).
- `backend_name(defaults, name)`: 기본 플랫폼이면 `parser.backend`, 그 밖은 `parser.by_platform.<name>`, 없으면 `SPEC.default_backend`.
- `select(defaults, cli, user)`: K3 순서, `enabled` 관문.
- `known_raw_line_finders()`: 설치된 **모든** 플랫폼의 원문 줄 판별(guard 규칙 10·Jira 게시 검사, 설정과 무관, 플랫폼마다 따로 불러와 하나가 깨져도 나머지는 쓴다). `raw_line_finders(defaults)`: 켠 플랫폼만.

### 1-2. 계층 규칙 (테스트로 강제)

- `common/`은 `platforms`를 import하지 않는다. 핵심(매처·`db_*`·guard·`config.py` 등)은 레지스트리 경유로만 플랫폼을 쓴다(`platforms.android` 직접 import 없음).
- `platforms/<a>`는 `platforms/<b>`를 import하지 않는다(공용은 `platforms.base`와 레지스트리 밖 모듈: `common.logtime`·`common.events`, 백엔드 `backend.py`는 `parser_backends.base`도). 플랫폼 코드는 핵심 스크립트(`parse_logcat`·`triage`·`config`·`code_roots`·`db_*`)와 `parser_backends.site`를 import하지 않는다.
- `platforms/<p>/__init__.py`는 표준 라이브러리 + 같은 패키지 하위 모듈 + `platforms.base`·`common.logtime`·`common.events`만(guard가 규칙 10에서 불러오므로 가벼워야 한다. `backend.py`는 `__init__`이 불러오지 않는다). 검사는 `tests/test_platforms.py`.

## 2. 선택·경로·프로필 규칙

| 층 | 키 | 의미 |
|---|---|---|
| site-defaults | `platform.name`, `platform.enabled`, `platform.others.<p>`, `parser.by_platform.<p>` | 팀 기본, 켤 수 있는 플랫폼, 그 밖 플랫폼의 상수·백엔드 (`02-config.md`) |
| 사용자 config | `platform` | 개인 기본 선택(`enabled` 안의 이름) |
| 사용자 config | `platforms.<p>.{issue_db, work_dir, log_dir, code_profiles, recent_code_roots}` | 경로 프로필(`PROFILE_KEYS`). 최상위 같은 키 = android 프로필 |
| CLI | `--platform <p>` | `triage.py`·`config.py`·`db_pr.py`·`db_verify.py`·`issue_post.py`·`code_roots.py`·`db_add.py`·`db_search.py`·`db_review.py`·`job_status.py`·`usage_stats.py`(그 밖 스크립트 — `mask_pii`·`parse_logcat` 등 — 은 받지 않는다) |
| env | `TT_PLATFORM` | triage → 하위 스크립트(사람이 쓰지 않는다) |

- 선택 순서: `--platform` > `TT_PLATFORM` > 사용자 config `platform` > site `platform.name` > `android`. `enabled` 관문은 **사용자 세션 흐름만** 적용한다. DB에 고정된 도구(`db_regress`·`db_lint`·`parse_logcat --rules`)는 DB 선언 플랫폼(설치돼 있으면 허용).
- 프로필: android가 아닌 플랫폼의 cfg는 공통 키에 `platforms.<p>`를 얹은 것이고 android 값을 **물려받지 않는다**(ofono 프로필이 실수로 android clone을 가리킬 수 없다). 기본 `work_dir` `<home>/work-<p>`, 보류 피드백 `<home>/pending-feedback-<p>`. 최상위 프로필 없는 config(따로 설치)도 된다.
- 경로 규칙(`userconfig.path_problems`): `work_dir`·`issue_db.path`는 비어 있지 않은 절대 경로(`~` 허용), `work_dir`은 clone 밖, 프로필끼리 `work_dir`·clone·원격 겹침 금지. `platforms.<p>`의 프로필 밖 키(예: `source_tree`)는 거부(RF-4). `config.py show`·`set`·`doctor`는 이런 문제가 있어도 동작하고(set 경고, doctor `platform` 행 fail), 그 밖 스크립트는 종료 코드 2.
- `--db`가 없을 때의 대체 경로(사용자 config `issue_db.path`, `common/dbpath`의 ③)도 **선택 플랫폼** 프로필의 값이다(`db_add`·`db_search`·`db_review`·`config`·`code_roots`). 이 스크립트들도 이슈 DB 선언과 선택 플랫폼을 대조한다(`platform-mismatch`). 단 `db_add`의 `apply`·`drift`·`renumber`·`check-ids`는 `db_pr publish`·`db_verify`·stage 검사가 그 DB에 대고 부르는 **DB 고정** 하위 명령이라 DB 선언을 따르고, `--platform`·`TT_PLATFORM`이 있을 때만 대조한다(사용자 config 없이 도는 비기본 DB 검사가 막히지 않게). 사용자 흐름인 `similar`는 항상 대조한다.
- 쓰기: `config.py set --platform <p> <키>`·`code_roots remember`는 `profile_key(p, key)`(android면 그 키, 그 밖 `platforms.<p>.<키>`)에 쓴다. `config.py init --platform <p>`는 그 프로필만 더한다(트래커(`tracker.*`)·gh 설정은 공유). 이미 있으면 `--force`로 그 프로필에서 입력한 항목만 갱신한다(없는 키·Enter는 유지, 빈 값·`-`·팀 기본값과 같은 답은 지움 — android `--force`와 같은 규칙). android도 최상위 프로필이 없는 config(따로 설치)면 `--force` 없이 그 프로필만 더한다. `init`의 플랫폼은 `--platform` > `TT_PLATFORM` > site(사용자 config `platform`은 보지 않는다 — `init --force`가 다른 플랫폼 프로필을 덮지 않게)이고, 새 config에 경로 규칙 문제가 있으면 저장하지 않는다(종료 코드 2).
- 출력: `analysis.json`·lock 기록·`triage-state.json`의 `platform`은 android가 아닐 때만. 라벨은 `SPEC.label`. 같은 작업 키를 다른 플랫폼으로 다시 실행하면 종료 코드 2.

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
4. 짝 규칙이 있으면 `SPEC.protocols`(`PairProtocol`), 슬롯 표기가 있으면 `SPEC.phone`, 묶음 입력이 있으면 `SPEC.capture`.
5. site-defaults: `platform.enabled`에 이름 추가, 상수는 `platform.others.<p>`(그 플랫폼 `block_keys`만), 기본 아닌 백엔드면 `parser.by_platform.<p>`. `site-defaults.example.yaml`에 주석 예시.
6. 이슈 DB: 새 레포. `issue-db.config.yaml`에 `platform: <p>`, `platform_versions_supported`, `parser_backend.name: <p>_reference`, `code_root_keys`(그 플랫폼 루트), 그 플랫폼 `categories`·`parser-rules`. 뼈대는 `tools/make_db_skeleton.py <out> --platform <p>`(위 키를 그 플랫폼 기본값으로 넣고 parser-rules는 스키마 최소 placeholder 항목, 카테고리는 일반 6종 시작점)로 만든 뒤 메인테이너가 채운다. pre-push는 플랫폼 분기가 있는 hook(샘플 DB `.githooks/pre-push`)을 쓴다.
7. 사용자: `/telephony-triage:setup`에서 그 플랫폼을 고르거나 `config.py init --platform <p>` → `platforms.<p>.issue_db.path` 등.
8. 테스트: 합성 로그 fixture(손으로 쓴 것, README에 "합성·형식 가정·placeholder"), 변형 DB(`tests/helpers/make_variant_dbs.py`), 전환 검증(같은 명령이 DB에 따라 백엔드·태그·카테고리·이벤트·매칭이 바뀌고, 섞으면 `platform-mismatch`), 계층 테스트, `tools/check_boundary.py --mode external`. android 바이트 동일성(골든·`db_regress` 샘플·fixture)이 그대로인지 본다.
9. 문서: 이 문서 §7에 결정, `14-site.md`에 TODO(SITE) 행, 사용자용 로그 수집 체크리스트(본보기 `docs/development/OFONO_LOG_COLLECTION.md`).

## 7. 결정 기록

| # | 결정 | 이유 |
|---|---|---|
| K1 | 레지스트리 = `platforms/<name>/__init__.py`의 `SPEC` 하나, 이름으로 동적 import. "등록"은 site `platform.enabled`. `SUPPORTED` 튜플은 없앴다 | `parser_backends.load`와 같은 방식. 추가 = 디렉토리 하나 + `enabled` |
| K2 | 사용자 config 최상위 경로 키는 항상 android 프로필, 그 밖은 `platforms.<name>`(기본 `work_dir` `<home>/work-<name>`) | 기존 config·경로 그대로. 두 벌 설치도 같은 config를 충돌 없이 쓴다 |
| K3 | 선택 순서 `--platform` > `TT_PLATFORM` > 사용자 `platform` > site `platform.name` > android. `enabled` 관문은 사용자 세션 흐름만 | triage가 하위 스크립트에 env로 넘긴다(기존 `TT_LOCK_OWNER` 방식) |
| K4 | **lock은 플랫폼(이슈 DB)별**(사용자 결정 10/11, 설계 초안의 "사용자당 하나"를 바꿈). lock·`session.guard`는 각 플랫폼 `work_dir`, 기록 `platform`은 android 아닐 때만 | android·oFono 작업을 동시에 할 수 있다. 원칙 문구를 "사용자·이슈 DB(플랫폼)별 한 번에 한 작업"으로 고쳤다 |
| K5 | 이슈 DB `platform` 선언, 세션 선택과 다르면 거부(`platform-mismatch`) | **동작·원인·해결책이 플랫폼마다 달라** 다른 DB에 대고 매칭하는 것은 의미가 없다. 시그니처에 platform 표시를 다는 "합치기" 안은 쓰지 않는다(사용자 결정) |
| K6 | DB에 고정된 도구는 DB 선언 플랫폼, 사용자 세션 흐름은 선택과 DB 선언을 대조 | oFono DB의 CI는 사용자 config 없이 돈다. `parse_logcat`은 사용자 config를 읽지 않는다 |
| K7 | **RF-4 유지**: 플랫폼 상수(정규식·디렉토리·태그·섹션 헤더)는 site-defaults에서만. 사용자 config는 이름 선택과 경로 프로필만, `platforms.<p>`의 그 밖 키는 거부 | 상수는 결정적 파서 출력과 이슈 DB 회귀 기준을 정한다. 사람마다 다르면 같은 fixture가 다르게 판정된다. 이번 요구는 "어느 상수 묶음을 쓸지 고르기"다 |
| K8 | 출력 `platform` 키는 android 아닐 때만, 라벨은 `SPEC.label` | android 바이트 불변, 기존 "있을 때만" 키 관례 |
| K9 | (해소, 트래커 범용화) 스키마 필드 `android_version(s)`·`code_profiles[].android_version`·`field_map.android_version`을 `platform_version(s)`로 개명했다. DB 키는 `platform_versions_supported` 하나(옛 키는 읽지 않고 `db_lint` config 오류) | 처음에는 이슈 DB 마이그레이션이 필요해 미뤘다. 배포된 이슈 DB가 없어 원칙 (d)로 v1을 직접 고쳤다(`18-trackers.md` T4·T10). 옛 사용자 config 키는 감지만 한다(T5) |
| K10 | 짝 규칙은 `SPEC.protocols`(0개 이상), 비-ril은 `proto` 주석, `pair`는 자기 주석만. `ril.yaml` 요청 이름은 DB 전체에서 유일 | oFono는 RIL 계층과 D-Bus 등 둘 이상일 수 있다 |
| K11 | 카테고리는 플랫폼 DB `categories`, 출처 → 카테고리는 플랫폼 DB `tags.yaml` | 코드에 카테고리 가정 없음(조사 결과) |

그 밖: `compiled.environment(defaults, platform)`은 `parser.backend`가 없으면 `SPEC.default_backend`를 쓴다(그런 설치만 분석 재사용 해시가 한 번 바뀐다). 두 벌 설치는 커맨드 이름 공간과 hook이 두 번 걸리므로 권장은 한 벌 설치 + `enabled` 2개다.

## 8. 미룬 것

- **oFono 실제 파서 규칙·이슈 DB 내용**: 사내 로그를 받은 뒤 사내 모드에서(S24~S29, `docs/development/OFONO_LOG_COLLECTION.md`). 지금 `platforms/ofono`는 형식 가정(journald `short-iso-precise`·BSD syslog) placeholder이고 합성 로그로 전환만 검증한다. 실제 로그·형식은 사외로 가져오지 않는다.
- **`external_parsers`는 기본 플랫폼만** 쓴다(그 밖 플랫폼은 `{}`). 비기본 플랫폼 어댑터는 필요할 때 `platform.others`·DB `external_parsers`와 함께 정한다.
- **트래커 설정 플랫폼별 덮어쓰기**: `tracker.*`(트래커 종류·`field_map` 등)는 플랫폼끼리 공유한다. oFono 트래커나 프로젝트가 다르면 `platforms.<p>.tracker` 덮어쓰기(`PROFILE_KEYS` 확장)를 다음 작업으로(S28·S32, `18-trackers.md` T9).
- parser-rules 스키마가 `ril.yaml` 항목 1개 이상을 요구해 oFono DB에 placeholder 항목이 필요하다 — 실제 짝 규칙이 정해질 때 프로토콜별 파일 체계와 함께 스키마를 고친다.
