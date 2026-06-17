# HANDSOFF — P4 루프엔진 통합 (코드 완성, 벤치 A/B 머지게이트 대기)

> 2026-06-17 업데이트. 아래 "남은 작업" 6개는 **전부 구현 완료**됐고 브랜치 `feat/loop-engine-unification-p4`에 있다.
> **유일하게 남은 것 = 벤치 A/B(머지 전 필수)**. 코드/유닛은 끝났다.

## 현재 상태
- 브랜치: `feat/loop-engine-unification-p4` (베이스 main=`f70f969`, HEAD=`2ab3ca5`, 8 커밋 + Task9 무변경).
- 전체 스위트: **1364 passed, 6 skipped, 0 fail**. 최종 리뷰 = "Ready to merge pending bench A/B".
- 계획서: `docs/superpowers/plans/2026-06-17-loop-engine-unification-p4.md` (로컬 전용).
- 설계: `docs/superpowers/specs/2026-06-16-agentnode-tool-loop-design.md` §3·§9-P4.

## 완료된 작업 (HANDSOFF 원본 6항목 매핑)
1. ✅ **cwd 스레딩** — `AgentNode._read_loop`에 `cwd` kwarg(기본 `Path.cwd()`, interviewer 무영향). `05b94c0`
2. ✅ **루프 엔진 통합** — `AgentNode._tool_loop` 공유 엔진 + `ToolLoopHooks`/`_DefaultHooks`/`_LoopRound`; `_stream_round`에 `leak_text` 토글(베이스는 서브클래스 충돌 방지 위해 `_stream_llm_round`로 개명, `_stream_tools`는 delegate). explorer/verifier/implementer 셋 다 복붙 `_stream_round`/`_run_tool`/`_safe_args` 삭제→엔진 사용. per-round 훅(재클램프 예산·no-op nudge·excerpt 기록)은 오버라이드 훅으로. `9b62431`/`00f9ff3`/`e50ff04`/`c68cd21`
3. ✅ **`SideEffectCompletion`** — `terminal_tool=[]`, `extract_async`=바깥세계 읽기. `d9ec0d5`
4. ✅ **implementer 배선** — `Implementer(AgentNode)`; snapshot-diff→Attempt를 `SideEffectCompletion`으로 표현. re-clamp강등/no-op nudge/tree-hash는 stateful `_ImplementerHooks`(강등 타이밍 라운드별 바이트-동일성 검증). `c68cd21`/`2ab3ca5`
5. ✅ **이중 validate 제거** — 조사 후 **무변경 유지**가 정답: `StructuredCompletion.extract`는 테스트로 고정된 공개 확장-API raw 계약, `InterviewStepCompletion`은 에러 payload용 raw 필요, verifier는 별도 `_dispatch` 경로(extract 계약과 무관). 이중 validate는 멱등·무해.
6. ✅ **죽은 코드 제거** — `AgentNode._response_format` 삭제. `974934f`

## 남은 단 하나: 벤치 A/B (머지 전 필수)
- 무손실 보존(regression 0)이 #1 제약이라, load-bearing 루프는 유닛만으론 부족 → **벤치 A/B가 머지 게이트**.
- 프로토콜: nano full-15 셋(`bench/run-nano-full15-2026-06-14.sh`)을 **main(control) vs 브랜치(treatment)** 동일 실행. 게이트 = treatment resolved 수 ≥ control AND 신규 크래시 0.
- 런북: 메모리 `bench-terminal-bench-runbook`. 기준선: `bench-2026-06-14-nano-full15`(nano 4/15).
- 통과 시: 결과를 메모리 `loop-engine-unification-p4`에 기록 → `superpowers:finishing-a-development-branch` Option 1(`--no-ff`)로 머지.

## 참고
- Phase 1(1·6번, `05b94c0`/`974934f`)은 안전·유닛검증완료라 단독 머지해도 무방(같은 브랜치에 함께 있을 뿐).
- 미세: `_tool_loop`가 `ToolContext.turn_id=self.name`("explorer"/"verifier"/"implementer")로 통일 — 기존 "explore"/"verify"/"implement"와 다르나 turn_id는 어떤 도구도 안 읽어 동작 무영향(확인됨).
