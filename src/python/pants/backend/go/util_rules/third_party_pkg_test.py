# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go.target_types import GoModTarget
from pants.backend.go.util_rules import sdk, third_party_pkg
from pants.backend.go.util_rules.third_party_pkg import (
    ThirdPartyModuleInfo,
    ThirdPartyModuleInfoRequest,
    ThirdPartyPkgInfo,
    ThirdPartyPkgInfoRequest,
    _AllDownloadedModules,
    _AllDownloadedModulesRequest,
    _DownloadedModule,
    _DownloadedModuleRequest,
)
from pants.engine.fs import Digest, PathGlobs, Snapshot
from pants.engine.process import ProcessExecutionFailure
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            *third_party_pkg.rules(),
            QueryRule(_AllDownloadedModules, [_AllDownloadedModulesRequest]),
            QueryRule(_DownloadedModule, [_DownloadedModuleRequest]),
            QueryRule(ThirdPartyModuleInfo, [ThirdPartyModuleInfoRequest]),
            QueryRule(ThirdPartyPkgInfo, [ThirdPartyPkgInfoRequest]),
        ],
        target_types=[GoModTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


GO_MOD = dedent(
    """\
    module example.com/third-party-module
    go 1.17

    // No dependencies, already has `go.mod`.
    require github.com/google/uuid v1.3.0

    // No dependencies, but missing `go.mod`.
    require cloud.google.com/go v0.26.0

    // Has dependencies, already has a `go.sum`.
    require (
        github.com/google/go-cmp v0.5.6
        golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543  // indirect
    )

    // Has dependencies, missing `go.sum`. This causes `go list` to fail in that directory unless
    // we add `go.sum`.
    require (
        rsc.io/quote v1.5.2
        golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c // indirect
        rsc.io/sampler v1.3.0 // indirect
    )
    """
)

GO_SUM = dedent(
    """\
    cloud.google.com/go v0.26.0 h1:e0WKqKTd5BnrG8aKH3J3h+QvEIQtSUcf2n5UZ5ZgLtQ=
    cloud.google.com/go v0.26.0/go.mod h1:aQUYkXzVsufM+DwF1aE+0xfcU+56JwCaLick0ClmMTw=
    github.com/google/go-cmp v0.5.6 h1:BKbKCqvP6I+rmFHt06ZmyQtvB8xAkWdhFyr0ZUNZcxQ=
    github.com/google/go-cmp v0.5.6/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
    github.com/google/uuid v1.3.0 h1:t6JiXgmwXMjEs8VusXIJk2BXHsn+wx8BZdTaoZ5fu7I=
    github.com/google/uuid v1.3.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
    golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c h1:qgOY6WgZOaTkIIMiVjBQcw93ERBE4m30iBm00nkL0i8=
    golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c/go.mod h1:NqM8EUOU14njkJ3fqMW+pc6Ldnwhi/IjpwHt7yyuwOQ=
    golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 h1:E7g+9GITq07hpfrRu66IVDexMakfv52eLZ2CXBWiKr4=
    golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
    rsc.io/quote v1.5.2 h1:w5fcysjrx7yqtD/aO+QwRjYZOKnaM9Uh2b40tElTs3Y=
    rsc.io/quote v1.5.2/go.mod h1:LzX7hefJvL54yjefDEDHNONDjII0t9xZLPXsUe+TKr0=
    rsc.io/sampler v1.3.0 h1:7uVkIFmeBqHfdjD+gZwtXXI+RODJ2Wc4O7MPEh/QiW4=
    rsc.io/sampler v1.3.0/go.mod h1:T1hPZKmBbMNahiBKFy5HrXp6adAjACjK9JXDnKaTXpA=
    """
)


# -----------------------------------------------------------------------------------------------
# Download modules
# -----------------------------------------------------------------------------------------------


def test_download_modules(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot({"go.mod": GO_MOD, "go.sum": GO_SUM}).digest
    downloaded_modules = rule_runner.request(
        _AllDownloadedModules, [_AllDownloadedModulesRequest(input_digest)]
    )
    assert len(downloaded_modules) == 7

    def assert_module(module: str, version: str, sample_file: str) -> None:
        assert (module, version) in downloaded_modules
        digest = downloaded_modules[(module, version)]
        snapshot = rule_runner.request(Snapshot, [digest])
        assert "go.mod" in snapshot.files
        assert "go.sum" in snapshot.files
        assert sample_file in snapshot.files

        extracted_module = rule_runner.request(
            _DownloadedModule, [_DownloadedModuleRequest(module, version, input_digest)]
        )
        extracted_snapshot = rule_runner.request(Snapshot, [extracted_module.digest])
        assert extracted_snapshot == snapshot

    assert_module("cloud.google.com/go", "v0.26.0", "bigtable/filter.go")
    assert_module("github.com/google/uuid", "v1.3.0", "uuid.go")
    assert_module("github.com/google/go-cmp", "v0.5.6", "cmp/cmpopts/errors_go113.go")
    assert_module("golang.org/x/text", "v0.0.0-20170915032832-14c0d48ead0c", "width/transform.go")
    assert_module("golang.org/x/xerrors", "v0.0.0-20191204190536-9bdfabe68543", "wrap.go")
    assert_module("rsc.io/quote", "v1.5.2", "quote.go")
    assert_module("rsc.io/sampler", "v1.3.0", "sampler.go")


def test_download_modules_missing_module(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot({"go.mod": GO_MOD, "go.sum": GO_SUM}).digest
    with engine_error(
        AssertionError, contains="The module some_project.org/project@v1.1 was not downloaded"
    ):
        rule_runner.request(
            _DownloadedModule,
            [_DownloadedModuleRequest("some_project.org/project", "v1.1", input_digest)],
        )


def test_download_modules_invalid_go_sum(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot(
        {
            "go.mod": dedent(
                """\
                module example.com/third-party-module
                go 1.17
                require github.com/google/uuid v1.3.0
                """
            ),
            "go.sum": dedent(
                """\
                github.com/google/uuid v1.3.0 h1:00000gmwXMjEs8VusXIJk2BXHsn+wx8BZdTaoZ5fu7I=
                github.com/google/uuid v1.3.0/go.mod h1:00000e4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
                """
            ),
        }
    ).digest
    with engine_error(ProcessExecutionFailure, contains="SECURITY ERROR"):
        rule_runner.request(_AllDownloadedModules, [_AllDownloadedModulesRequest(input_digest)])


def test_download_modules_missing_go_sum(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot(
        {
            "go.mod": dedent(
                """\
                module example.com/third-party-module
                go 1.17
                require github.com/google/uuid v1.3.0
                """
            ),
            # `go.sum` is for a different module.
            "go.sum": dedent(
                """\
                cloud.google.com/go v0.26.0 h1:e0WKqKTd5BnrG8aKH3J3h+QvEIQtSUcf2n5UZ5ZgLtQ=
                cloud.google.com/go v0.26.0/go.mod h1:aQUYkXzVsufM+DwF1aE+0xfcU+56JwCaLick0ClmMTw=
                """
            ),
        }
    ).digest
    with engine_error(contains="`go.mod` and/or `go.sum` changed!"):
        rule_runner.request(_AllDownloadedModules, [_AllDownloadedModulesRequest(input_digest)])


# -----------------------------------------------------------------------------------------------
# Determine package info
# -----------------------------------------------------------------------------------------------


def test_determine_pkg_info(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"go.mod": GO_MOD, "go.sum": GO_SUM, "BUILD": "go_mod(name='mod')"})
    input_digest = rule_runner.request(Digest, [PathGlobs(["go.mod", "go.sum"])])

    def assert_module(
        module: str,
        version: str,
        expected: list[str] | dict[str, ThirdPartyPkgInfo],
        *,
        check_subset: bool = False,
        skip_checking_pkg_info: bool = False,
    ) -> None:
        module_info = rule_runner.request(
            ThirdPartyModuleInfo, [ThirdPartyModuleInfoRequest(module, version, input_digest)]
        )
        # If `check_subset`, check that the expected import_paths are included.
        if check_subset:
            assert isinstance(expected, list)
            assert set(expected).issubset(module_info.keys())
        else:
            # If expected is a dict, check that the ThirdPartyPkgInfo is correct for each package.
            if isinstance(expected, dict):
                assert dict(module_info) == expected
            # Else, only check that the import paths are present.
            else:
                assert list(module_info.keys()) == expected

        # Check our subsetting logic.
        if not skip_checking_pkg_info:
            for pkg_info in module_info.values():
                extracted_pkg = rule_runner.request(
                    ThirdPartyPkgInfo,
                    [ThirdPartyPkgInfoRequest(pkg_info.import_path, module, version, input_digest)],
                )
                assert extracted_pkg == pkg_info

    assert_module(
        "cloud.google.com/go",
        "v0.26.0",
        ["cloud.google.com/go/bigquery", "cloud.google.com/go/firestore"],
        check_subset=True,
    )

    uuid_mod = "github.com/google/uuid"
    uuid_version = "v1.3.0"
    uuid_digest = rule_runner.request(
        _DownloadedModule, [_DownloadedModuleRequest(uuid_mod, uuid_version, input_digest)]
    ).digest
    assert_module(
        uuid_mod,
        uuid_version,
        {
            uuid_mod: ThirdPartyPkgInfo(
                import_path=uuid_mod,
                module_path=uuid_mod,
                version=uuid_version,
                digest=uuid_digest,
                imports=(
                    "bytes",
                    "crypto/md5",
                    "crypto/rand",
                    "crypto/sha1",
                    "database/sql/driver",
                    "encoding/binary",
                    "encoding/hex",
                    "encoding/json",
                    "errors",
                    "fmt",
                    "hash",
                    "io",
                    "net",
                    "os",
                    "strings",
                    "sync",
                    "time",
                ),
                go_files=(
                    "dce.go",
                    "doc.go",
                    "hash.go",
                    "marshal.go",
                    "node.go",
                    "node_net.go",
                    "null.go",
                    "sql.go",
                    "time.go",
                    "util.go",
                    "uuid.go",
                    "version1.go",
                    "version4.go",
                ),
                s_files=(),
            )
        },
    )

    assert_module(
        "github.com/google/go-cmp",
        "v0.5.6",
        [
            "github.com/google/go-cmp/cmp",
            "github.com/google/go-cmp/cmp/cmpopts",
            "github.com/google/go-cmp/cmp/internal/diff",
            "github.com/google/go-cmp/cmp/internal/flags",
            "github.com/google/go-cmp/cmp/internal/function",
            "github.com/google/go-cmp/cmp/internal/testprotos",
            "github.com/google/go-cmp/cmp/internal/teststructs",
            "github.com/google/go-cmp/cmp/internal/teststructs/foo1",
            "github.com/google/go-cmp/cmp/internal/teststructs/foo2",
            "github.com/google/go-cmp/cmp/internal/value",
        ],
    )
    assert_module(
        "golang.org/x/text",
        "v0.0.0-20170915032832-14c0d48ead0c",
        ["golang.org/x/text/cmd/gotext", "golang.org/x/text/collate"],
        check_subset=True,
        skip_checking_pkg_info=True,  # Contains unsupported `.cgo` files.
    )
    assert_module(
        "golang.org/x/xerrors",
        "v0.0.0-20191204190536-9bdfabe68543",
        ["golang.org/x/xerrors", "golang.org/x/xerrors/internal"],
    )

    assert_module("rsc.io/quote", "v1.5.2", ["rsc.io/quote", "rsc.io/quote/buggy"])
    assert_module("rsc.io/sampler", "v1.3.0", ["rsc.io/sampler"])


def test_determine_pkg_info_missing(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot({"go.mod": GO_MOD, "go.sum": GO_SUM}).digest
    with engine_error(
        AssertionError,
        contains=(
            "The package another_project.org/foo does not belong to the module "
            "github.com/google/uuid@v1.3.0"
        ),
    ):
        rule_runner.request(
            ThirdPartyPkgInfo,
            [
                ThirdPartyPkgInfoRequest(
                    "another_project.org/foo", "github.com/google/uuid", "v1.3.0", input_digest
                )
            ],
        )


def test_determine_pkg_info_no_packages(rule_runner) -> None:
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/third-party-module
                go 1.17

                require github.com/Azure/go-autorest v13.3.2+incompatible
                """
            ),
            "go.sum": dedent(
                """\
                github.com/Azure/go-autorest v13.3.2+incompatible h1:VxzPyuhtnlBOzc4IWCZHqpyH2d+QMLQEuy3wREyY4oc=
                github.com/Azure/go-autorest v13.3.2+incompatible/go.mod h1:r+4oMnoxhatjLLJ6zxSWATqVooLgysK6ZNox3g/xq24=
                """
            ),
            "BUILD": "go_mod(name='mod')",
        }
    )
    input_digest = rule_runner.request(Digest, [PathGlobs(["go.mod", "go.sum"])])
    module_info = rule_runner.request(
        ThirdPartyModuleInfo,
        [
            ThirdPartyModuleInfoRequest(
                "github.com/Azure/go-autorest", "v13.3.2+incompatible", input_digest
            )
        ],
    )
    assert not module_info


def test_determine_pkg_info_module_with_replace_directive(rule_runner: RuleRunner) -> None:
    """Regression test for https://github.com/pantsbuild/pants/issues/13138."""
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/third-party-module
                go 1.17

                require github.com/hashicorp/consul/api v1.3.0
                """
            ),
            "go.sum": dedent(
                """\
github.com/Azure/go-autorest v13.3.2+incompatible h1:VxzPyuhtnlBOzc4IWCZHqpyH2d+QMLQEuy3wREyY4oc=
github.com/Azure/go-autorest v13.3.2+incompatible/go.mod h1:r+4oMnoxhatjLLJ6zxSWATqVooLgysK6ZNox3g/xq24=
github.com/armon/circbuf v0.0.0-20150827004946-bbbad097214e h1:QEF07wC0T1rKkctt1RINW/+RMTVmiwxETico2l3gxJA=
github.com/armon/circbuf v0.0.0-20150827004946-bbbad097214e/go.mod h1:3U/XgcO3hCbHZ8TKRvWD2dDTCfh9M9ya+I9JpbB7O8o=
github.com/armon/go-metrics v0.0.0-20180917152333-f0300d1749da h1:8GUt8eRujhVEGZFFEjBj46YV4rDjvGrNxb0KMWYkL2I=
github.com/armon/go-metrics v0.0.0-20180917152333-f0300d1749da/go.mod h1:Q73ZrmVTwzkszR9V5SSuryQ31EELlFMUz1kKyl939pY=
github.com/armon/go-radix v0.0.0-20180808171621-7fddfc383310 h1:BUAU3CGlLvorLI26FmByPp2eC2qla6E1Tw+scpcg/to=
github.com/armon/go-radix v0.0.0-20180808171621-7fddfc383310/go.mod h1:ufUuZ+zHj4x4TnLV4JWEpy2hxWSpsRywHrMgIH9cCH8=
github.com/bgentry/speakeasy v0.1.0 h1:ByYyxL9InA1OWqxJqqp2A5pYHUrCiAL6K3J+LKSsQkY=
github.com/bgentry/speakeasy v0.1.0/go.mod h1:+zsyZBPWlz7T6j88CTgSN5bM796AkVf0kBD4zp0CCIs=
github.com/davecgh/go-spew v1.1.0/go.mod h1:J7Y8YcW2NihsgmVo/mv3lAwl/skON4iLHjSsI+c5H38=
github.com/davecgh/go-spew v1.1.1 h1:vj9j/u1bqnvCEfJOwUhtlOARqs3+rkHYY13jYWTU97c=
github.com/davecgh/go-spew v1.1.1/go.mod h1:J7Y8YcW2NihsgmVo/mv3lAwl/skON4iLHjSsI+c5H38=
github.com/fatih/color v1.7.0 h1:DkWD4oS2D8LGGgTQ6IvwJJXSL5Vp2ffcQg58nFV38Ys=
github.com/fatih/color v1.7.0/go.mod h1:Zm6kSWBoL9eyXnKyktHP6abPY2pDugNf5KwzbycvMj4=
github.com/google/btree v0.0.0-20180813153112-4030bb1f1f0c h1:964Od4U6p2jUkFxvCydnIczKteheJEzHRToSGK3Bnlw=
github.com/google/btree v0.0.0-20180813153112-4030bb1f1f0c/go.mod h1:lNA+9X1NB3Zf8V7Ke586lFgjr2dZNuvo3lPJSGZ5JPQ=
github.com/hashicorp/consul/api v1.3.0 h1:HXNYlRkkM/t+Y/Yhxtwcy02dlYwIaoxzvxPnS+cqy78=
github.com/hashicorp/consul/api v1.3.0/go.mod h1:MmDNSzIMUjNpY/mQ398R4bk2FnqQLoPndWW5VkKPlCE=
github.com/hashicorp/consul/sdk v0.3.0 h1:UOxjlb4xVNF93jak1mzzoBatyFju9nrkxpVwIp/QqxQ=
github.com/hashicorp/consul/sdk v0.3.0/go.mod h1:VKf9jXwCTEY1QZP2MOLRhb5i/I/ssyNV1vwHyQBF0x8=
github.com/hashicorp/errwrap v1.0.0 h1:hLrqtEDnRye3+sgx6z4qVLNuviH3MR5aQ0ykNJa/UYA=
github.com/hashicorp/errwrap v1.0.0/go.mod h1:YH+1FKiLXxHSkmPseP+kNlulaMuP3n2brvKWEqk/Jc4=
github.com/hashicorp/go-cleanhttp v0.5.1 h1:dH3aiDG9Jvb5r5+bYHsikaOUIpcM0xvgMXVoDkXMzJM=
github.com/hashicorp/go-cleanhttp v0.5.1/go.mod h1:JpRdi6/HCYpAwUzNwuwqhbovhLtngrth3wmdIIUrZ80=
github.com/hashicorp/go-immutable-radix v1.0.0 h1:AKDB1HM5PWEA7i4nhcpwOrO2byshxBjXVn/J/3+z5/0=
github.com/hashicorp/go-immutable-radix v1.0.0/go.mod h1:0y9vanUI8NX6FsYoO3zeMjhV/C5i9g4Q3DwcSNZ4P60=
github.com/hashicorp/go-msgpack v0.5.3 h1:zKjpN5BK/P5lMYrLmBHdBULWbJ0XpYR+7NGzqkZzoD4=
github.com/hashicorp/go-msgpack v0.5.3/go.mod h1:ahLV/dePpqEmjfWmKiqvPkv/twdG7iPBM1vqhUKIvfM=
github.com/hashicorp/go-multierror v1.0.0 h1:iVjPR7a6H0tWELX5NxNe7bYopibicUzc7uPribsnS6o=
github.com/hashicorp/go-multierror v1.0.0/go.mod h1:dHtQlpGsu+cZNNAkkCN/P3hoUDHhCYQXV3UM06sGGrk=
github.com/hashicorp/go-rootcerts v1.0.0 h1:Rqb66Oo1X/eSV1x66xbDccZjhJigjg0+e82kpwzSwCI=
github.com/hashicorp/go-rootcerts v1.0.0/go.mod h1:K6zTfqpRlCUIjkwsN4Z+hiSfzSTQa6eBIzfwKfwNnHU=
github.com/hashicorp/go-sockaddr v1.0.0 h1:GeH6tui99pF4NJgfnhp+L6+FfobzVW3Ah46sLo0ICXs=
github.com/hashicorp/go-sockaddr v1.0.0/go.mod h1:7Xibr9yA9JjQq1JpNB2Vw7kxv8xerXegt+ozgdvDeDU=
github.com/hashicorp/go-syslog v1.0.0 h1:KaodqZuhUoZereWVIYmpUgZysurB1kBLX2j0MwMrUAE=
github.com/hashicorp/go-syslog v1.0.0/go.mod h1:qPfqrKkXGihmCqbJM2mZgkZGvKG1dFdvsLplgctolz4=
github.com/hashicorp/go-uuid v1.0.0/go.mod h1:6SBZvOh/SIDV7/2o3Jml5SYk/TvGqwFJ/bN7x4byOro=
github.com/hashicorp/go-uuid v1.0.1 h1:fv1ep09latC32wFoVwnqcnKJGnMSdBanPczbHAYm1BE=
github.com/hashicorp/go-uuid v1.0.1/go.mod h1:6SBZvOh/SIDV7/2o3Jml5SYk/TvGqwFJ/bN7x4byOro=
github.com/hashicorp/go.net v0.0.1 h1:sNCoNyDEvN1xa+X0baata4RdcpKwcMS6DH+xwfqPgjw=
github.com/hashicorp/go.net v0.0.1/go.mod h1:hjKkEWcCURg++eb33jQU7oqQcI9XDCnUzHA0oac0k90=
github.com/hashicorp/golang-lru v0.5.0 h1:CL2msUPvZTLb5O648aiLNJw3hnBxN2+1Jq8rCOH9wdo=
github.com/hashicorp/golang-lru v0.5.0/go.mod h1:/m3WP610KZHVQ1SGc6re/UDhFvYD7pJ4Ao+sR/qLZy8=
github.com/hashicorp/logutils v1.0.0 h1:dLEQVugN8vlakKOUE3ihGLTZJRB4j+M2cdTm/ORI65Y=
github.com/hashicorp/logutils v1.0.0/go.mod h1:QIAnNjmIWmVIIkWDTG1z5v++HQmx9WQRO+LraFDTW64=
github.com/hashicorp/mdns v1.0.0 h1:WhIgCr5a7AaVH6jPUwjtRuuE7/RDufnUvzIr48smyxs=
github.com/hashicorp/mdns v1.0.0/go.mod h1:tL+uN++7HEJ6SQLQ2/p+z2pH24WQKWjBPkE0mNTz8vQ=
github.com/hashicorp/memberlist v0.1.3 h1:EmmoJme1matNzb+hMpDuR/0sbJSUisxyqBGG676r31M=
github.com/hashicorp/memberlist v0.1.3/go.mod h1:ajVTdAv/9Im8oMAAj5G31PhhMCZJV2pPBoIllUwCN7I=
github.com/hashicorp/serf v0.8.2 h1:YZ7UKsJv+hKjqGVUUbtE3HNj79Eln2oQ75tniF6iPt0=
github.com/hashicorp/serf v0.8.2/go.mod h1:6hOLApaqBFA1NXqRQAsxw9QxuDEvNxSQRwA/JwenrHc=
github.com/mattn/go-colorable v0.0.9 h1:UVL0vNpWh04HeJXV0KLcaT7r06gOH2l4OW6ddYRUIY4=
github.com/mattn/go-colorable v0.0.9/go.mod h1:9vuHe8Xs5qXnSaW/c/ABM9alt+Vo+STaOChaDxuIBZU=
github.com/mattn/go-isatty v0.0.3 h1:ns/ykhmWi7G9O+8a448SecJU3nSMBXJfqQkl0upE1jI=
github.com/mattn/go-isatty v0.0.3/go.mod h1:M+lRXTBqGeGNdLjl/ufCoiOlB5xdOkqRJdNxMWT7Zi4=
github.com/miekg/dns v1.0.14 h1:9jZdLNd/P4+SfEJ0TNyxYpsK8N4GtfylBLqtbYN1sbA=
github.com/miekg/dns v1.0.14/go.mod h1:W1PPwlIAgtquWBMBEV9nkV9Cazfe8ScdGz/Lj7v3Nrg=
github.com/mitchellh/cli v1.0.0 h1:iGBIsUe3+HZ/AD/Vd7DErOt5sU9fa8Uj7A2s1aggv1Y=
github.com/mitchellh/cli v1.0.0/go.mod h1:hNIlj7HEI86fIcpObd7a0FcrxTWetlwJDGcceTlRvqc=
github.com/mitchellh/go-homedir v1.0.0 h1:vKb8ShqSby24Yrqr/yDYkuFz8d0WUjys40rvnGC8aR0=
github.com/mitchellh/go-homedir v1.0.0/go.mod h1:SfyaCUpYCn1Vlf4IUYiD9fPX4A5wJrkLzIz1N1q0pr0=
github.com/mitchellh/go-testing-interface v1.0.0 h1:fzU/JVNcaqHQEcVFAKeR41fkiLdIPrefOvVG1VZ96U0=
github.com/mitchellh/go-testing-interface v1.0.0/go.mod h1:kRemZodwjscx+RGhAo8eIhFbs2+BFgRtFPeD/KE+zxI=
github.com/mitchellh/gox v0.4.0 h1:lfGJxY7ToLJQjHHwi0EX6uYBdK78egf954SQl13PQJc=
github.com/mitchellh/gox v0.4.0/go.mod h1:Sd9lOJ0+aimLBi73mGofS1ycjY8lL3uZM3JPS42BGNg=
github.com/mitchellh/iochan v1.0.0 h1:C+X3KsSTLFVBr/tK1eYN/vs4rJcvsiLU338UhYPJWeY=
github.com/mitchellh/iochan v1.0.0/go.mod h1:JwYml1nuB7xOzsp52dPpHFffvOCDupsG0QubkSMEySY=
github.com/mitchellh/mapstructure v0.0.0-20160808181253-ca63d7c062ee/go.mod h1:FVVH3fgwuzCH5S8UJGiWEs2h04kUh9fWfEaFds41c1Y=
github.com/mitchellh/mapstructure v1.1.2 h1:fmNYVwqnSfB9mZU6OS2O6GsXM+wcskZDuKQzvN1EDeE=
github.com/mitchellh/mapstructure v1.1.2/go.mod h1:FVVH3fgwuzCH5S8UJGiWEs2h04kUh9fWfEaFds41c1Y=
github.com/pascaldekloe/goe v0.0.0-20180627143212-57f6aae5913c h1:Lgl0gzECD8GnQ5QCWA8o6BtfL6mDH5rQgM4/fX3avOs=
github.com/pascaldekloe/goe v0.0.0-20180627143212-57f6aae5913c/go.mod h1:lzWF7FIEvWOWxwDKqyGYQf6ZUaNfKdP144TG7ZOy1lc=
github.com/pkg/errors v0.8.1 h1:iURUrRGxPUNPdy5/HRSm+Yj6okJ6UtLINN0Q9M4+h3I=
github.com/pkg/errors v0.8.1/go.mod h1:bwawxfHBFNV+L2hUp1rHADufV3IMtnDRdf1r5NINEl0=
github.com/pmezard/go-difflib v1.0.0 h1:4DBwDE0NGyQoBHbLQYPwSUPoCMWR5BEzIk/f1lZbAQM=
github.com/pmezard/go-difflib v1.0.0/go.mod h1:iKH77koFhYxTK1pcRnkKkqfTogsbg7gZNVY4sRDYZ/4=
github.com/posener/complete v1.1.1 h1:ccV59UEOTzVDnDUEFdT95ZzHVZ+5+158q8+SJb2QV5w=
github.com/posener/complete v1.1.1/go.mod h1:em0nMJCgc9GFtwrmVmEMR/ZL6WyhyjMBndrE9hABlRI=
github.com/ryanuber/columnize v0.0.0-20160712163229-9b3edd62028f h1:UFr9zpz4xgTnIE5yIMtWAMngCdZ9p/+q6lTbgelo80M=
github.com/ryanuber/columnize v0.0.0-20160712163229-9b3edd62028f/go.mod h1:sm1tb6uqfes/u+d4ooFouqFdy9/2g9QGwK3SQygK0Ts=
github.com/sean-/seed v0.0.0-20170313163322-e2103e2c3529 h1:nn5Wsu0esKSJiIVhscUtVbo7ada43DJhG55ua/hjS5I=
github.com/sean-/seed v0.0.0-20170313163322-e2103e2c3529/go.mod h1:DxrIzT+xaE7yg65j358z/aeFdxmN0P9QXhEzd20vsDc=
github.com/stretchr/objx v0.1.0 h1:4G4v2dO3VZwixGIRoQ5Lfboy6nUhCyYzaqnIAPPhYs4=
github.com/stretchr/objx v0.1.0/go.mod h1:HFkY916IF+rwdDfMAkV7OtwuqBVzrE8GR6GFx+wExME=
github.com/stretchr/testify v1.2.2/go.mod h1:a8OnRcib4nhh0OaRAV+Yts87kKdq0PP7pXfy6kDkUVs=
github.com/stretchr/testify v1.3.0 h1:TivCn/peBQ7UY8ooIcPgZFpTNSz0Q2U6UrFlUfqbe0Q=
github.com/stretchr/testify v1.3.0/go.mod h1:M5WIy9Dh21IEIfnGCwXGc5bZfKNJtfHm1UVUgZn+9EI=
golang.org/x/crypto v0.0.0-20181029021203-45a5f77698d3 h1:KYQXGkl6vs02hK7pK4eIbw0NpNPedieTSTEiJ//bwGs=
golang.org/x/crypto v0.0.0-20181029021203-45a5f77698d3/go.mod h1:6SG95UA2DQfeDnfUPMdvaQW0Q7yPrPDi9nlGo2tz2b4=
golang.org/x/net v0.0.0-20181023162649-9b4f9f5ad519/go.mod h1:mL1N/T3taQHkDXs73rZJwtUhF3w3ftmwwsq0BUmARs4=
golang.org/x/net v0.0.0-20181201002055-351d144fa1fc h1:a3CU5tJYVj92DY2LaA1kUkrsqD5/3mLDhx2NcNqyW+0=
golang.org/x/net v0.0.0-20181201002055-351d144fa1fc/go.mod h1:mL1N/T3taQHkDXs73rZJwtUhF3w3ftmwwsq0BUmARs4=
golang.org/x/sync v0.0.0-20181221193216-37e7f081c4d4 h1:YUO/7uOKsKeq9UokNS62b8FYywz3ker1l1vDZRCRefw=
golang.org/x/sync v0.0.0-20181221193216-37e7f081c4d4/go.mod h1:RxMgew5VJxzue5/jJTE5uejpjVlOe/izrB70Jof72aM=
golang.org/x/sys v0.0.0-20180823144017-11551d06cbcc/go.mod h1:STP8DvDyc/dI5b8T5hshtkjS+E42TnysNCUPdjciGhY=
golang.org/x/sys v0.0.0-20181026203630-95b1ffbd15a5 h1:x6r4Jo0KNzOOzYd8lbcRsqjuqEASK6ob3auvWYM4/8U=
golang.org/x/sys v0.0.0-20181026203630-95b1ffbd15a5/go.mod h1:STP8DvDyc/dI5b8T5hshtkjS+E42TnysNCUPdjciGhY=
                """
            ),
            "BUILD": "go_mod(name='mod')",
        }
    )
    input_digest = rule_runner.request(Digest, [PathGlobs(["go.mod", "go.sum"])])
    _module_info = rule_runner.request(
        ThirdPartyModuleInfo,
        [ThirdPartyModuleInfoRequest("github.com/hashicorp/consul/api", "v1.3.0", input_digest)],
    )


def test_determine_pkg_info_unsupported_sources(rule_runner: RuleRunner) -> None:
    # `golang.org/x/mobile/bind/objc` uses `.h` files on both Linux and macOS.
    mobile_version = "v0.0.0-20210924032853-1c027f395ef7"
    input_digest = rule_runner.make_snapshot(
        {
            "go.mod": dedent(
                f"""\
                module example.com/unsupported
                go 1.17
                require golang.org/x/mobile {mobile_version}
                """
            ),
            "go.sum": dedent(
                """\
                github.com/BurntSushi/xgb v0.0.0-20160522181843-27f122750802 h1:1BDTz0u9nC3//pOCMdNH+CiXJVYJh5UQNCOBG7jbELc=
                github.com/BurntSushi/xgb v0.0.0-20160522181843-27f122750802/go.mod h1:IVnqGOEym/WlBOVXweHU+Q+/VP0lqqI8lqeDx9IjBqo=
                github.com/yuin/goldmark v1.3.5 h1:dPmz1Snjq0kmkz159iL7S6WzdahUTHnHB5M56WFVifs=
                github.com/yuin/goldmark v1.3.5/go.mod h1:mwnBkeHKe2W/ZEtQ+71ViKU8L12m81fl3OWwC1Zlc8k=
                golang.org/x/crypto v0.0.0-20190308221718-c2843e01d9a2/go.mod h1:djNgcEr1/C05ACkg1iLfiJU5Ep61QUkGW8qpdssI0+w=
                golang.org/x/crypto v0.0.0-20190510104115-cbcb75029529/go.mod h1:yigFU9vqHzYiE8UmvKecakEJjdnWj3jj499lnFckfCI=
                golang.org/x/crypto v0.0.0-20191011191535-87dc89f01550 h1:ObdrDkeb4kJdCP557AjRjq69pTHfNouLtWZG7j9rPN8=
                golang.org/x/crypto v0.0.0-20191011191535-87dc89f01550/go.mod h1:yigFU9vqHzYiE8UmvKecakEJjdnWj3jj499lnFckfCI=
                golang.org/x/exp v0.0.0-20190731235908-ec7cb31e5a56 h1:estk1glOnSVeJ9tdEZZc5mAMDZk5lNJNyJ6DvrBkTEU=
                golang.org/x/exp v0.0.0-20190731235908-ec7cb31e5a56/go.mod h1:JhuoJpWY28nO4Vef9tZUw9qufEGTyX1+7lmHxV5q5G4=
                golang.org/x/image v0.0.0-20190227222117-0694c2d4d067/go.mod h1:kZ7UVZpmo3dzQBMxlp+ypCbDeSB+sBbTgSJuh5dn5js=
                golang.org/x/image v0.0.0-20190802002840-cff245a6509b h1:+qEpEAPhDZ1o0x3tHzZTQDArnOixOzGD9HUJfcg0mb4=
                golang.org/x/image v0.0.0-20190802002840-cff245a6509b/go.mod h1:FeLwcggjj3mMvU+oOTbSwawSJRM1uh48EjtB4UJZlP0=
                golang.org/x/mobile v0.0.0-20190312151609-d3739f865fa6/go.mod h1:z+o9i4GpDbdi3rU15maQ/Ox0txvL9dWGYEHz965HBQE=
                golang.org/x/mobile v0.0.0-20210924032853-1c027f395ef7 h1:CyFUjc175y/mbMjxe+WdqI72jguLyjQChKCDe9mfTvg=
                golang.org/x/mobile v0.0.0-20210924032853-1c027f395ef7/go.mod h1:c4YKU3ZylDmvbw+H/PSvm42vhdWbuxCzbonauEAP9B8=
                golang.org/x/mod v0.1.0/go.mod h1:0QHyrYULN0/3qlju5TqG8bIK38QM8yzMo5ekMj3DlcY=
                golang.org/x/mod v0.4.2 h1:Gz96sIWK3OalVv/I/qNygP42zyoKp3xptRVCWRFEBvo=
                golang.org/x/mod v0.4.2/go.mod h1:s0Qsj1ACt9ePp/hMypM3fl4fZqREWJwdYDEqhRiZZUA=
                golang.org/x/net v0.0.0-20190311183353-d8887717615a/go.mod h1:t9HGtf8HONx5eT2rtn7q6eTqICYqUVnKs3thJo3Qplg=
                golang.org/x/net v0.0.0-20190404232315-eb5bcb51f2a3/go.mod h1:t9HGtf8HONx5eT2rtn7q6eTqICYqUVnKs3thJo3Qplg=
                golang.org/x/net v0.0.0-20190620200207-3b0461eec859/go.mod h1:z5CRVTTTmAJ677TzLLGU+0bjPO0LkuOLi4/5GtJWs/s=
                golang.org/x/net v0.0.0-20210405180319-a5a99cb37ef4 h1:4nGaVu0QrbjT/AK2PRLuQfQuh6DJve+pELhqTdAj3x0=
                golang.org/x/net v0.0.0-20210405180319-a5a99cb37ef4/go.mod h1:p54w0d4576C0XHj96bSt6lcn1PtDYWL6XObtHCRCNQM=
                golang.org/x/sync v0.0.0-20190423024810-112230192c58/go.mod h1:RxMgew5VJxzue5/jJTE5uejpjVlOe/izrB70Jof72aM=
                golang.org/x/sync v0.0.0-20210220032951-036812b2e83c h1:5KslGYwFpkhGh+Q16bwMP3cOontH8FOep7tGV86Y7SQ=
                golang.org/x/sync v0.0.0-20210220032951-036812b2e83c/go.mod h1:RxMgew5VJxzue5/jJTE5uejpjVlOe/izrB70Jof72aM=
                golang.org/x/sys v0.0.0-20190215142949-d0b11bdaac8a/go.mod h1:STP8DvDyc/dI5b8T5hshtkjS+E42TnysNCUPdjciGhY=
                golang.org/x/sys v0.0.0-20190412213103-97732733099d/go.mod h1:h1NjWce9XRLGQEsW7wpKNCjG9DtNlClVuFLEZdDNbEs=
                golang.org/x/sys v0.0.0-20201119102817-f84b799fce68/go.mod h1:h1NjWce9XRLGQEsW7wpKNCjG9DtNlClVuFLEZdDNbEs=
                golang.org/x/sys v0.0.0-20210330210617-4fbd30eecc44/go.mod h1:h1NjWce9XRLGQEsW7wpKNCjG9DtNlClVuFLEZdDNbEs=
                golang.org/x/sys v0.0.0-20210510120138-977fb7262007 h1:gG67DSER+11cZvqIMb8S8bt0vZtiN6xWYARwirrOSfE=
                golang.org/x/sys v0.0.0-20210510120138-977fb7262007/go.mod h1:oPkhp1MJrh7nUepCBck5+mAzfO9JrbApNNgaTdGDITg=
                golang.org/x/term v0.0.0-20201126162022-7de9c90e9dd1 h1:v+OssWQX+hTHEmOBgwxdZxK4zHq3yOs8F9J7mk0PY8E=
                golang.org/x/term v0.0.0-20201126162022-7de9c90e9dd1/go.mod h1:bj7SfCRtBDWHUb9snDiAeCFNEtKQo2Wmx5Cou7ajbmo=
                golang.org/x/text v0.3.0/go.mod h1:NqM8EUOU14njkJ3fqMW+pc6Ldnwhi/IjpwHt7yyuwOQ=
                golang.org/x/text v0.3.3 h1:cokOdA+Jmi5PJGXLlLllQSgYigAEfHXJAERHVMaCc2k=
                golang.org/x/text v0.3.3/go.mod h1:5Zoc/QRtKVWzQhOtBMvqHzDpF6irO9z98xDceosuGiQ=
                golang.org/x/text v0.3.7 h1:olpwvP2KacW1ZWvsR7uQhoyTYvKAupfQrRGBFM352Gk=
                golang.org/x/text v0.3.7/go.mod h1:u+2+/6zg+i71rQMx5EYifcz6MCKuco9NR6JIITiCfzQ=
                golang.org/x/tools v0.0.0-20180917221912-90fa682c2a6e h1:FDhOuMEY4JVRztM/gsbk+IKUQ8kj74bxZrgw87eMMVc=
                golang.org/x/tools v0.0.0-20180917221912-90fa682c2a6e/go.mod h1:n7NCudcB/nEzxVGmLbDWY5pfWTLqBcC2KZ6jyYvM4mQ=
                golang.org/x/tools v0.0.0-20190312151545-0bb0c0a6e846/go.mod h1:LCzVGOaR6xXOjkQ3onu1FJEFr0SW1gC7cKk1uF8kGRs=
                golang.org/x/tools v0.0.0-20191119224855-298f0cb1881e/go.mod h1:b+2E5dAYhXwXZwtnZ6UAqBI28+e2cm9otk0dWdXHAEo=
                golang.org/x/tools v0.1.2 h1:kRBLX7v7Af8W7Gdbbc908OJcdgtK8bOz9Uaj8/F1ACA=
                golang.org/x/tools v0.1.2/go.mod h1:o0xws9oXOQQZyjljx8fwUC0k7L1pTE6eaCbjGeHmOkk=
                golang.org/x/xerrors v0.0.0-20190717185122-a985d3407aa7/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                golang.org/x/xerrors v0.0.0-20191011141410-1b5146add898/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                golang.org/x/xerrors v0.0.0-20200804184101-5ec99f83aff1 h1:go1bK/D/BFZV2I8cIQd1NKEZ+0owSTG1fDTci4IqFcE=
                golang.org/x/xerrors v0.0.0-20200804184101-5ec99f83aff1/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                """
            ),
        }
    ).digest

    # Nothing should error when computing `ThirdPartyModuleInfo`, we only create an exception to
    # maybe raise later.
    module_info = rule_runner.request(
        ThirdPartyModuleInfo,
        [ThirdPartyModuleInfoRequest("golang.org/x/mobile", mobile_version, input_digest)],
    )
    assert module_info["golang.org/x/mobile/bind/objc"].unsupported_sources_error is not None

    # Error when requesting the `ThirdPartyPkgInfo`.
    with engine_error(NotImplementedError):
        rule_runner.request(
            ThirdPartyPkgInfo,
            [
                ThirdPartyPkgInfoRequest(
                    "golang.org/x/mobile/bind/objc",
                    "golang.org/x/mobile",
                    mobile_version,
                    input_digest,
                )
            ],
        )
