# 시작하기 (10분)

> 처음 오는 사람이 10분 안에 첫 PR까지 가는 것이 목표다 (`06-collaboration.md §6.9`).

## 1. 플러그인 설치

Claude Code에 telephony-triage 플러그인을 설치한다. 설치 방법은 플러그인 레포의 README를 본다.

## 2. `/telephony-triage:setup`

커맨드가 순서대로 묻고 설정한다.

- `~/.telephony-triage/config.yaml` 생성 (GHE 아이디, 이슈 DB clone 경로·원격·GHE 호스트, Jira MCP 서버와 읽기 도구, 타임존, 작업 디렉토리)
- 이슈 DB clone이 없으면 `git clone` 제안
- 이슈 DB 레포에 pre-commit hook 설치 (`git config core.hooksPath .githooks`)
- 읽기 스냅샷 생성
- `gh auth status` 확인 — **로그인이 없으면 읽기 전용이다.** 아래 3번 연습은 그대로 할 수 있다.

## 3. 연습 (`--dry-run`)

```
/telephony-triage:analyze <JIRA-KEY> <logcat 경로> --dry-run
```

- 확인 화면까지 진행하고 임시 worktree를 지운다. **push하지 않고, 이슈 DB clone의 브랜치·파일도 바꾸지 않는다.**
- Jira MCP 없이 연습하려면 `--jira-file <yaml>`로 샘플 Jira 요약을 준다.
- 스스로 해결해서 히스토리만 남기는 흐름도 같이 연습한다:
  `/telephony-triage:record <JIRA-KEY> --dry-run`
- `--dry-run`은 pending 피드백을 만들지 않는다.

## 4. 실제 이슈로 첫 PR

```
/telephony-triage:analyze <JIRA-KEY> <logcat 경로>
```

1. 이슈 DB를 최신으로 맞추고 읽기 스냅샷을 만든다
2. Jira를 읽고(읽기 전용) 로그를 파싱·매칭한다
3. 후보를 보여주고 **분류를 사용자가 확정**한다
4. 필요한 변경(작업 계획)을 만들고 검증한다
5. push 전 확인 화면을 승인하면 브랜치와 PR이 만들어진다

- 새 유형/원인, 시그니처·파서 규칙 추가는 **항상 확인을 받는다.**
- PR은 CODEOWNERS 승인 1명 이상이 필요하다.
- 머지 전에 main이 바뀌었으면 작성자가 `/telephony-triage:sync-pr`를 실행한다.

## 5. 결과 보는 법

| 파일 | 내용 |
|---|---|
| `README.md` | 카테고리 > 유형 > 원인 인덱스. 해결책·수정 상태·Jira 건수 (생성 파일) |
| `<카테고리>/README.md` | 카테고리 상세 (증상 시그니처 요약, 코드 위치, 지원 버전) |
| `STATS.md` | 통계: 최근 건수, Top 원인, 급증, 검증 현황, 시그니처 품질 |
| `<유형 디렉토리>/type.md` | 유형·원인 정의와 사람용 상세 (재현 시나리오, 로그 예시) |

- 해결책 옆 `⚠ 미검증`은 해결책 검증 기록이 없다는 뜻이다.
- 수정 상태 `fixed ✅ <빌드> 검증`은 그 빌드에서 `verify-fix`를 통과했다는 뜻이다.

## 다음 단계

- 규칙은 `CONTRIBUTING.md`, 용어는 `GLOSSARY.md`
- 월간 리뷰(카테고리 오너)는 `docs/review-guide.md`
