"""Import-consistency guard: suites importing repo packages bootstrap sys.path.

Stdlib unittest only. Every tests/test_*.py file that imports a first-party
package must carry the verbatim bootstrap line so the suite resolves imports
via the file location instead of the caller's working directory. Files with
no first-party imports (test_demo_pack.py, this file) are exempt.
"""

import ast
import os
import unittest

BOOTSTRAP = "sys.path.insert(0, os.path.join(os.path.dirname(__file__), \"..\"))"

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)


def _first_party_roots():
    """Top-level packages living at the repo root (roombrain, memory, ...)."""
    roots = set()
    for name in os.listdir(ROOT):
        if name.startswith("."):
            continue
        path = os.path.join(ROOT, name)
        if not os.path.isdir(path):
            continue
        for entry in os.listdir(path):
            if entry.endswith(".py"):
                roots.add(name)
                break
    return roots


def _imported_roots(path):
    """All import roots in a file, including lazy function-level imports."""
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


class TestImportConsistency(unittest.TestCase):
    def test_first_party_imports_require_bootstrap(self):
        first_party = _first_party_roots()
        self.assertTrue(first_party, "expected repo-root packages")
        offenders = []
        for name in sorted(os.listdir(TESTS_DIR)):
            if not name.startswith("test_") or not name.endswith(".py"):
                continue
            path = os.path.join(TESTS_DIR, name)
            if _imported_roots(path) & first_party:
                with open(path, encoding="utf-8") as handle:
                    source = handle.read()
                if BOOTSTRAP not in source:
                    offenders.append(name)
        self.assertEqual(
            offenders, [],
            "suites importing repo packages without the sys.path "
            "bootstrap: %s" % ", ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
