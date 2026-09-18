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

    def test_transparent_cases_require_same_trust_dns_profile_and_gateway(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = []
            for name, profile, gateway in (("a", "profile", "image"), ("b", "profile", "image"),
                                           ("c", "changed", "image"), ("d", "profile", "changed")):
                path = root / name
                path.mkdir()
                durable(path / "run.json", encoded({"status": "completed", "required_pages_opened": True,
                    "snapshot_sha256": "world", "network_mode": "transparent"}))
                durable(path / "images.json", encoded({"agent_then_world": ["agent", "world"]}))
                durable(path / "network-profile.json", encoded({"profile_seal": profile, "gateway_image": gateway,
                                                                "edge_subnet": name}))
                seal(path)
                paths.append(path)
            self.assertEqual(len(compare_runs(paths[:2])), 2)
            for path in paths[2:]:
                with self.assertRaisesRegex(ValueError, "network profiles"):
                    compare_runs([paths[0], path])


if __name__ == "__main__":
    unittest.main()
