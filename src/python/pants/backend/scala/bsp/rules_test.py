# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.scala.bsp import rules as scala_bsp_rules
from pants.backend.scala.bsp.rules import _jdk_request_sort_key
from pants.jvm.jdk_rules import JdkRequest
from pants.jvm.subsystems import JvmSubsystem
from pants.testutil.option_util import create_subsystem


def test_scala_bsp_rules_module_importable() -> None:
    """Smoke check: importing the module surfaces obvious import-time errors
    (missing names, circular imports) even when no real behavior is exercised
    from here. The substantive coverage lives next to the implementation in
    `pants.jvm.bsp.dependencies_test`."""
    assert callable(scala_bsp_rules.rules)


def test_jdk_request_sort_key_ignores_legacy_version_prefix() -> None:
    """`temurin:1.17` and `temurin:17` name the same JDK, so they must sort the same: the highest
    JDK is the one handed to the IDE."""
    sort_key = _jdk_request_sort_key(create_subsystem(JvmSubsystem, jdk="temurin:11"))

    assert sort_key(JdkRequest("temurin:1.11")) == sort_key(JdkRequest("temurin:11"))
    assert sort_key(JdkRequest("temurin:1.17")) > sort_key(JdkRequest("temurin:11"))
    assert sort_key(JdkRequest("temurin:17")) > sort_key(JdkRequest("temurin:1.11"))
    assert sort_key(JdkRequest("temurin:1.11.0.23")) > sort_key(JdkRequest("temurin:11"))
    # A target without a `jdk` falls back to `[jvm].jdk`.
    assert sort_key(JdkRequest.SOURCE_DEFAULT) == sort_key(JdkRequest("temurin:1.11"))
    # ... which may itself still be written with the legacy prefix.
    legacy_default_sort_key = _jdk_request_sort_key(
        create_subsystem(JvmSubsystem, jdk="temurin:1.17")
    )
    assert legacy_default_sort_key(JdkRequest.SOURCE_DEFAULT) == sort_key(JdkRequest("temurin:17"))
    assert legacy_default_sort_key(JdkRequest.SOURCE_DEFAULT) > sort_key(JdkRequest("temurin:11"))
    # The system JDK and bare labels sort lowest.
    assert sort_key(JdkRequest.SYSTEM) < sort_key(JdkRequest("temurin:1.8"))
    assert sort_key(JdkRequest("system")) < sort_key(JdkRequest("temurin:1.8"))
