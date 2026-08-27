"""The gate: a shipped event pump must exclude user input - a bare `processEvents()` delivers the user's next click into the middle of the loop that pumped it, and the loop's pre-collected rows then point at the wrong assets. Read from the SOURCE, because re-entrancy needs a user to demonstrate."""

import ast
import os
import unittest

_AMAZE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source_files() -> list:
    """The shipped modules - tests excluded, since a test pumps its own quiet loop where there is no user to exclude."""
    found = []
    for root, dirs, files in os.walk(_AMAZE):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]
        for filename in files:
            if filename.endswith(".py"):
                found.append(os.path.join(root, filename))
    return sorted(found)


def _bare_pumps(path: str) -> list:
    """Line numbers of every `processEvents` call carrying no flags argument."""
    with open(path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    bare = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "processEvents"
                and not node.args and not node.keywords):
            bare.append(node.lineno)
    return bare


class TestEveryShippedPumpExcludesInput(unittest.TestCase):

    def test_no_shipped_pump_is_bare(self):
        offenders = []
        for path in _source_files():
            for line in _bare_pumps(path):
                offenders.append("%s:%d"
                                 % (os.path.relpath(path, _AMAZE), line))
        self.assertEqual([], offenders,
                         "bare processEvents() in shipped code - pass "
                         "ExcludeUserInputEvents so a mid-loop click cannot "
                         "re-enter: " + ", ".join(offenders))


if __name__ == "__main__":
    unittest.main()
