# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import PurePath

from pants.backend.go.util_rules.coverage import GoCoverMode
from pants.core.util_rules.distdir import DistDir
from pants.option.option_types import ArgsListOption, EnumOption, StrOption
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

    coverage_mode = EnumOption(
        "--cover-mode",
        default=GoCoverMode.SET,
        help=softwrap(
            """\
            Coverage mode to use when running Go tests with coverage analysis enabled via --test-use-coverage.
            Valid values are `set`, `count`, and `atomic`:\n
            * `set`: bool: does this statement run?\n
            * `count`: int: how many times does this statement run?\n
            * `atomic`: int: count, but correct in multithreaded tests; significantly more expensive.\n
            """
        ),
    )

    _coverage_output_dir = StrOption(
        default=str(PurePath("{distdir}", "coverage", "go", "{import_path_escaped}")),
        advanced=True,
        help=softwrap(
            """
            Path to write the Go coverage reports to. Must be relative to the build root.
            `{distdir}` is replaced with the Pants `distdir`, and `{import_path_escaped}` is
            replaced with the applicable package's import path but with slashes converted to
            underscores.
            """
        ),
    )

    def coverage_output_dir(self, distdir: DistDir, import_path: str) -> PurePath:
        import_path_escaped = import_path.replace("/", "_")
        return PurePath(
            self._coverage_output_dir.format(
                distdir=distdir.relpath, import_path_escaped=import_path_escaped
            )
        )
