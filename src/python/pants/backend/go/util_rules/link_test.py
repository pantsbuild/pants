# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.target_types import GoModTarget
from pants.backend.go.util_rules import (
    assembly,
    build_opts,
    build_pkg,
    build_pkg_target,
    first_party_pkg,
    go_mod,
    goroot,
    implicit_linker_deps,
    import_analysis,
    link,
    sdk,
    third_party_pkg,
)
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    BuiltGoPackage,
    MergeBuiltGoPackageArchivesRequest,
    MergedGoPackageArchives,
)
from pants.backend.go.util_rules.link import LinkedGoBinary, LinkGoBinaryRequest
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.engine.fs import Digest
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            *assembly.rules(),
            *build_opts.rules(),
            *build_pkg.rules(),
            *build_pkg_target.rules(),
            *import_analysis.rules(),
            *go_mod.rules(),
            *goroot.rules(),
            *first_party_pkg.rules(),
            *implicit_linker_deps.rules(),
            *link.rules(),
            *third_party_pkg.rules(),
            *target_type_rules.rules(),
            QueryRule(BuiltGoPackage, [BuildGoPackageRequest]),
            QueryRule(MergedGoPackageArchives, [MergeBuiltGoPackageArchivesRequest]),
            QueryRule(LinkedGoBinary, [LinkGoBinaryRequest]),
            QueryRule(Process, [GoSdkProcess]),
            QueryRule(ProcessResult, [Process]),
        ],
        target_types=[GoModTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def _dep_package(rule_runner: RuleRunner) -> BuildGoPackageRequest:
    return BuildGoPackageRequest(
        import_path="example.com/dep",
        pkg_name="dep",
        dir_path="dep",
        build_opts=GoBuildOptions(),
        go_files=("dep.go",),
        digest=rule_runner.make_snapshot(
            {
                "dep/dep.go": dedent(
                    """\
                    package dep

                    func Greeting() string {
                        return "hello"
                    }
                    """
                )
            }
        ).digest,
        s_files=(),
        direct_dependencies=(),
        minimum_go_version=None,
    )


def _link_main(
    rule_runner: RuleRunner,
    main_go: str,
    direct_dependencies: tuple[BuildGoPackageRequest, ...] = (),
) -> Digest:
    built_package = rule_runner.request(
        BuiltGoPackage,
        [
            BuildGoPackageRequest(
                import_path="main",
                pkg_name="main",
                dir_path="",
                build_opts=GoBuildOptions(),
                go_files=("main.go",),
                digest=rule_runner.make_snapshot({"main.go": main_go}).digest,
                s_files=(),
                direct_dependencies=direct_dependencies,
                minimum_go_version=None,
            )
        ],
    )
    merged = rule_runner.request(
        MergedGoPackageArchives, [MergeBuiltGoPackageArchivesRequest((built_package,))]
    )
    binary = rule_runner.request(
        LinkedGoBinary,
        [
            LinkGoBinaryRequest(
                input_digest=merged.digest,
                archives=(built_package.pkg_archive_path,),
                build_opts=GoBuildOptions(),
                import_paths_to_pkg_a_files=merged.import_paths_to_pkg_a_files,
                output_filename="./bin",
                description="Link Go binary for test",
            )
        ],
    )
    return binary.digest


def _build_id(rule_runner: RuleRunner, binary: Digest) -> str:
    process = rule_runner.request(
        Process,
        [
            GoSdkProcess(
                ("tool", "buildid", "./bin"),
                input_digest=binary,
                description="Read the Go build ID from the linked binary",
            )
        ],
    )
    return rule_runner.request(ProcessResult, [process]).stdout.decode().strip()


_STANDALONE = dedent(
    """\
    package main

    func main() {
        println("hello")
    }
    """
)

_USES_DEP = dedent(
    """\
    package main

    import "example.com/dep"

    func main() {
        println(dep.Greeting())
    }
    """
)

_STANDALONE_ALTERED = dedent(
    """\
    package main

    func main() {
        println("goodbye")
    }
    """
)


def test_link_records_a_build_id(rule_runner: RuleRunner) -> None:
    build_id = _build_id(rule_runner, _link_main(rule_runner, _STANDALONE))
    assert build_id, "linked binary does not record a Go build ID"


def test_build_id_distinguishes_binaries(rule_runner: RuleRunner) -> None:
    standalone = _build_id(rule_runner, _link_main(rule_runner, _STANDALONE))
    uses_dep = _build_id(
        rule_runner, _link_main(rule_runner, _USES_DEP, (_dep_package(rule_runner),))
    )
    assert standalone and uses_dep, "linked binary does not record a Go build ID"
    assert standalone != uses_dep


def test_build_id_tracks_source_content(rule_runner: RuleRunner) -> None:
    original = _build_id(rule_runner, _link_main(rule_runner, _STANDALONE))
    altered = _build_id(rule_runner, _link_main(rule_runner, _STANDALONE_ALTERED))
    assert original and altered, "linked binary does not record a Go build ID"
    assert original != altered
