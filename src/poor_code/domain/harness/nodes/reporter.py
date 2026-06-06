"""reporter [C] — the graph's terminal node. Turns the final SessionState into a
Report. Reached ONLY via ("global_validator","pass"), so the node always reports
SUCCEEDED; the headless endpoint stamps ABANDONED for non-success parks. Pure +
deterministic (no LLM). build_report mirrors build_changeset in global_validator."""
from __future__ import annotations

from typing import Any

from poor_code.domain.harness.node import NodeContext, NodeResult
from poor_code.domain.harness.nodes.global_validator import build_changeset
from poor_code.domain.session.models import (
    ChangeSet, Phase, Report, ReportOutcome, SessionState, TaskReport, TaskStatus,
)


_VALIDATION_OUTPUT_TAIL = 1500  # keep the end (errors/tracebacks land there)


def _last_run_result(task):
    """The most recent attempt that produced a binding validation result, if any."""
    for attempt in reversed(task.attempts):
        if attempt.run_result is not None:
            return attempt.run_result
    return None


def _task_report(t) -> TaskReport:
    rr = _last_run_result(t)
    return TaskReport(
        task_id=t.id, title=t.title, status=t.status, attempts=len(t.attempts),
        validation_command=(rr.command if rr is not None else ""),
        validation_exit=(rr.exit_code if rr is not None else None),
        validation_output=(rr.output[-_VALIDATION_OUTPUT_TAIL:] if rr is not None else ""))


def build_report(state: SessionState, outcome: ReportOutcome) -> Report:
    tasks = state.plan.tasks if state.plan is not None else ()
    task_reports = tuple(_task_report(t) for t in tasks)
    done = sum(1 for t in tasks if t.status is TaskStatus.DONE)
    passed = outcome is ReportOutcome.SUCCEEDED
    tail = "global validation passed" if passed else "ABANDONED"
    summary = f"{done}/{len(tasks)} tasks done; {tail}"
    return Report(outcome=outcome, tasks=task_reports,
                  global_validation_passed=passed,
                  changeset=build_changeset(state), summary=summary)


def report_to_dict(r: Report) -> dict[str, Any]:
    cs = r.changeset
    return {
        "outcome": r.outcome.value,
        "tasks": [{"task_id": t.task_id, "title": t.title,
                   "status": t.status.value, "attempts": t.attempts,
                   "validation_command": t.validation_command,
                   "validation_exit": t.validation_exit,
                   "validation_output": t.validation_output} for t in r.tasks],
        "global_validation_passed": r.global_validation_passed,
        "changeset": (None if cs is None else
                      {"aggregate_diff": cs.aggregate_diff,
                       "per_task": [[tid, d] for (tid, d) in cs.per_task]}),
        "summary": r.summary,
    }


def report_from_dict(d: dict[str, Any]) -> Report:
    cs = d.get("changeset")
    return Report(
        outcome=ReportOutcome(d["outcome"]),
        tasks=tuple(TaskReport(task_id=t["task_id"], title=t["title"],
                               status=TaskStatus(t["status"]), attempts=t.get("attempts", 0),
                               validation_command=t.get("validation_command", ""),
                               validation_exit=t.get("validation_exit"),
                               validation_output=t.get("validation_output", ""))
                    for t in d.get("tasks", ())),
        global_validation_passed=d.get("global_validation_passed", False),
        changeset=(None if cs is None else ChangeSet(
            aggregate_diff=cs.get("aggregate_diff", ""),
            per_task=tuple((row[0], row[1]) for row in cs.get("per_task", ())))),
        summary=d.get("summary", ""),
    )


class Reporter:
    name = "reporter"
    phase = Phase.FINALIZING

    async def run(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(output=build_report(ctx.state, ReportOutcome.SUCCEEDED))
