# 합성 샘플 이슈 DB (자리표시)

이 트리는 **Phase 1**에서 채운다 (`docs/design/11-phases.md` Phase 1):
디렉토리 구조, `issue-db.config.yaml`, `schema/` 6종, `templates/` 3종,
`.github/CODEOWNERS`, `CONTRIBUTING.md`, `GLOSSARY.md`, `docs/` 3종,
`parser-rules/`, 카테고리별 샘플 유형 6개와 fixture.

**Phase D0에서 먼저 만든 것**은 `.githooks/pre-commit`·`.githooks/pre-push`
스텁뿐이다. D0 완료 기준의 "실행 비트와 함께 커밋된다(`git ls-files -s`로
100755 확인)"를 이 시점의 산출물만으로 확인하기 위해서다
(`11-phases.md` Phase D0 완료 기준).

이 파일은 Phase 1에서 `db_build.py`가 만드는 README로 대체되지 않는다
(생성 README는 운영 이슈 DB의 것이고, 이 파일은 개발 레포의 안내다).
