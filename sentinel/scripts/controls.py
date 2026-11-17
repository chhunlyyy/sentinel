"""Human run controls (Phase F, MON-02): cancel a run, resume a parked run, cancel or retry one task.

ControlOps is mixed into Engine. Each control is one registry transaction that moves the state, writes the
event with the actor name and channel, and writes the audit row, so the audit log and the state cannot
disagree. Source: plan/v1.1/phaseF/README.md point 12.
"""
import machines
from cycles import TDD_ROLES
from errors import SentinelError

RETRYABLE = ("FAILED", "CANCELLED")


class ControlOps:
    channel = None
    actor_name = None

    def _actor_ctx(self, actor):
        """Name and channel stored with an event: only for human actions that carry a channel."""
        if actor == machines.HUMAN and (self.channel or self.actor_name):
            return {"actor_name": self.actor_name, "channel": self.channel}
        return {}

    def _as_human(self, user, channel):
        self.channel, self.actor_name = channel, user

    def _task_of(self, slug, task_id):
        """(run, task) with the task proven to belong to the run; E_NOT_FOUND otherwise."""
        run = self._get_v2(slug)
        task = self._task_row(task_id)
        if task["run_id"] != run["id"]:
            raise SentinelError("E_NOT_FOUND", f"no task {task_id} in run {slug}", {"task": task_id})
        return run, task

    # ---- run controls
    def cancel_run(self, slug, comment=None, *, user, channel="dashboard"):
        """R23: a human cancels an active run; its open tasks are cancelled and their processes stopped."""
        self._as_human(user, channel)
        self._sync(slug)
        with self.reg.transaction():
            run = self._get_v2(slug)
            self._move(run, "CANCELLED", machines.HUMAN, reason=comment)
            self.reg.add_audit(user, channel, "cancel", slug, reason=comment)
        return self._finish_up(slug, run)

    def resume_run(self, slug, comment, *, user, channel="dashboard"):
        """R20: a human sends a NEEDS_HUMAN run back to the state it came from."""
        self._as_human(user, channel)
        run = self._get_v2(slug)
        if run["state"] != "NEEDS_HUMAN":
            raise SentinelError("E_TRANSITION", f"only a NEEDS_HUMAN run resumes, run is {run['state']}",
                                {"state": run["state"]})
        result = self.request_state(slug, run["previous_state"], machines.HUMAN, reason=comment)
        self.audit(user, channel, "resume", slug, reason=comment)
        return result

    # ---- task controls
    def cancel_task_control(self, slug, task_id, comment=None, *, user, channel="dashboard"):
        """A human cancels one task and the tasks that wait for it; the run state does not change.
        A running cycle task also moves its cycle back a state: `_cancel_in_tx` calls on_cycle_task_cancelled once."""
        self._as_human(user, channel)
        self._sync(slug)
        run_before, _ = self._task_of(slug, task_id)
        with self.reg.transaction():
            run, task = self._task_of(slug, task_id)
            self._cancel_in_tx(run, task, machines.HUMAN, comment)
            self.reg.add_audit(user, channel, "cancel", f"{slug}/{task_id}", reason=comment)
        return self._finish_up(slug, run_before)

    def retry_task(self, slug, task_id, *, user, channel="dashboard"):
        """A human retries a FAILED or CANCELLED task: a new QUEUED attempt with retry_of. The retry cap does not apply
        to a plain task; a TDD cycle task follows the cycle rules of retry_cycle_task (cap included)."""
        self._as_human(user, channel)
        self._sync(slug)
        run_before, task = self._task_of(slug, task_id)
        with self.reg.transaction():
            run, task = self._task_of(slug, task_id)
            if task["cycle_id"] and task["role"] in TDD_ROLES:
                # a cycle task: the Phase D rules (cycle state, latest task, cap, reverted violations) decide, in this
                # transaction, exactly as retry_cycle_task does; a refusal is E_PRECONDITION and changes nothing
                self._retry_cycle_task_in_tx(run, task, machines.HUMAN)
                self.reg.add_audit(user, channel, "retry", f"{slug}/{task_id}")
                return self._finish_up(slug, run_before)
            if task["state"] not in RETRYABLE or run["state"] in machines.RUN_FINAL:
                raise SentinelError("E_TRANSITION", f"task {task_id} is {task['state']} in a {run['state']} run; "
                                    "only a FAILED or CANCELLED task of an active run is retried",
                                    {"state": task["state"], "run_state": run["state"]})
            verdict = {"code": task["error_code"] or "E_EXIT", "message": task["reason"] or "retried by a human",
                       "details": {}}
            self._make_retry(run, task, verdict, task["attempt"] or 1)
            self.reg.add_audit(user, channel, "retry", f"{slug}/{task_id}")
        return self._finish_up(slug, run_before)
