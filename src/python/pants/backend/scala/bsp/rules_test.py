# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Tests for `get_entry_for_coord` moved with the function to
# `src/python/pants/jvm/bsp/dependencies_test.py` when the JVM-generic BSP
# dependency rules were lifted out of the Scala backend.

from pants.backend.scala.bsp import rules as scala_bsp_rules


def test_scala_bsp_rules_module_importable() -> None:
    """Smoke check: importing the module surfaces obvious import-time errors
    (missing names, circular imports) even when no real behavior is exercised
    from here. The substantive coverage lives next to the implementation in
    `pants.jvm.bsp.dependencies_test`."""
    assert callable(scala_bsp_rules.rules)
