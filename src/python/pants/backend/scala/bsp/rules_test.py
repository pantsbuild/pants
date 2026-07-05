# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.scala.bsp import rules as scala_bsp_rules


def test_scala_bsp_rules_module_importable() -> None:
    """Smoke check: importing the module surfaces obvious import-time errors
    (missing names, circular imports) even when no real behavior is exercised
    from here. The substantive coverage lives next to the implementation in
    `pants.jvm.bsp.dependencies_test`."""
    assert callable(scala_bsp_rules.rules)
