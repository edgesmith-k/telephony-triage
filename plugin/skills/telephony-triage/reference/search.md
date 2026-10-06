# search — 이슈 DB 검색 (증상 문장·키워드·Jira 키·ID)

`/telephony-triage:search`와 "비슷한 이슈 있었어? 지라 번호 알려줘"처럼 **과거 이슈만 묻는** 요청의 단일 원본이다
(`03-issue-db.md §5.5`, `09-commands.md` search). **읽기 전용**이라 세션 lock을 잡지 않는다. 로그·Jira 분석이나 분류를 하지 않는다
(`triage.py`·파서·매칭을 부르지 않는다): 묻는 것은 DB에 이미 있는 기록이기 때문이다.

## 1. 검색

사용자의 문장을 **고치지 않고 그대로** 넘긴다. 조사·불용어 정리와 별칭 확장은 스크립트가 한다. 임의로 키워드로 줄이면 맞는 단어를 놓친다.

`S/db_search.py --db SNAP "<문장>" --limit 10 --format markdown` (SNAP = `<work_dir>/_snapshot`, `work_dir`는 `config.py show --keys work_dir`의 값).
스냅샷이 없으면(`sync`를 한 적이 없음) `--db`를 빼고(cwd의 이슈 DB 또는 config의 clone) "최신 main 기준이 아닐 수 있으니 `sync`를 권한다"고 알린다.
문장에 Jira 키나 유형·원인 ID가 있으면 그 키로도 한 번 더 검색한다(정확 일치).

## 2. 결과가 0건일 때

- `terms`가 비었으면(불용어뿐) 어떤 증상인지 되묻는다.
- 아니면 증상 명사 한두 개로 **한 번만** 다시 검색하고, 어떤 단어로 찾았는지 밝힌다. 이 결과를 같은 이슈라고 말하지 않는다.
- 그래도 없으면 "일치 없음"과 다른 검색어(유형 제목·태그·Jira 키)를 제안한다. **이슈 번호를 지어내지 않는다.**

## 3. 보여주기

`--format markdown` 출력을 순서·내용 그대로 보인다(요약·재서술 금지). 다시 순위를 매기거나 키를 지어내지 않는다(`matched`·`score` 순위가 이미 계산돼 있다). 출력이 따르는 규칙은 아래와 같다(`tests/test_db_search.py`가 대조한다).

1. **이슈 번호** 줄 먼저: 원인·유형의 `jira`에서 Jira 키를 중복 없이 모으고 `jira_latest`(가장 최근 날짜)를 붙인다. 키는 결과에 있는 것만 쓴다.
2. 표: 유형 > 원인 | 해결책(`resolution_verification` — 미검증이면 그렇다고) | 수정 상태(`fix.status`, `fixed_in`) | 최근 Jira(`jira_count`건) | 맞은 단어(`matched`).
   질의 단어 일부만 맞으면(`matched`가 `terms`보다 적으면) "부분 일치"로 표시한다. `phrase: true`는 질의 전체가 그대로 들어 있는 결과다.
3. 연관(`related`), 다른 카테고리(`secondary_categories`)가 있으면 함께 보인다.
4. `links[]`가 있으면 `옛 ID → 새 ID`(`merged-into` 병합 / `renumbered` 사후 정리, 커밋·날짜)를 보이고, `current`(병합 체인의 끝)가 있으면 지금 봐야 할 ID를 알린다.
5. `kind`(type-id / cause-id / jira / keyword)를 밝힌다.

이 순위는 검색용이다. 분류를 확정하거나 원인을 단정하는 근거로 쓰지 않는다.

## 4. 분석이 필요하면

로그로 원인을 확인하려는 것이면 직접 하지 말고 `/telephony-triage:analyze <KEY> <로그>`를 안내만 한다.
