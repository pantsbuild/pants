# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.target_types import (
    GoBinaryMainPackageField,
    GoBinaryTarget,
    GoImportPathField,
    GoModTarget,
    GoPackageSourcesField,
    GoPackageTarget,
    GoThirdPartyPackageTarget,
)
from pants.backend.go.testutil import gen_module_gomodproxy
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    first_party_pkg,
    go_mod,
    link,
    sdk,
    third_party_pkg,
)
from pants.backend.go.util_rules.binary import (
    GoBinaryMainDependencyInferenceFieldSet,
    GoBinaryMainPackage,
    GoBinaryMainPackageRequest,
    InferGoBinaryMainDependencyRequest,
)
from pants.build_graph.address import Address, ResolveError
from pants.core.target_types import (
    GenericTarget,
    TargetGeneratorSourcesHelperSourcesField,
    TargetGeneratorSourcesHelperTarget,
)
from pants.core.util_rules.archive import rules as archive_rules
from pants.engine.addresses import Addresses
from pants.engine.fs import rules as fs_rules
from pants.engine.internals.graph import _TargetParametrizations, _TargetParametrizationsRequest
from pants.engine.rules import QueryRule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    InferredDependencies,
    InvalidFieldException,
    InvalidTargetException,
)
from pants.testutil.rule_runner import RuleRunner, engine_error

# -----------------------------------------------------------------------------------------------
# Dependency inference
# -----------------------------------------------------------------------------------------------


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *go_mod.rules(),
            *first_party_pkg.rules(),
            *third_party_pkg.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            *build_pkg.rules(),
            *link.rules(),
            *assembly.rules(),
            *fs_rules(),
            *archive_rules(),
            QueryRule(_TargetParametrizations, [_TargetParametrizationsRequest]),
            QueryRule(Addresses, [DependenciesRequest]),
            QueryRule(GoBinaryMainPackage, [GoBinaryMainPackageRequest]),
            QueryRule(InferredDependencies, [InferGoBinaryMainDependencyRequest]),
        ],
        target_types=[
            GoModTarget,
            GoPackageTarget,
            GoBinaryTarget,
            GenericTarget,
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_go_package_dependency_inference(rule_runner: RuleRunner) -> None:
    # TODO(#12761): Add tests for ambiguous dependencies.
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod()",
            "foo/go.mod": dedent(
                """\
                    module go.example.com/foo
                    go 1.17

                    require (
                        rsc.io/quote v1.5.2
                        golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c // indirect
                        rsc.io/sampler v1.3.0 // indirect
                    )
                    """
            ),
            "foo/go.sum": dedent(
                """\
                golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c h1:qgOY6WgZOaTkIIMiVjBQcw93ERBE4m30iBm00nkL0i8=
                golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c/go.mod h1:NqM8EUOU14njkJ3fqMW+pc6Ldnwhi/IjpwHt7yyuwOQ=
                rsc.io/quote v1.5.2 h1:w5fcysjrx7yqtD/aO+QwRjYZOKnaM9Uh2b40tElTs3Y=
                rsc.io/quote v1.5.2/go.mod h1:LzX7hefJvL54yjefDEDHNONDjII0t9xZLPXsUe+TKr0=
                rsc.io/sampler v1.3.0 h1:7uVkIFmeBqHfdjD+gZwtXXI+RODJ2Wc4O7MPEh/QiW4=
                rsc.io/sampler v1.3.0/go.mod h1:T1hPZKmBbMNahiBKFy5HrXp6adAjACjK9JXDnKaTXpA=
                """
            ),
            "foo/pkg/foo.go": dedent(
                """\
                    package pkg
                    import "rsc.io/quote"
                    """
            ),
            "foo/pkg/BUILD": "go_package()",
            "foo/cmd/main.go": dedent(
                """\
                    package main
                    import (
                        "fmt"
                        "go.example.com/foo/pkg"
                    )
                    """
            ),
            "foo/cmd/BUILD": "go_package()",
            "foo/bad/f.go": "invalid!!!",
            "foo/bad/BUILD": "go_package()",
        }
    )

    def get_deps(addr: Address) -> set[Address]:
        tgt = rule_runner.get_target(addr)
        return set(
            rule_runner.request(
                Addresses,
                [DependenciesRequest(tgt[Dependencies])],
            )
        )

    go_mod_file_tgts = {Address("foo", relative_file_path=fp) for fp in ("go.mod", "go.sum")}

    assert get_deps(Address("foo/cmd")) == {
        Address("foo/pkg"),
    }
    assert get_deps(Address("foo/pkg")) == {Address("foo", generated_name="rsc.io/quote")}
    assert get_deps(Address("foo", generated_name="rsc.io/quote")) == {
        Address("foo", generated_name="rsc.io/sampler"),
        *go_mod_file_tgts,
    }
    assert get_deps(Address("foo", generated_name="rsc.io/sampler")) == {
        Address("foo", generated_name="golang.org/x/text/language"),
        *go_mod_file_tgts,
    }
    assert get_deps(Address("foo", generated_name="golang.org/x/text")) == go_mod_file_tgts
    # Compilation failures should not blow up Pants.
    assert not get_deps(Address("foo/bad"))


# -----------------------------------------------------------------------------------------------
# `go_package` validation
# -----------------------------------------------------------------------------------------------


def test_go_package_sources_field_validation() -> None:
    with pytest.raises(InvalidTargetException):
        GoPackageTarget({GoPackageSourcesField.alias: ()}, Address("pkg"))
    with pytest.raises(InvalidTargetException):
        GoPackageTarget({GoPackageSourcesField.alias: ("**.go",)}, Address("pkg"))
    with pytest.raises(InvalidTargetException):
        GoPackageTarget({GoPackageSourcesField.alias: ("subdir/f.go",)}, Address("pkg"))


# -----------------------------------------------------------------------------------------------
# Generate package targets from `go_mod`
# -----------------------------------------------------------------------------------------------


def test_generate_package_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/go/BUILD": "go_mod()\n",
            "src/go/go.mod": dedent(
                """\
                module example.com/src/go
                go 1.17

                require (
                    github.com/google/go-cmp v0.4.0
                    github.com/google/uuid v1.2.0
                    golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 // indirect
                )
                """
            ),
            "src/go/go.sum": dedent(
                """\
                github.com/google/go-cmp v0.4.0 h1:xsAVV57WRhGj6kEIi8ReJzQlHHqcBYCElAvkovg3B/4=
                github.com/google/go-cmp v0.4.0/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
                github.com/google/uuid v1.2.0 h1:qJYtXnJRWmpe7m/3XlyhrsLrEURqHRM2kxzoxXqyUDs=
                github.com/google/uuid v1.2.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 h1:E7g+9GITq07hpfrRu66IVDexMakfv52eLZ2CXBWiKr4=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                """
            ),
            "src/go/hello.go": "",
            "src/go/subdir/f.go": "",
            "src/go/subdir/f2.go": "",
            "src/go/another_dir/subdir/f.go": "",
        }
    )
    generated = rule_runner.request(
        _TargetParametrizations,
        [_TargetParametrizationsRequest(Address("src/go"), description_of_origin="tests")],
    ).parametrizations

    file_tgts = [
        TargetGeneratorSourcesHelperTarget(
            {TargetGeneratorSourcesHelperSourcesField.alias: fp},
            Address("src/go", relative_file_path=fp),
        )
        for fp in ("go.mod", "go.sum")
    ]

    def gen_third_party_tgt(import_path: str) -> GoThirdPartyPackageTarget:
        return GoThirdPartyPackageTarget(
            {
                GoImportPathField.alias: import_path,
                Dependencies.alias: [t.address.spec for t in file_tgts],
            },
            Address("src/go", generated_name=import_path),
        )

    all_third_party = {
        gen_third_party_tgt(pkg)
        for pkg in (
            "github.com/google/uuid",
            "github.com/google/go-cmp/cmp",
            "github.com/google/go-cmp/cmp/cmpopts",
            "github.com/google/go-cmp/cmp/internal/diff",
            "github.com/google/go-cmp/cmp/internal/flags",
            "github.com/google/go-cmp/cmp/internal/function",
            "github.com/google/go-cmp/cmp/internal/testprotos",
            "github.com/google/go-cmp/cmp/internal/teststructs",
            "github.com/google/go-cmp/cmp/internal/value",
            "golang.org/x/xerrors",
            "golang.org/x/xerrors/internal",
        )
    }
    assert set(generated.values()) == {*file_tgts, *all_third_party}


def test_third_party_package_targets_cannot_be_manually_created() -> None:
    with pytest.raises(InvalidTargetException):
        GoThirdPartyPackageTarget(
            {GoImportPathField.alias: "foo"},
            Address("foo"),
        )


# -----------------------------------------------------------------------------------------------
# The `main` field for `go_binary`
# -----------------------------------------------------------------------------------------------


def test_determine_main_pkg_for_go_binary(rule_runner: RuleRunner) -> None:
    import_path = "pantsbuild.org/go-sample-for-test"
    version = "v0.0.1"

    fake_gomod = gen_module_gomodproxy(
        version,
        import_path,
        (
            (
                "pkg/hello/hello.go",
                dedent(
                    """\
        package hello
        import "fmt"


        func Hello() {
            fmt.Println("Hello world!")
        }
        """
                ),
            ),
            (
                "cmd/hello/main.go",
                dedent(
                    f"""\
        package main
        import "{import_path}/pkg/hello"


        func main() {{
            hello.Hello()
        }}
        """
                ),
            ),
        ),
    )

    # mypy gets sad if update is reversed or ** is used here
    fake_gomod.update(
        {
            "go.mod": dedent(
                f"""\
                module example.com/foo
                go 1.16

                require (
                \t{import_path} {version}
                )
                """
            ),
            "BUILD": "go_mod(name='mod')",
            "explicit/f.go": "",
            "explicit/BUILD": "go_binary(main=':pkg')\ngo_package(name='pkg')",
            "inferred/f.go": "",
            "inferred/BUILD": "go_binary()\ngo_package(name='pkg')",
            "ambiguous/f.go": "",
            "ambiguous/BUILD": "go_binary()\ngo_package(name='pkg1')\ngo_package(name='pkg2')",
            "external/BUILD": f"go_binary(main='//:mod#{import_path}/cmd/hello')",
            # Note there are no `.go` files in this dir.
            "missing/BUILD": "go_binary()",
            "explicit_wrong_type/BUILD": dedent(
                """\
                target(name='dep')
                go_binary(main=':dep')
                """
            ),
        }
    )

    rule_runner.write_files(fake_gomod)

    rule_runner.set_options(
        [
            "--go-test-args=-v -bench=.",
            f"--golang-subprocess-env-vars=GOPROXY=file://{rule_runner.build_root}/go-mod-proxy",
            "--golang-subprocess-env-vars=GOSUMDB=off",
        ],
        env_inherit={"PATH"},
    )

    def get_main(addr: Address) -> Address:
        tgt = rule_runner.get_target(addr)
        main_addr = rule_runner.request(
            GoBinaryMainPackage, [GoBinaryMainPackageRequest(tgt[GoBinaryMainPackageField])]
        ).address
        inferred_addresses = rule_runner.request(
            InferredDependencies,
            [
                InferGoBinaryMainDependencyRequest(
                    GoBinaryMainDependencyInferenceFieldSet.create(tgt)
                )
            ],
        )
        assert inferred_addresses == InferredDependencies([main_addr])
        return main_addr

    assert get_main(Address("explicit")) == Address("explicit", target_name="pkg")
    assert get_main(Address("inferred")) == Address("inferred", target_name="pkg")
    assert get_main(Address("external")) == Address(
        "",
        target_name="mod",
        generated_name="pantsbuild.org/go-sample-for-test/cmd/hello",
    )

    with engine_error(ResolveError, contains="none were found"):
        get_main(Address("missing"))
    with engine_error(ResolveError, contains="There are multiple `go_package` targets"):
        get_main(Address("ambiguous"))
    with engine_error(
        InvalidFieldException, contains="a `go_package` or `go_third_party_package` target"
    ):
        get_main(Address("explicit_wrong_type"))
