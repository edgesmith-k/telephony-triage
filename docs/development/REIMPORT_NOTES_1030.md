# 재반입 노트 — 10/30 oFono 여러 데몬·플랫폼별 가설 분석·플랫폼 자동 판단

PR #71(`REIMPORT_NOTES_1021.md`·`REIMPORT_NOTES_1028.md`) 뒤 묶음에 함께 들어간다. 절차는 `docs/SITE_INSTALL.md §8`. 설계는 `docs/design/17-platforms.md §9~§11`(K12~K18).

**Android만 켠 설치는 동작·출력이 바뀌지 않는다**(플랫폼 판단을 하지 않고 파일도 열지 않는다). 아래는 oFono를 켤 때(`platform.enabled`에 `ofono`) 해당한다.

## 1. 바뀐 것

| 영역 | 바뀐 것 | 사내에서 할 일 |
|---|---|---|
| 구성요소(데몬) | site-defaults `platform.others.ofono.components.<이름>.{idents, root_key, source_tree, msg_format, split_tag}`. 쓰면 코드 기본(`ofono` 하나)을 통째로 바꾼다. ident는 구성요소끼리 겹치면 안 된다 | 실제 데몬 이름·ident·소스 루트 키를 넣는다(S24·S25·S27). 카테고리 매핑은 oFono 이슈 DB `parser-rules/tags.yaml` |
| 메시지 하위 형식 | `msg_format`(placeholder `file_func`) + `split_tag`(기본 꺼짐, 켜면 태그 `ident/하위`) | 켜면 `tags.yaml`은 `tag_regex`로 맞춘다(정확한 `tag:` 규칙은 안 맞음) |
| 데몬 사이 짝 | `platform.others.ofono.protocols.<이름>.{kind: regex, tags, request, response}`(기본 없음). 짝 키는 `serial`, 한 수집 스트림 안에서만. 짝 없는 요청은 무응답 이벤트 | 요청·응답 줄 형식 확인 뒤 정규식 작성(S26). 대화 키가 필요한지 S26에서 판단. 유닛별 로그와 합친 journal을 같이 넣지 않는다(줄 중복) |
| 소스 루트 | `code_roots validate`가 구성요소 루트마다 필수 디렉토리 확인·버전 추정, 출력 `component_versions`(참고용, 구성요소가 있는 플랫폼만). `ofono` 주 루트는 계속 필수 | oFono 이슈 DB `code_root_keys`에 데몬 루트 키 추가(뼈대에 TODO(SITE:S27)) |
| 파서 백엔드 | `ofono_reference` 0.0.2 | 분석 재사용 캐시가 한 번 바뀐다 |
| 분석 스킬(5-1) | 최상위 `analyzers`는 Android 전용. 다른 플랫폼은 `platforms.<p>.analyzers`(site-defaults 최상위 새 키 + 사용자 config), Android 스킬로 넘어가지 않는다. site-defaults에 `platforms.android`가 있으면 종료 2. guard 규칙 12는 모든 플랫폼의 분석 스킬 `source`를 보호 | oFono 분석 스킬이 있으면 `platforms.ofono.analyzers.<카테고리>`로. 없으면 oFono 이슈는 심층 분석 없이 진행(리포트 "해당 없음") |
| 탐색 분석(5-2) | oFono 작업은 `reference/platforms/ofono/log-guide.md`(placeholder 틀)만 참고 | 실제 로그를 본 뒤 log-guide 내용 보완은 사외 수정 요청으로(사내 값은 반출하지 않음) |
| 플랫폼 자동 판단 | 켠 플랫폼 2개 이상 + 명시 없음(`--platform`·`TT_PLATFORM`·`--answer platform=`): 로그 앞부분 형식으로 고르고 리포트 맨 위에 "플랫폼: …" 줄. 애매하거나 명시와 다르면 lock 전에 한 번 묻는다. 사용자 config `platform`은 기본값이라 분명한 로그 형식이 우선 | S24 형식 확인 뒤 오판이 있으면 사외로 |
| Jira 대응표 | site-defaults `platform.detect.tracker_field {path, values}`(기본 꺼짐) | 플랫폼을 가리키는 Jira 필드가 있으면 설정(S28·S32) |
| 버그 수정 | `--platform`이 기본과 다를 때 Jira 원문이 기본 플랫폼 작업 폴더에 저장돼 이슈를 다시 묻던 것 | — |
| 사내 확인 목록 | `list_site_todos`가 `TODO(SITE:S24·S25)`처럼 묶은 표시를 항목마다 센다 | `s1.todos` 개수가 늘 수 있다(정상) |

## 2. 이슈 DB 뼈대

뼈대 zip 해시가 바뀐다(oFono `code_root_keys` TODO 주석, `tags.yaml` 주석, `docs/analyzer-skills.md` 플랫폼 키 한 줄). 운영 Android 이슈 DB는 `docs/analyzer-skills.md`만 선택적으로 옮긴다.

## 3. 테스트·eval

- `python3 -m pytest -q tests`. 판단 기준은 1021·1028 노트와 같다.
- eval: 새 eval **73**(oFono 탐색 자료)·**74**(로그가 섞여 플랫폼 질문), **63**에 단언 1개 추가 — 정의만 넣었고 사외에서도 실행하지 않았다(사용자 결정). `explore.md`가 바뀌어 **46·47**도 재측정 대상. 사내 대상 eval 11개와 함께 돌릴지는 사용자가 정한다.

## 4. 반입 뒤 후보 (P2)

데몬 사이 짝의 D-Bus 멤버 이름(`ril.yaml` 요청 이름 정규식 한계), site-defaults ↔ 이슈 DB 교차 검사, 감지가 비기본 플랫폼을 고르는 eval, `jira_bridge`의 암묵 플랫폼 로직 중복, site `platforms.<오타>` 경고, 사용자 config 없을 때 guard 규칙 12, 한 파일이 두 형식에 맞을 때 질문 문구.

10/31 재리뷰에서 더한 것:
- 로그 형식으로 고른 플랫폼에 사용자 프로필(`platforms.<p>.issue_db`)이 없으면 check-key(`이슈 DB가 아닙니다: .`)나 `platform-mismatch`로 늦게 멈춘다(lock은 남지 않음). 고른 플랫폼과 `config.py init --platform <p>`·`--platform` 안내를 lock 전에 내기.
- `job_status.py`는 `--platform` 없이 다른 플랫폼 work_dir에 고른 작업을 찾지 못한다(`release`·`explore`만 `_find_job`).
- 켠 플랫폼 2개 이상에서 키 형식이 틀리면 Driver가 키를 거절하기 전에 플랫폼·로그 질문을 먼저 낼 수 있다.
- 판별에서 `.zip`은 모두 Android bugreport로 본다(oFono 로그 zip은 Android로 고름). 판별 앞의 Android `looks_like_bugreport`는 줄 길이 상한 없이 5줄을 읽는다(개행 없는 큰 파일, Driver의 같은 호출도 기존부터 그렇다).
- Android만 켠 설치에서도 guard 규칙 12가 site·사용자 두 층의 같은 카테고리 `source`를 모두 보호한다(전에는 병합 값만 — 더 안전한 쪽 변화, 머리말 "바뀌지 않는다"의 예외).
- `site_checks` `s4a.analyzers`는 기본 플랫폼이 oFono여도 최상위(Android) `analyzers.data`만 본다.
- Jira 원문 옮기기(`Driver.adopt_raw`)는 다른 플랫폼 work_dir에서 그 플랫폼 lock 없이 옮긴다(같은 KEY를 두 플랫폼에서 동시에 돌릴 때만 문제).
- 플랫폼을 바로잡기 전 작업(로그 형식으로 고른 뒤 질문에서 멈춘 작업)은 그 플랫폼에 `pending`과 세션 lock을 남긴다(해제·만료 전까지 `job_status`에 대기로 보이고 그 플랫폼의 다른 KEY는 lock 질문). `triage.py release`는 lock(`owner`)만 풀고 `pending`은 남겨 이어 하는 작업으로 계속 세어진다 — 버린 작업을 정리하는 방법과 안내가 필요하다.
- `docs/design/07-workflow.md` Step 2 플랫폼 줄의 괄호 "(스킬은 사용자가 플랫폼을 말했을 때만 붙인다)"가 같은 줄의 "결과에 `platform`이 있으면 이후 호출에 `--platform`을 붙인다"·SKILL.md 31행과 어긋난다("말했거나 결과에 `platform`이 있을 때"로).
- 답으로 정한 작업이 지정 플랫폼을 대신할 때 노트는 "이어 하는 작업의 플랫폼(X)으로 계속"뿐이고 `needs_input` 출력에는 노트가 없다 — "(지정 E 대신 앞서 답한 X)"처럼 지정 플랫폼을 밝히기.
- 켠 플랫폼이 3개 이상이면 세 번째 플랫폼을 답한 뒤 스킬이 옛 `--platform`을 계속 붙일 때 D2를 다시 묻는다(`resume in (fmt, chosen)`). lock 전 플랫폼·로그 질문을 낸 실행에 같이 준 다른 `--answer`는 저장되지 않아, 스킬이 다음 호출에서 빼면 Driver가 한 번 더 묻는다.
- 끝난 작업의 `platform_answer`는 세지 않는다(`pending`이 있을 때만): 지정과 다른 형식으로 답해 끝낸 뒤 분석 전용 → 기록 재실행, `--refresh`, `--more-logs`(옛 `--platform`을 계속 붙일 때 포함)에서 D2를 다시 묻는다 — 17-platforms K18 요약의 "다시 묻지 않음"보다 좁다. 형식 판별이 사내 로그와 어긋나는 동안(S24 전) 자주 보일 수 있다. `--more-logs`의 D2 질문은 이전 로그가 다른 플랫폼에만 있어도 지정 플랫폼을 선택지로 내고, 고르면 lock을 잡은 뒤 `이전 분석 로그가 없다`(종료 2)로 끝나며 `<work_dir>/<KEY>/{trace.jsonl, triage-state.json}`이 남아 `--platform` 없는 `release`·`explore`가 그 플랫폼에 머문다(이전 로그 없는 플랫폼의 `--more-logs` 실패 자체는 기존부터).
- 저장된 플랫폼 답은 그 질문(`pending.asked_at`, 벽시계 초)이 그 KEY의 가장 늦은 활동일 때만 쓴다. 같은 초면 한 번 더 묻고, 시계가 거꾸로 가거나 미래 시각이 남으면 시계가 따라잡을 때까지 답을 쓰지 않는다(다시 묻는다). 다른 플랫폼으로 바꾼 실행이 질문·완료 전에 실패하면(시각을 남기지 않음) 옛 답이 이길 수 있다(노트·출력 `platform`에는 보인다).
- 저장된 답은 그때의 로그·지정과 묶이지 않는다(`platform_answer`는 이름만): 질문에서 멈춘 동안 다른 형식의 로그로 다시 부르면 답한 플랫폼으로 계속하고, 답(=로그 형식)과 다른 새 `--platform`(앞선 출력에 `platform`이 없어 옛 값을 이어 붙인 것일 수 없는 경우)도 묻지 않고 덮는다. `{platform, fmt, explicit}`을 남겨 그때와 같을 때만 쓰기.
- 답을 쓰지 않게 된 뒤에도 답 없는 옛 `pending` 작업은 이어 하는 작업 표 하나로 남는다(다른 플랫폼에 더 늦은 활동이 있어도) — 섞인 로그·명시 없음이면 그 옛 작업으로 조용히 계속한다. 가장 늦은 활동 거르기를 답 없는 작업에도 적용하기.
- 켠 플랫폼 2개 이상에서 `--logs` 경로가 없으면 판정하지 않고 Driver로 넘어가, 종료 2 전에 그 플랫폼 work_dir에 JOB(`trace.jsonl`·`triage-state.json`·Jira 추출 파일)이 생긴다(Jira 추출이 로그 확인보다 먼저). pick에서 lock 전에 `로그 파일이 없습니다`로 끝내기.
- 문서: `triage.py` 머리말·`contracts.md`의 "명시 없이 로그가 없으면 lock 전 logs 질문"에 "이어 하는 작업도 없으면"이 빠졌다(코드·17 §11-3은 있음). "시각 없는 작업은 막지 않는다"는 시각 없는 답이 다른 플랫폼의 시각 있는 작업에 막히는 경우를 말하지 않는다. `driver.py` `open_job`의 "아래 lock()이 다시 남긴다" 주석(실제로는 그 뒤 `prepare`).

## 5. oFono 사내 트랙 O-1~O-4 (10/31)

- `site_step.py`에 Android S 단계와 따로 가는 oFono 트랙을 더했다(`15-local-draft.md §15.5` oFono 트랙 표). **S-3 완료 뒤** "oFono 설정 시작" → `python3 tools/site_step.py ofono`. `SITE_PROFILE.md` 진행 상태에 `- oFono 단계: O-n`·`- oFono 완료: …` 두 줄이 생기고(§14.3), 인자 없는 실행은 Android 단계에 안내 한 줄만 붙인다. `check O-n`·`propose O-n`·`--done O-n`.
- O-1 로그·형식(S24·S29), O-2 설정(S25~S27), O-3 oFono 이슈 DB(S28, 카테고리마다 실제 fixture 유형 3개 이상 — 쓰지 않을 뼈대 카테고리는 지운다), O-4 사용자·시험(실제 oFono 이슈 5건 이상, 플랫폼 오판 0). `docs/site/steps.yaml` 새 입력 `ofono_log_dir`·`android_log_dir`(선택)·`ofono_db`·`ofono_db_repo`.
- oFono 트랙을 시작하지 않으면 `site_step.py` 출력·기록은 이전과 같다.
- 반입 뒤 후보(P2): `--done S-n` 출력에는 oFono 안내 줄이 없다(인자 없는 실행만). `o1.masked`의 `mask_pii`가 oFono DB `allow_patterns`를 보지 않는다. `android_log_dir`의 로그 아닌 파일(notes 등)이 `o1.sniff` 실패가 된다. `ofono_log_dir`를 파일 링크까지 따라가 크기 상한 없이 점검마다 다시 읽는다. `o4.runs`는 점검하는 PC의 work_dir만 센다. `o4.report`·`s7.pilot` 면제 줄이 다시 보고 줄로 잡힐 수 있다(`s7.pilot` 기존).
