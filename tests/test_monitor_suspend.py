"""A machine suspended while an agent runs must not count the sleep as task time (MEF-HR dogfood, 2026-11-24)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import runtime  # noqa: E402


class SuspendIsNotTaskTime(unittest.TestCase):
    def monitor(self, timeout, wall_jump, mono_step):
        ops = mock.MagicMock()
        ops.heartbeat.return_value = 10_000
        ops.reg.get_row.return_value = {"state": "RUNNING"}
        ops._write_exit = runtime.RuntimeOps._write_exit
        ops._task_row.return_value = {"session_id": None}
        adapter = mock.MagicMock()
        adapter.wait.side_effect = [False, False, True]
        adapter.reap.return_value = 0
        adapter.result.return_value = (0, "", "")
        adapter.runner = {}
        wall = iter(range(0, 10**9, wall_jump))
        mono = iter(range(0, 10**9, mono_step))
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(runtime.time, "time", side_effect=lambda: next(wall)), \
                mock.patch.object(runtime.time, "monotonic", side_effect=lambda: next(mono)):
            runtime.RuntimeOps._monitor(ops, {"slug": "s"}, {"id": "t-1", "timeout_seconds": timeout,
                                                              "repo_id": "r", "role": "docs"},
                                        adapter, mock.Mock(pid=1), Path(tmp))
        return ops, adapter

    def test_a_long_suspend_does_not_time_the_task_out(self):
        ops, adapter = self.monitor(timeout=5400, wall_jump=10 * 3600, mono_step=1)
        adapter.cancel.assert_not_called()
        self.assertFalse(ops.finish_task.call_args.kwargs["timed_out"])

    def test_real_running_time_still_times_out(self):
        ops, adapter = self.monitor(timeout=5400, wall_jump=1, mono_step=6000)
        adapter.cancel.assert_called_once()
        self.assertTrue(ops.finish_task.call_args.kwargs["timed_out"])


if __name__ == "__main__":
    unittest.main()
