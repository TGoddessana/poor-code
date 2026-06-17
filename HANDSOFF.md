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

## Acceptance oracle 제거 실험 근거

> 2026-06-17 논의 메모. 바로 계획 단계로 넘어가고, 이후 `implement_loop` 안에 task-local test writer 노드를 두는 방향을 실험하려는 이유.

### 실제 장애 사례
- 사용자 요청: `PromptBox` 긴 입력을 자동 줄바꿈하고, Enter는 제출, Shift+Enter는 줄바꿈으로 동작하게 하는 Textual UI 변경.
- 인터뷰는 정상 완료되어 `Requirement`가 만들어졌다.
- 이후 acceptance layer에서 `acceptance_oracle -> acceptance_gate -> acceptance_oracle` repair loop가 반복됐다.
- `acceptance_oracle`은 매번 `status=done`으로 끝났지만 산출은 `0 acceptance checks designed`였다.
- `acceptance_gate`는 결정론적으로 `Acceptance spec has no checks; design at least one runnable check.`를 반환했고, route 규칙상 다시 `acceptance_oracle`로 되돌렸다.
- `acceptance_critic`와 `spec_confirm_gate`까지는 도달하지 못했다.
- acceptance repair budget이 `100`이라 사용자 입장에서는 사실상 무한루프처럼 보였다.

### 구조적 문제 인식
- 현재 oracle은 `Requirement + CodeContext`를 읽고 plan-independent `AcceptanceSpec`를 선행 작성하는 책임을 가진다.
- 이 구조는 TDD/회귀 재현처럼 입력·출력·관찰 기준이 명확한 문제에는 유효하다.
- 하지만 모든 소프트웨어 엔지니어링 문제에 선행 시험지를 작성할 수 있는 것은 아니다.
- UI/UX 개선, 탐색적 리팩터링, 조사/디버깅, 아키텍처 정리 같은 작업은 구현 전 전역 acceptance test를 강제하면 거짓 확신이나 빈 산출물이 나오기 쉽다.
- 이번 사례처럼 Textual 위젯 동작 변경은 task-local 맥락에서 테스트를 작성하는 편이 자연스럽다.

### 현재 oracle 프롬프트의 부적합성
- authoring prompt는 `$TMPDIR` scratch test, exact expected value, alternate/boundary input, whole-program invocation을 강하게 요구한다.
- 이 프롬프트는 알고리즘/파일 변환/CLI 문제에는 맞지만, Textual UI 위젯 작업에는 과도하게 절차적이다.
- 실제 trace에서 oracle은 `emit_acceptance`를 내기보다 `bash/read` 도구 호출 형태의 command/path payload만 반복했다.
- `_AcceptanceSpecOut.checks` 기본값이 `[]`라 빈 spec이 schema/parse 단계에서 실패하지 않고 gate까지 흘러갔다.
- 결과적으로 "잘못된 객체를 만들 수 있는 도메인 모델" + "큰 repair budget" 조합이 loop를 만들었다.

### 설계 방향 전환
- 큰 틀의 엔지니어링 루프는 `문제 인식 -> 이해/조사 -> 계획 -> 구현 -> 검증`이 맞다.
- 다만 `검증`은 항상 필요하지만, 검증 방식은 문제 유형마다 달라야 한다.
- 전역 oracle이 계획 전에 시험지를 강제 작성하기보다, 계획 후 task 실행 맥락에서 테스트/검증을 구체화하는 쪽을 실험한다.
- 제안 흐름:
  - 기존: `interviewer -> acceptance_oracle -> acceptance_gate -> acceptance_critic -> spec_confirm_gate -> planner`
  - 실험: `interviewer -> planner`
  - 이후 implement subgraph: `task_selector -> composer -> test_writer -> implementer -> eng_gate -> verifier -> task_selector`
- `test_writer`는 전역 "done" 시험지가 아니라, 현재 task 목적과 코드 맥락을 보고 실패해야 할 테스트/검증 코드를 먼저 작성한다.
- `verifier`는 기존처럼 실제 실행/관찰 기반으로 완료 여부를 판단한다.

### 제거/우회 시 영향 범위
- route 변경:
  - `interviewer -> planner`
  - FULL_AUTO rewrite도 `interviewer -> planner` 방향으로 조정 필요.
- `AcceptanceSpec` require 완화 필요:
  - `Planner.requires = (Requirement, CodeContext)`
  - `VerifierNode.requires = (Plan, Requirement)`
  - `GlobalValidator.requires = (Plan,)`
  - `implement_loop.compiled.requires = (Plan, Requirement, CodeContext)`
- 기존 구현에는 fallback이 일부 있다:
  - `Planner._acceptance_digest()`는 acceptance가 없으면 `(none)` 출력 가능.
  - `VerifierNode._criteria()`는 acceptance가 없으면 `Requirement.acceptance` 또는 request/task purpose로 fallback 가능.
  - `GlobalValidator.run()`은 v2에서 현재 즉시 `pass`라 `AcceptanceSpec`를 실질적으로 사용하지 않는다.
- route/contract 테스트는 갱신 필요:
  - `tests/domain/harness/test_route_acceptance.py`
  - `tests/domain/harness/test_route.py`
  - `tests/domain/harness/test_route_headless_skip.py`
  - `tests/domain/harness/test_node_contracts.py`
  - acceptance 경로를 전제로 한 일부 planner/verifier/global-validator 테스트.

### 실험 원칙
- 1단계에서는 oracle/gate/critic/spec-confirm 노드를 삭제하지 말고 route에서 우회한다.
- registry에 남겨두면 rollback이 쉽고, 기존 단위 테스트도 단계적으로 정리할 수 있다.
- oracle 제거와 `test_writer` 추가를 한 번에 하지 않는다.
- 먼저 planner 직행이 정상 동작하는지 확인한 뒤, implement subgraph에 `test_writer`를 삽입한다.
