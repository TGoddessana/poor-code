# HANDSOFF — P4 남은 작업 (벤치-크리티컬 루프 이관)

> AgentNode 추상화 리팩터 P0~P5는 main 머지 완료(1348 passed). P4는 **SAFE 슬라이스만** 머지됨
> (`_dispatch`/`_terminal` → 공유 `_roll_structured` dedup, 머지 `42925cc`).
> 아래는 **의도적으로 미뤄둔** P4의 핵심부 — 벤치-크리티컬이라 유닛 테스트만으론 검증 불가, **벤치 실행이 필요**.

## 왜 미뤘나
- `implementer`는 50-iteration 벤치-튜닝 루프(re-clamp 예산 / no-op nudge / tree-hash 변경감지). 단일런 고변동.
- `verifier`/`implementer`는 프로젝트 `cwd`에서 도구 실행 — 공유 `AgentNode._read_loop`는 `Path.cwd()` 하드코딩이라 그대로 못 씀.
- 설계 #1 제약 = 무손실 보존(regression 0). 벤치 없이 자율 이관은 위험.

## 남은 작업 (우선순위 순)
1. **공유 read 루프에 cwd 스레딩** — `AgentNode._read_loop`가 `Path.cwd()` 대신 노드별 cwd를 받도록 일반화(verifier/implementer 전제조건).
2. **루프 엔진 통합(설계 §3.3)** — implementer/explorer/verifier의 복붙된 `_stream_round`/`_run_tool`를 AgentNode 공유본으로 흡수 + per-round 훅(re-clamp 예산, no-op nudge, explorer excerpt 기록)을 오버라이드 가능 훅으로.
3. **`SideEffectCompletion(snapshot_diff)`** — `terminal_tools=[]`, `is_done`=도구 호출 0, `extract`=git 스냅샷 diff→Attempt. (루프 엔진 위에서만 의미 있음 → 2번 선행.)
4. **implementer 배선** = `AgentNode(tools=쓰기셋, SideEffectCompletion)`; `implement_loop`는 배선만 유지.
5. **인터뷰어/verifier 이중 validate 제거** — `Completion.extract`에 검증된 객체를 넘기는 계약 변경(현재는 idempotent라 무해, 정리만).
6. **죽은 코드 제거** — `AgentNode._response_format` (P4 dedup 후 미사용).

## 검증 방법 (필수)
- 각 이관은 **무손실 회귀 테스트** + **벤치 A/B**(이관 전후 동일 태스크셋 resolved 수)로 게이트.
- 벤치 런북: 메모리 `bench-terminal-bench-runbook` 참고.

## 참고
- 설계 문서: `docs/superpowers/specs/2026-06-16-agentnode-tool-loop-design.md` §3·§9-P4 (로컬 전용).
- P4 SAFE 슬라이스 계획서: `docs/superpowers/plans/2026-06-16-dispatch-terminal-dedup-p4.md`.
- 미세 잔여: P4 dedup에서 `_terminal` 의미적 재롤 시 `sink.node_context` 2회 호출(UI/덤프 cosmetic, 정확성 무영향).
