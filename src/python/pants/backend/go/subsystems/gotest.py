# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from pathlib import PurePath

from pants.backend.go.target_types import (
    GoAddressSanitizerEnabledField,
    GoMemorySanitizerEnabledField,
    GoPackageTarget,
    GoTestRaceDetectorEnabledField,
)
from pants.backend.go.util_rules.coverage import GoCoverMode
from pants.build_graph.address import Address
from pants.core.util_rules.distdir import DistDir
from pants.option.option_types import (
    ArgsListOption,
    BoolOption,
    EnumOption,
    SkipOption,
    StrListOption,
    StrOption,
)
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
            Coverage mode to use when running Go tests with coverage analysis enabled via `--test-use-coverage`.
            Valid values are `set`, `count`, and `atomic`:

              * `set`: bool: does this statement run?
              * `count`: int: how many times does this statement run?
              * `atomic`: int: count, but correct in multithreaded tests; significantly more expensive.
            """
        ),
    )

    _coverage_output_dir = StrOption(
        default=str(PurePath("{distdir}", "coverage", "go", "{target_spec}")),
        advanced=True,
        help=softwrap(
            """
            Path to write the Go coverage reports to. Must be relative to the build root.

            Replacements:

              - `{distdir}` is replaced with the Pants `distdir`.
              - `{target_spec}` is replaced with the address of the applicable `go_package` target with `/`
              characters replaced with dots (`.`).
              - `{import_path}` is replaced with the applicable package's import path. Subdirectories will be made
              for any path components separated by `/` characters.
              - `{import_path_escaped}` is replaced with the applicable package's import path but with
              slashes converted to underscores. This is deprecated and only exists to support behavior from
              earlier versions.
            """
        ),
    )

    coverage_html = BoolOption(
        default=True,
        help=softwrap(
            """
            If true, then convert coverage reports to HTML format and write a `coverage.html` file next to the
            raw coverage data.
            """
        ),
    )

    coverage_packages = StrListOption(
        default=[],
        help=softwrap(
            """
            A list of "import path patterns" for determining which import paths will be instrumented for code
            coverage.

            From `go help packages`:

            An import path is a pattern if it includes one or more "..." wildcards,
            each of which can match any string, including the empty string and
            strings containing slashes. Such a pattern expands to all package
            directories found in the GOPATH trees with names matching the
            patterns.

            To make common patterns more convenient, there are two special cases.
            First, /... at the end of the pattern can match an empty string,
            so that net/... matches both net and packages in its subdirectories, like net/http.
            Second, any slash-separated pattern element containing a wildcard never
            participates in a match of the "vendor" element in the path of a vendored
            package, so that ./... does not match packages in subdirectories of
            ./vendor or ./mycode/vendor, but ./vendor/... and ./mycode/vendor/... do.
            Note, however, that a directory named vendor that itself contains code
            is not a vendored package: cmd/vendor would be a command named vendor,
            and the pattern cmd/... matches it.
            See golang.org/s/go15vendor for more about vendoring.

            This option is similar to the `go test -coverpkg` option, but without support currently
            for reserved import path patterns like `std` and `all`.
            """
        ),
    )

    skip = SkipOption("test")

    force_race = BoolOption(
        default=False,
        help=softwrap(
            f"""
            If true, then always enable the Go data race detector when running tests regardless of the
            test-by-test `{GoTestRaceDetectorEnabledField.alias}` field on the relevant `{GoPackageTarget.alias}`
            target.

            See https://go.dev/doc/articles/race_detector for additional information about the Go data race detector.
            """
        ),
    )

    force_msan = BoolOption(
        default=False,
        help=softwrap(
            f"""
            If true, then always enable interoperation between Go and the C/C++ "memory sanitizer" when running tests
            regardless of the test-by-test `{GoMemorySanitizerEnabledField.alias}` field on the relevant
            `{GoPackageTarget.alias}` target.

            See https://github.com/google/sanitizers/wiki/MemorySanitizer for additional information about
            the C/C++ memory sanitizer.
            """
        ),
    )

    force_asan = BoolOption(
        default=False,
        help=softwrap(
            f"""
            If true, then always enable interoperation between Go and the C/C++ "address sanitizer" when running tests
            regardless of the test-by-test `{GoAddressSanitizerEnabledField.alias}` field on the relevant
            `{GoPackageTarget.alias}` target.

            See https://github.com/google/sanitizers/wiki/AddressSanitizer for additional information about
            the C/C++ address sanitizer.
            """
        ),
    )

    block_profile = BoolOption(
        default=False,
        help=softwrap(
            """
            Capture a goroutine blocking profile from the execution of the test runner. The profile will be written
            to the file `block.out` in the test extra output directory. The test binary will also be written to
            the test extra output directory.

            """
        ),
    )

    cpu_profile = BoolOption(
        default=False,
        help=softwrap(
            """
            Capture a CPU profile from the execution of the test runner. The profile will be written to the
            file `cpu.out` in the test extra output directory. The test binary will also be written to the
            test extra output directory.
            """
        ),
    )

    mem_profile = BoolOption(
        default=False,
        help=softwrap(
            """
            Capture an allocation profile from the execution of the test runner after tests have passed.
            The profile will be written to the file `mem.out` in the test extra output directory.
            The test binary will also be written to the test extra output directory.
            """
        ),
    )

    mutex_profile = BoolOption(
        default=False,
        help=softwrap(
            """
            Capture a mutex contention profile from the execution of the test runner when all tests are
            complete. The profile will be written to the file `mutex.out` in the test extra output directory.
            The test binary will also be written to the test extra output directory.
            """
        ),
    )

    trace = BoolOption(
        default=False,
        help=softwrap(
            """
            Capture an execution trace from the execution of the test runner. The trace will be written to the
            file `trace.out` in the test extra output directory.
            """
        ),
    )

    output_test_binary = BoolOption(
        default=False,
        help=softwrap(
            """
            Write the test binary to the test extra output directory.

            This is similar to the `go test -c` option, but will still run the underlying test.
            """
        ),
        advanced=True,
    )

    def coverage_output_dir(self, distdir: DistDir, address: Address, import_path: str) -> PurePath:
        target_spec = address.spec_path.replace(os.sep, ".")
        import_path_escaped = import_path.replace("/", "_")
        return PurePath(
            self._coverage_output_dir.format(
                distdir=distdir.relpath,
                target_spec=target_spec,
                import_path=import_path,
                import_path_escaped=import_path_escaped,
            )
        )
