# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.option.option_types import ArgsListOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class GoTestSubsystem(Subsystem):
    options_scope = "go-test"
    name = "Go test binary"
    help = "Options for Go tests."

    args = ArgsListOption(
        example="-run TestFoo -v",
        extra_help=softwrap(
            """
            Known Go test options will be transformed into the form expected by the test
            binary, e.g. `-v` becomes `-test.v`. Run `go help testflag` from the Go SDK to
            learn more about the options supported by Go test binaries.
            """
        ),
        passthrough=True,
    )
