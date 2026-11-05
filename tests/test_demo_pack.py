"""Demo-pack static gates: required files, README strings, counts, compose.

Stdlib unittest only. Guards the issue-14 acceptance contract: the judge
clone path files exist, the README carries its three verbatim strings, the
demo script has enough live commands plus the push beat and runtime, and
the compose file names the pinned image, port, and collab profile.
"""

import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(name):
    with open(os.path.join(ROOT, name), "r", encoding="utf-8") as handle:
        return handle.read()


def _bang_lines(text):
    """Standalone command lines: start with `!cmd` (after whitespace)."""
    out = []
    for line in text.splitlines():
        if re.match(r"^\s*![a-zA-Z-]+(\s|$)", line):
            out.append(line)
    return out


class TestDemoPack(unittest.TestCase):
    def test_required_files_exist(self):
        for name in ("docker-compose.demo.yml", "README.md",
                     "docs/demo-script.md", "Makefile"):
            path = os.path.join(ROOT, name)
            self.assertTrue(os.path.isfile(path), "missing %s" % name)

    def test_readme_strings(self):
        readme = _read("README.md")
        for needle in ("Why this needs Switch",
                       "approval recorded; send skipped",
                       "!invite-agent"):
            self.assertIn(needle, readme, "README missing %r" % needle)

    def test_readme_cold_start_steps(self):
        readme = _read("README.md")
        for needle in ("docker compose", "make setup", "register",
                       "seed-demo --local", "roombrain run"):
            self.assertIn(needle, readme, "README missing step %r" % needle)

    def test_demo_script_commands(self):
        script = _read("docs/demo-script.md")
        lines = _bang_lines(script)
        self.assertGreaterEqual(len(lines), 5,
                                "want >=5 `!` lines, got %d" % len(lines))
        joined = "\n".join(lines)
        for cmd in ("!remember", "!recall", "!decisions", "!draft",
                    "!approve"):
            self.assertIn(cmd, joined, "script missing %s" % cmd)

    def test_demo_script_push_and_runtime(self):
        script = _read("docs/demo-script.md")
        self.assertTrue("push" in script or "POST /agents" in script,
                        "script must name the push path")
        self.assertIn("POST /agents", script)
        self.assertIn("3 min", script)

    def test_compose_sanity(self):
        compose = _read("docker-compose.demo.yml")
        self.assertIn("standalone-compose", compose)
        self.assertIn("8000", compose)
        self.assertIn("collab", compose)

    def test_makefile_targets(self):
        makefile = _read("Makefile")
        for target in ("demo-up", "register", "seed-local"):
            self.assertIn(target, makefile,
                          "Makefile missing %s" % target)


if __name__ == "__main__":
    unittest.main()
