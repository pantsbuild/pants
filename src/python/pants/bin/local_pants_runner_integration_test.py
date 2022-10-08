# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Sequence

from pants.testutil.pants_integration_test import PantsResult, run_pants


def test_print_stacktrace() -> None:
    def run(args: Sequence[str]) -> PantsResult:
        return run_pants(command=[*args, "list", "definitely-does-not-exist::"])

    list_rule_name = "pants.backend.project_info.list_targets"
    no_print_stacktrace = run(["--no-print-stacktrace"])
    assert "Traceback" not in no_print_stacktrace.stderr
    assert "Engine traceback:" in no_print_stacktrace.stderr
    assert list_rule_name not in no_print_stacktrace.stderr

    print_stacktrace = run(["--print-stacktrace"])
    assert "Traceback" in print_stacktrace.stderr
    assert "Engine traceback:" in print_stacktrace.stderr
    assert list_rule_name in print_stacktrace.stderr
