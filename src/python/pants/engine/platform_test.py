# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_platform_on_local_epr_result() -> None:
    rule_runner = RuleRunner(rules=[QueryRule(FallibleProcessResult, (Process,))])
    this_platform = Platform.create_for_localhost()
    process = Process(
        argv=("/bin/echo", "test"), description="Run some program that will exit cleanly."
    )
    result = rule_runner.request(FallibleProcessResult, [process])
    assert result.exit_code == 0
    assert result.platform == this_platform
