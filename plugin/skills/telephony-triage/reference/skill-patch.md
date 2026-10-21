# 스킬 제안 patch (analyze Step 7)

고른 `[스킬]` 줄은 담당자용 patch로만 남긴다. 계획·PR·Jira 코멘트에 넣지 않고 분석 스킬 디렉토리 안은 쓰지 않는다(Write·Edit·Bash).
- `SK` = 5-1 Skill 결과의 `Base directory for this skill:`. 줄이 가리키는 `SK/<rel>`(예 `references/DATA-001.md`)을 읽고 제안을 반영한 사본을 `JOB/skill-suggestions/<이름>/<rel>`에 쓴다(`<이름>` = `analyzer.skill`, `[A-Za-z0-9._-]` 밖은 `-`). 경로는 따옴표로 감싼다.
- `<P>` = `JOB/skill-suggestions/<이름>.patch` 절대 경로, 명령마다 글자 그대로 쓴다(셸 변수는 호출 사이에 안 남는다). 명령마다 종료 코드를 본다(`&&`로 잇지 않는다):
  1. `diff -u --label a/<rel> --label b/<rel> "SK/<rel>" "<사본>" > "<P>"` — 종료 1이 정상(2는 실패). 파일 여럿이면 둘째부터 `>>`, 없는 파일은 `/dev/null`·`--label /dev/null`.
  2. `S/mask_pii.py "<P>" --in-place` — 0이 아니면 실패.
  3. `(cd "SK" && GIT_CEILING_DIRECTORIES="$(dirname "$PWD")" git apply --check "<P>")` — 마스킹이 문맥 줄을 바꾸면 여기서 실패한다.
- 셋 다 통과하면 이 줄을 글자 그대로 보이고 그 아래에 `git apply --numstat "<P>"`의 파일별 `+N −M`을 보인다:
  `스킬 제안 patch(적용 안 함, 마스킹됨): <patch 경로> — 분석 스킬 담당자에게 전달, 담당자가 검토 후 스킬 소스에서 git apply`
- 하나라도 실패하거나 `SK`를 모르거나 `<rel>`이 `SK` 밖(절대 경로·`..`)·읽기 실패면 짐작하지 않는다: 위 줄 없이 담당자 메모로 보이고 사유를 말한다(patch는 지운다).
- release·discard 뒤에도 남는다(`db_pr cleanup --older-than`이 폴더째 지울 때까지).
