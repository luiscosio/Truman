import json
import tempfile
import unittest
from pathlib import Path
from sandbox.archive import durable, encoded, seal
from sandbox.suite import compare_runs


class SuiteTests(unittest.TestCase):
    def test_same_world_allows_different_model_effort_but_not_different_task(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = {"status": "completed", "required_pages_opened": True, "snapshot_sha256": "world",
                    "replay_mode": "world", "experiment_sha256": "task", "observed_tools": ["WebFetch"],
                    "limits": {"seconds": 60}, "agent_adapter": "claude-code"}
            paths = []
            for name, extra in (("a", {"model": "a", "effort": "low"}),
                                ("b", {"model": "b", "effort": "high"}),
                                ("c", {"experiment_sha256": "another-task"})):
                path = root / name
                path.mkdir()
                durable(path / "run.json", encoded({**base, **extra}))
                durable(path / "images.json", encoded({"agent_then_world": ["agent", "world"]}))
                seal(path)
                paths.append(path)
            self.assertEqual(len(compare_runs(paths[:2])), 2)
            with self.assertRaises(ValueError):
                compare_runs(paths)


if __name__ == "__main__":
    unittest.main()
