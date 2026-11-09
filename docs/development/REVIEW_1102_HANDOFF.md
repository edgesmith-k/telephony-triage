# 11/02 변경 재리뷰 인계 (병합 뒤, 브랜치 `ccr-d022623a-2f4vdx`)

> **결과(11/02~03)**: 재리뷰 완료 — P0 0, P1 2(설정 짝 serial의 `--mask` 우회·새 `msg_format`이 마스킹본에서 깨짐) 수정, P2는 `REIMPORT_NOTES_1102.md` §4·§5. 그 뒤 사용자 결정으로 맨 `cid` 전부 오픈(아래 42행의 좁은 결정을 대체)·`dump_dmsg` placeholder. 내용은 `REIMPORT_NOTES_1102.md` §6. import-20261102는 태그·반입 보류(사용자에게 알림) → 새 라벨 묶음.

새 대화(`/clear` 뒤)에서 11/02에 main에 들어간 변경을 **선입견 없이** 다시 리뷰하고, P0·P1이 나오면 고쳐 새 PR·새 반입 묶음까지 가기 위한 자료. 사외 초안 모드.

## 지금 상태

- main `1004d41`(PR #78 병합). 반입 묶음 **import-20261102**를 그 커밋에서 만들어 사용자에게 보냈다(종료 3, 자동 검사 모두 통과). 태그·push·사내 반입은 사용자 — 리뷰에서 고칠 것이 나오면 **새 라벨로 다시 만들고**, 사용자에게 1102를 태그·반입하지 말라고 먼저 알린다.
- 브랜치 `ccr-d022623a-2f4vdx`는 main과 같은 내용(+ 이 문서). 새 수정은 이 브랜치에서 새 PR로.

## 리뷰 범위

| PR | 내용 | 커밋 | 비중 |
|---|---|---|---|
| #77 | 공개 oFono 표본 반영: BusyBox syslog 형식(c)·내장 `gril` RIL 짝·슬롯 규칙·벤더 `msg_format` 4개·마스킹 보강과 완화·`--mask` 짝 값 재마스킹, `ofono_reference` 0.0.3 | `a257f7b` | 핵심 |
| #78 | 데몬 사이 연결 `kind: hop`·`PairProtocol.reads`·`site_checks` o2·oFono `log-guide.md`·eval 73 재측정 | `9314858`·`5a910ee`·`bf80fef` | 핵심 |
| #75·#76 | 사외 eval 재측정(46·47·63·73·74)·DRAFT_NOTES | `f28e96a`·`3bc83ce` | 가볍게 |

- 핵심 diff: `git diff 586140a 1004d41`(PR #77+#78). 전체: `git diff 1cde81d 1004d41`.
- 설계·노트: `docs/design/17-platforms.md` §7(K19·K20)·§8·§9·§10-2·§11-2, `docs/design/08-safety.md §8`, `docs/design/14-site.md` S13·S24·S26·S29, `docs/development/REIMPORT_NOTES_1102.md`(사내 안내·P2 목록).

## 리뷰 방법

- 먼저 `CLAUDE.md`, `docs/design/12-principles.md`. `docs/history/`는 읽지 않는다.
- 이 문서에는 **요청·사용자 결정·자료 위치**만 적었다. 구현이 맞는지는 적지 않았다 — 설계 문서 문구·노트·코드 주석·커밋 메시지·PR 본문도 검증 대상이다.
- 등급: P0 안전 위반(마스킹, guard, 이슈 DB push·병합 승인, fail-closed), P1 기능 결함·계약 불일치, P2 그 밖. 결정 (r): P0·P1만 고치고 P2는 `REIMPORT_NOTES_1102.md` §4·§5 후보에. 고칠 때는 결정 (p): 계획 → 수정 → 별도 리뷰(P0·P1이면 다시) → 테스트.
- 권장 분담(독립 리뷰어 병렬): ① 마스킹 안전 — `plugin/scripts/common/masking.py`, `parse_logcat.py` `_mask_record`(Android 공통 경로) ② oFono 파서·짝 — `platforms/ofono/{journal,gril,hop,msgformat,__init__,backend}.py`, `platforms/{base,__init__,sniff}.py`, `tools/site_checks.py` ③ 문서·skill reference·eval — `log-guide.md`, 17·14·08 문서, `offsite_results.json`·채점.
- Android만 켠 설치는 줄 해석·짝이 **바이트 단위로 같아야** 하고, 마스킹은 아래 결정 범위의 모양이 든 줄만 바뀌어야 한다. 골든·`db_regress` 샘플·레포 fixture 불변.
- 디스크: pytest는 `-p no:cacheprovider`. 전체 테스트가 `/tmp/tt-*`를 남긴다 — 쌓이면 디스크가 찬다(11/02 사용자 허가로 한 번 정리함).

## 입력 로그

- 입력은 합성 로그·placeholder 기준이다(사내 로그는 사내에서 본다). 레포·fixture·테스트·문서·커밋 메시지·PR·대화 출력에는 호스트·회사·사내 구성요소 이름·D-Bus 이름(공개 `org.ofono.*` 제외)을 넣지 않는다. 검증 출력은 개수·비율만.

## 사용자 결정 (11/02)

- 로그 반출: 위 두 파일은 사내 로그가 아니고 사외 분석 허용. 레포에는 구조만(형식 규칙·합성 fixture).
- 마스킹 완화: RIL 요청 `token`의 **짧은 숫자 값**과 데이터 콜 객체(`VendorDataCall{`·`PdnInfo`·`PDN_INFO_EXT`) 안 **cid**는 가리지 않는다("토큰이랑 cid는 중요해"). 셀 위치 키는 계속 가린다. 긴 인증 토큰은 계속 가린다. → **11/02 뒤 대체**: 맨 `cid`는 어디서도 가리지 않는다(`REIMPORT_NOTES_1102.md` §6).
- 반영 범위: "반영할 수 있는 건 최대한". 데몬 사이 이름+시간 짝(`kind: hop`)과 탐색 지식(log-guide 계층·한 층씩 내려가기)도 진행.
- eval: 46·47·63·73·74 재측정(10/31), log-guide 변경 뒤 73 재측정(11/02). 수동 채점 행은 별도 에이전트 판정안을 사용자가 승인해 기록.
- 반입 묶음은 A(#77)·B(#78) 뒤 한 번(import-20261102).

## 리뷰 뒤 할 일

- P0·P1이 있으면: 사용자에게 1102 태그·반입 보류 요청 → 수정 PR(CI 통과 뒤 병합은 사용자 확인) → 새 라벨 묶음(`python3 tools/make_bundle.py --label import-2026MMDD`, 로컬 `main` 브랜치에서) → 파일 전달.
- 없으면: 사용자에게 결과를 알리고, 이 문서 머리에 결과 한 줄.
