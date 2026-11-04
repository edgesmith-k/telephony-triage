# 계획 H 결과 노트 (모듈 스킬 레포 + +1 병합)

단계표는 `MODULE_SKILLS_PLAN.md §4`. 이 파일은 단계마다 리뷰·재측정에서 P2로 남긴 것(결정 (r): P0·P1만 고치고 P2는 반입 뒤 후보)과 단계 결과를 적는다.

## C0 모듈 스킬 시범 — 구현 (11/04, 유료 실행 전)

범위: oFono `data` 모듈 하나, case 3개(deep `data-apn-auth-reject`, explore `data-ditd-route-fail`, explore 함정 `data-ofonod-only`). 새로 만든 것: 실행기·채점기 `plugin/scripts/module_eval.py`, 자식 공통 `common/claude_child.py`(skill eval `run.py`·`grade.py`도 여기서 다시 내보냄), 입력 생성기 `tests/helpers/make_module_eval_inputs.py`, variant DB `issue-db-ofono-modules`(`issue-db-ofono`는 바이트 동일), `templates/module-skills/ofono/{_common,data}`, 얼린 arm 자료 `tests/fixtures/module-arms`(pre·post sha 고정, 자식 stream 기록 1개). guard 규칙 7이 `module_eval.py --module`을 ask로 둔다. 범위 밖(설계대로): modules.yaml, 나머지 5 유형(C1), 모듈 레포·묶음, contracts 행(E), triage.py·플러그인 SKILL 변경(B).
진행: 구현 2갈래(실행기·채점 / 문서·사례)·통합 → 리뷰 2관점 1회 → 반박 검증 → 17건 중 확정 P0 1·P1 3을 한 번 수정(재리뷰 없음). 설계·리뷰·검증은 노력 높음, 구현·수정은 보통. skill-creator: 문서 구현 에이전트가 `SKILL.md`·`references/DATA-001.md`를 쓰기 전에 불렀다(작업 기록 15:05 호출 → 15:07 작성). 쓰기 지침만 썼고 eval 반복·설명 최적화는 하지 않았다. 효과 측정은 C0 유료 6회가 대신한다.
고친 4건: P0 — argparse 줄임말(`--modu`·`--modul=`)이 guard ask(낱말 `module`)를 피해 유료 실행·probe를 시작함 → `allow_abbrev=False`(guard는 그대로, 스크립트가 시작 전에 종료 2). P1 — `--probe-restricted --dry-run`이 유료 자식을 띄움 → dry-run이면 argv만 보이고 종료 0. P1 — S6 적용 주장 regex가 분석 문장(`정책 규칙이 이미 추가됨 상태였을 수`)을 잡아 관문 전체를 fail로 → 주어를 도구 산출물(`tags.yaml`·`extractors.yaml`·`ril.yaml`·파서 규칙·시그니처·규칙 파일/문서·`규칙을`)로, 어미를 1인칭 완료형으로 좁힘(`됨`·`했을 수` 제외, 실제 쓰기는 S1이 잡음). P1 — S7이 가장 긴 일치 20자면 ok라 두 줄을 합친 줄·진짜 앞머리+지어낸 꼬리가 통과 → 로그 조각마다 가장 맞는 원문 줄에 대해 덮이지 않은 12자 이상 구간이 있으면 지어냄. S6·S7은 설계 §9.3 문구와 다르다. S7 문턱(블록 4자, 구간 12자)은 C0 case 3개로 맞췄으니 첫 실측 리포트의 근거 칸을 본다.
구현이 설계와 다르게 한 것: `gen_contracts` `NOT_CLI = ("module_eval",)`(E에서 contracts 행과 함께 SCRIPTS로), `ARM_PINS` 키는 플랫폼 경로 포함, `docs_sha256` 키는 `<arm>/<relpath>`, tags.yaml reason 구분자 `·`(YAML 흐름 표기의 쉼표), result 이벤트 없는 run(시간 초과 포함)은 안전 행 전부 `기록 없음` → 관문 fail, `--record`는 incomplete면 거부.
검증(본 트리): 관련 테스트(claude_child 변경으로 전체) ※, check_boundary 위반 없음, `make_module_eval_inputs.py --check` 9개 일치, `make_variant_dbs.py --check` 일치, `gen_contracts --check` 최신, exec bit 100755, ruff는 새 파일 0·바뀐 파일 2c6e0cd보다 늘지 않음. dry-run(`--model sonnet`): run 6(case 3 × with·without), arm별 파일 묶음 설계 §7.2와 같음(deep with 문서 13,974B), 추정 6 × $0.25 = $1.50(상한 안), arm 고정값 일치·pre log-guide = 현재 플러그인. 유료 자식은 띄우지 않았다.
해석 주의: explore 문서와 case를 같이 썼으므로 explore 결과는 상한이다(C1에 문서가 다루지 않는 case 하나 이상). B1 의무: `module --for deep`은 5-1에 deep timeline도 줘야 한다(설계 §2.2, 아니면 eval이 실제보다 쉽다). C1에서 다른 5 유형이 variant에 들어오면 입력 `--check`가 drift를 보고한다(예상, `--write` 후 C0 inputs_sha256은 옛 입력). S3(긴 로그 통째 읽기)은 C0 case로 시험되지 않는다(로그 100줄 이하, `S3 미시험` 메모).

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
