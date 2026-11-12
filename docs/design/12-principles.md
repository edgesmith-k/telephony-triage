# 12. 원칙

> 원본 12장(이전 `CLAUDE.md §12`). 매 세션 지킬 것의 요약은 `CLAUDE.md` "항상 지킬 것". 계약 표·정의는 `contracts.md`에만 있다(여기에 복사하지 않는다).
> 코드·스킬·이슈 DB 동작을 만들거나 바꾸는 Phase·S 단계에서 읽는다. Phase 13 skill-creator 입력이기도 하다 (`10-skill-eval.md`).

- 분류 확정, 새 유형/원인 생성, 시그니처와 파서 규칙 추가·삭제, 수정 상태 변경은 **항상 사용자 확인 후** 진행한다. 파서 규칙 삭제(`remove-parser-rule`)는 초안 검증(R1~R5)의 영향을 보인 뒤에만 한다.
- GitHub push 전에는 **변경 파일, ID 할당, README 미리보기, diff, 검사·검증 결과(실행/건너뜀과 사유), 커밋 메시지를 보여주고 승인받는다** (`07-workflow.md §Step 8`의 5번). 승인 없이는 push하지 않고, 승인 후 파일이 바뀌면 다시 승인받는다.
- 이슈 DB 변경은 **PR로만** main에 들어간다(main 직접 push 금지). 병합에는 **작성자 외 1명의 +1**(그 PR head 커밋에 Approve, 변경 요청 없음)이 필요하고 Claude는 Approve하지 않는다. Claude는 리뷰어를 자동 요청하지 않고 push 뒤 지정할지 묻는다(기본 지정 안 함 — 아무나 +1, 고르면 `db_pr request-review`). 병합은 사용자가 요청할 때 **+1이 있을 때만** `db_pr merge`로 하거나, +1 뒤 사람이 GHE에서 한다(서버 브랜치 보호가 필수 승인 1·up to date를 강제). `db_pr merge`는 +1·publish가 push한 커밋 그대로·PR 검사 통과(검사가 없으면 `ci_mode: local`일 때만)·GHE 병합 가능 상태·그 사이 main 불변일 때만 병합한다. 검증 결과 "승인 필요"·메인테이너 경로 변경 PR은 메인테이너가 리뷰한다. 다른 사람이 문제를 찾으면 그때 새 PR(또는 Revert)로 고친다 (`06-collaboration.md §6.1`).
- 분석 스킬 `[스킬]` 제안은 patch로 남긴다. 스킬 소스(`analyzers.<카테고리>.source`)가 설정돼 있으면 patch(마스킹됨)를 보이고 사용자가 "적용"을 고른 뒤에만 그 워킹 트리에 적용한다(`skill_patch.py --apply` — 커밋·push는 사용자). 설치된 플러그인 캐시의 스킬은 바꾸지 않는다 (`16-existing-assets.md §16.5.1`).
- 도구가 만드는 이슈 DB 변경은 **작업 계획을 최신 main 위에 적용**하는 방식으로만 만들고, 절차는 `db_pr.py`가 한다. 텍스트 rebase로 병합하지 않는다. 계획이 건드리는 대상이 그사이 main에서 바뀌었으면(drift) 자동으로 덮지 않고 사용자에게 묻는다 (`contracts.md §작업 계획`). 예외: 스키마 마이그레이션·새 카테고리·사후 정리는 계획 op로 표현할 수 없으므로 메인테이너가 자기 로컬 브랜치에서 직접 편집한다 (`06-collaboration.md §6.3·6.4·6.10`).
- **사용자의 이슈 DB clone은 브랜치도 파일도 바꾸지 않는다.** 분석은 읽기 스냅샷(`<work_dir>/_snapshot`), 쓰기는 작업 worktree와 도구 브랜치(`tt/*`)를 쓴다. 사용자 clone에는 fetch와 조건부 `pull --ff-only`만 한다. 명시적 예외는 둘이다: 메인테이너가 `migrate/schema-v<N>` 브랜치에서 실행하는 `migrate` 커맨드(그 브랜치의 워킹 트리를 바꾼다), 그리고 사용자가 자기 직접 편집 브랜치에서 직접 실행하는 `db_add renumber`(base·`tt/*`·detached가 아니고 트리가 깨끗할 때만, `06-collaboration.md §6.3`).
- 다른 유형의 fixture에서 새 시그니처가 걸리면(R3·R4) 시그니처를 좁힐지 `also_allowed`로 허용할지 **사용자가 고른다**. 몰래 좁히거나 몰래 허용하지 않는다 (`contracts.md §fixture`).
- 사용자·이슈 DB(플랫폼)별로 **한 번에 한 작업**만 스냅샷을 옮기거나 worktree를 만든다(세션 lock, 플랫폼 `work_dir`마다 하나라 android 작업과 oFono 작업은 동시에 할 수 있다, `17-platforms.md`). 작업이 끝나는 모든 경로에서 lock을 푼다 (`contracts.md §3.2` `db_pr.py` 세부).
- 생성 파일(README, STATS, CHANGELOG)은 `db_build.py`로만 만들고 직접 편집하지 않는다. 캐시는 커밋하지 않는다. 이슈 한 건은 파일 하나다(`issues/<작업 키>.yaml`).
- 머지 전 main이 바뀌었으면 `sync-pr`로 다시 맞춘다 (계획이 있는 PR은 계획 재적용, 직접 편집한 브랜치는 사용자가 재동기화, `06-collaboration.md §6.3`).
- ID는 main에 들어간 뒤에는 바꾸지 않는다. **유일한 예외**는 머지 간격으로 main에 같은 ID가 두 번 들어온 경우의 사후 정리(메인테이너, `06-collaboration.md §6.3`)다. 병합·폐기는 `status`로 처리하고 삭제하지 않는다.
- 이슈 트래커(Jira 등, `18-trackers.md`)는 허용된 읽기 도구와, **사용자가 확인 화면에서 승인한 본문의 코멘트 추가**(`tracker.write_tools.add_comment`, 1종)만 쓴다. 필드 수정·상태 전환·이슈 생성·삭제·첨부는 하지 않는다. 승인 뒤 본문이 바뀌면 다시 승인받는다(guard가 본문 해시·이슈 키를 승인 기록과 대조하고, Claude Code 권한 확인은 그대로 뜬다). `--dry-run`·`--analysis-only` 결과는 게시하지 않는다 (`07-workflow.md §Step 9`, `08-safety.md §9` 규칙 2).
- 로그 원문은 필요한 구간만 읽는다. 매칭과 이슈 DB에는 마스킹된 텍스트만 쓴다. 이슈 DB에는 마스킹된 최소 예시와 fixture만 남긴다.
- Jira 코멘트에는 마스킹된 스크립트 출력과 확인받은 문장만 넣는다. Jira 원문 인용·로그 원문 통째 붙이기는 하지 않고, 로그로 확인한 것과 추정을 칸마다 구분한다.
- 분석 리포트에서 로그로 확인한 사실과 코드 기반 추정을 구분한다. placeholder 규칙으로 얻은 결과는 그렇다고 밝힌다.
- 수동 기록(`record`)은 로그·코드 분석과 매칭만 건너뛰고, 쓰기 경로와 검증은 analyze와 같다. 확인 화면과 PR에 "수동 기록"을 밝힌다.
- 규칙·해결책 변경은 `05-verification.md §5.12 (1)` 검증을 통과해야 올린다. 건너뛴 검증(`skipped`)은 통과로 표시하지 않는다. `fixed`는 `verify-fix` 통과로만 기록하고, 통과에는 시나리오 흔적이 필요하다(유일한 예외: 비코드 유형에 흔적 시그니처가 없으면 사용자 확인을 `verification.note`에 남긴다, `05-verification.md §5.12 (2)`). 검증되지 않은 해결책은 미검증으로 표시한다.
- "`SKILL.md`와 `reference/`는 eval로 검증한다"의 범위: 스킬 문서(`SKILL.md`·`reference/`·모듈 문서)의 **판단 규칙**(어느 층·유형으로 답할지, 판단 순서, 예외·우선순위, 근거로 삼을 것)을 바꾸면 **고친 스킬·모듈의 eval**을 돌린다(전체가 아니다. API 비용이 들므로 추정 비용을 보이고 승인받은 뒤 실행한다). **문구·표기·오타만** 바꾸거나 placeholder 태그·로그 문구를 실제 값으로 **이름만** 바꿨으면 pytest(문서 상한·고정 문구·생성 파일 일치)로 갈음한다. 애매하면 돌리고, 그 태그·문구가 판단 조건에 쓰이면 이름만 바꾼 것이 아니다. eval을 건너뛴 수정은 건너뛰었다고 보고한다(통과로 적지 않는다). 이슈 DB와 사내 값(`site-defaults.yaml`)은 eval 대상이 아니다 — `db_regress`·`db_verify`(위 검증, `05-verification.md`)와 `config.py check`가 보고, 실제 로그 정확도는 S-5 `offline_eval.py`가 잰다. 재반입 때 사내 대상 eval 범위는 이 규칙이 아니라 `docs/SITE_INSTALL.md` 8절(재반입)을 따른다(hook·공통 규칙이 바뀌면 사내 대상 12개 모두).
- 분류·회귀·검증의 기준은 결정적인 스크립트 출력(파서 이벤트, 시그니처 매칭)이다. 카테고리 분석 스킬(LLM)의 결과는 리포트 보조 정보로만 쓴다.
- 사내 코드와 값은 `SITE_PATHS` 경로에만 두고, 재반입은 `tools/import_draft.py`로 한다 (통째로 교체하지 않는다). 런타임 코드는 사내/사외 모드를 판별하지 않는다: `plugin/site-defaults.yaml`이 없으면 멈추고, example은 테스트 헬퍼만 쓴다 (`15-local-draft.md §15.1`).
- git 충돌, 인증 실패, MCP 부재, 스키마·생성기·파서 백엔드·외부 파서 버전 불일치는 자동으로 우회하지 않고 사용자에게 보고한다.
