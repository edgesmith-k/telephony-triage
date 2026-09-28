"""종료 코드 (contracts.md §종료 코드)."""

OK = 0            # 성공 (경고 포함)
CHECK_FAILED = 1  # 검사 실패 (drift 포함)
USAGE = 2         # 사용 오류·환경 오류
NEEDS_APPROVAL = 3  # 승인 필요 (needs-approval)
