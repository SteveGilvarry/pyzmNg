"""scripts/gates/mutation_smoke.py must not leave a mutant's bytecode behind (#86)."""

from __future__ import annotations

import importlib.util
import os
from unittest.mock import patch

_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "gates", "mutation_smoke.py")


def test_mutant_bytecode_is_never_written(tmp_path):
    # A mutant the same size as the original, restored within a second, leaves
    # a .pyc that still matches the source's mtime and size, so Python keeps
    # loading the mutant afterwards. Writing no bytecode for it avoids that.
    (tmp_path / "mod.py").write_text("def check():\n    return 1 < 2\n")
    (tmp_path / "test_mod.py").write_text("from mod import check\n\ndef test_check():\n    assert check()\n")
    spec = importlib.util.spec_from_file_location("mutation_smoke", _SCRIPT)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)

    with patch.object(smoke, "REPO", tmp_path), \
            patch.object(smoke, "TARGETS", [("mod.py", "1 < 2", "1 > 2", "test_mod.py")]):
        assert smoke.main() == 0  # the mutant was caught

    assert (tmp_path / "mod.py").read_text() == "def check():\n    return 1 < 2\n"
    assert not list(tmp_path.rglob("mod*.pyc"))
