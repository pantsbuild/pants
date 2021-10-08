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


def test_unsupported_sources(rule_runner: RuleRunner) -> None:
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
