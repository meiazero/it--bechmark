"""Artifact-producing planning checks that never launch a simulator."""

import json
import os
import subprocess
import sys
import unittest

import contract


class PlanningChecks(unittest.TestCase):
    def test_full_plan_without_tools_or_collection(self):
        # Failure boundaries: accidentally executing a tool, unknown/duplicate
        # suites, inconsistent geometry, and confusing planned with observed data.
        directory = contract.ROOT / "results/acceptance/plan-only"
        directory.mkdir(parents=True, exist_ok=True)
        sentinels = directory / "sentinels"
        sentinels.mkdir(exist_ok=True)
        marker = directory / "unexpected-execution"
        marker.unlink(missing_ok=True)
        for name in (
            "systemd-run",
            "taskset",
            "julia",
            "git",
            "lscpu",
            "cmake",
            "cargo",
        ):
            path = sentinels / name
            path.write_text('#!/bin/sh\nprintf invoked > "$PLAN_MARKER"\nexit 91\n')
            path.chmod(0o755)
        invocation = [
            sys.executable,
            "-m",
            "bench",
            "--suite",
            "single,scaling,memory,stages",
            "--turbo-check",
            "--dry-run",
        ]
        result = subprocess.run(
            invocation,
            cwd=contract.ROOT,
            env={
                **os.environ,
                "PATH": str(sentinels),
                "PLAN_MARKER": str(marker),
            },
            text=True,
            capture_output=True,
            timeout=10,
        )
        (directory / "plan.json").write_text(result.stdout)
        (directory / "stderr.txt").write_text(result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())
        plan = json.loads(result.stdout)
        self.assertTrue(plan["plan_only"])
        self.assertFalse(plan["executed"])
        self.assertEqual(plan["expected_no_turbo"], 0)
        self.assertEqual(plan["perf_n_batches"], 2048)
        self.assertEqual(plan["baseline_processes"], 328)
        self.assertEqual(plan["possible_repeat_processes"], 320)
        self.assertEqual(plan["cooldown_s"], 20)
        groups = plan["groups"]
        self.assertEqual(len(groups), 40)
        memory = [g for g in groups if g["suite"] == "memory"]
        self.assertEqual(len(memory), 8)
        self.assertTrue(all(g["work_limit_s"] == 600 for g in memory))
        for group in groups:
            self.assertTrue(group["command_is_first_repetition"])
            if group["core"] == "e-core":
                self.assertEqual(group["cpus"], list(range(4, 4 + group["workers"])))
            if group["core"] == "mixed-informative":
                self.assertEqual(group["workers"], 12)
                self.assertEqual(group["cpus"], list(range(12)))
            self.assertIn("--config", group["command"])
            self.assertIn("--out", group["command"])
            self.assertIn("-r0-", group["command"][-1])
        self.assertFalse(any("work_s" in group for group in groups))

    def test_make_preview_defaults_to_the_complete_plan(self):
        result = subprocess.run(
            ["make", "-n", "bench-plan", "TURBO=on"],
            cwd=contract.ROOT,
            text=True,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--suite single,scaling,memory,stages", result.stdout)
        self.assertIn("--dry-run", result.stdout)

    def test_invalid_plan_selection(self):
        for suites in ("single,single", "unknown", ""):
            with self.subTest(suites=suites):
                result = subprocess.run(
                    [sys.executable, "-m", "bench", "--suite", suites, "--dry-run"],
                    cwd=contract.ROOT,
                    text=True,
                    capture_output=True,
                    timeout=10,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("suite", result.stderr)


if __name__ == "__main__":
    unittest.main()
