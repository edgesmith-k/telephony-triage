# 스킬 제안 patch (analyze Step 7)

고른 `[스킬]` 줄은 patch로만 남기고 반영은 사용자가 직접 판단한다. 계획·PR·Jira 코멘트에 넣지 않고 분석 스킬 디렉토리 안은 쓰지 않는다(Write·Edit·Bash).
1. `SK` = 5-1 Skill 결과의 `Base directory for this skill:`. 줄이 가리키는 `SK/<rel>`(예 `references/DATA-001.md`)을 읽고 제안을 반영한 사본을 Write로 `JOB/skill-suggestions/<이름>/<rel>`에 쓴다(`<이름>` = `analyzer.skill`, `[A-Za-z0-9._-]` 밖은 `-`). 그 폴더엔 사본만 둔다.
2. `S/skill_patch.py <KEY> --skill-dir "SK" --name <analyzer.skill>`를 **한 번** 부른다(`--json` 없이, 플랫폼이 정해졌으면 `--platform <p>`). diff·마스킹·`SK` 임시 사본의 `git apply --check`·줄 수는 스크립트가 한다. 직접 `diff`·`mask_pii`·`git apply`를 하지 않는다.
3. 출력 줄 전부(종료 0: 안내 줄 `스킬 제안 patch(적용 안 함, 마스킹됨): …`과 파일별 `+N −M`, 종료 1: `스킬 제안 patch 없음(직접 반영할 메모): <사유>`)를 다음 질문 전에 바꿔 쓰지 말고 글자 그대로 보인다(hook이 본다). 종료 1이면 제안 줄을 메모로 보이고 이어간다.
- 종료 2면 stderr를 그대로 보이고 제안 줄을 메모로 보인 뒤 이어간다(analyze를 멈추지 않는다).
- `SK`를 모르거나 `SK/<rel>`을 읽지 못하면 스크립트 없이 짐작하지 않는다: 메모로 보이고 사유를 말한다.
- release·discard 뒤에도 남는다(`db_pr cleanup --older-than`이 폴더째 지울 때까지).
