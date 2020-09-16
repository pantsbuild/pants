# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResultWithPlatform, Process
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


def test_platform_on_local_epr_result() -> None:
    rule_runner = RuleRunner(rules=[QueryRule(FallibleProcessResultWithPlatform, (Process,))])
    this_platform = Platform.current
    process = Process(
        argv=("/bin/echo", "test"), description="Run some program that will exit cleanly."
    )
    result = rule_runner.request(FallibleProcessResultWithPlatform, [process])
    assert result.exit_code == 0
    assert result.platform == this_platform
