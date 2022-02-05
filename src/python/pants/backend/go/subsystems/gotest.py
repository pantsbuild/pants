# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.option.option_types import ArgsListOption
from pants.option.subsystem import Subsystem


class GoTestSubsystem(Subsystem):
    options_scope = "go-test"
    help = "Options for Go tests."

    args = ArgsListOption(
        help=(
            "Arguments to pass directly to the Go test binary, e.g. "
            '`--go-test-args="-run TestFoo -v"`.\n\n'
            "Known Go test options will be transformed into the form expected by the test "
            "binary, e.g. `-v` becomes `-test.v`. Run `go help testflag` from the Go SDK to "
            "learn more about the options supported by Go test binaries."
        ),
    ).passthrough()
