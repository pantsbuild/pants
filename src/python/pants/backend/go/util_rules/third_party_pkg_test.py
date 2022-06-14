# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.go_sources import load_go_binary
from pants.backend.go.target_types import GoModTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    first_party_pkg,
    go_mod,
    import_analysis,
    link,
    sdk,
    third_party_pkg,
)
from pants.backend.go.util_rules.third_party_pkg import (
    AllThirdPartyPackages,
    AllThirdPartyPackagesRequest,
    ThirdPartyPkgAnalysis,
    ThirdPartyPkgAnalysisRequest,
)
from pants.engine.fs import Digest, Snapshot
from pants.engine.process import ProcessExecutionFailure
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            *third_party_pkg.rules(),
            *first_party_pkg.rules(),
            *load_go_binary.rules(),
            *build_pkg.rules(),
            *import_analysis.rules(),
            *link.rules(),
            *assembly.rules(),
            *target_type_rules.rules(),
            *go_mod.rules(),
            QueryRule(AllThirdPartyPackages, [AllThirdPartyPackagesRequest]),
            QueryRule(ThirdPartyPkgAnalysis, [ThirdPartyPkgAnalysisRequest]),
        ],
        target_types=[GoModTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


GO_MOD = dedent(
    """\
    module example.com/third-party-module
    go 1.16

    require github.com/google/uuid v1.3.0
    require (
        rsc.io/quote v1.5.2
        golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c // indirect
        rsc.io/sampler v1.3.0 // indirect
    )
    """
)

GO_SUM = dedent(
    """\
    github.com/google/uuid v1.3.0 h1:t6JiXgmwXMjEs8VusXIJk2BXHsn+wx8BZdTaoZ5fu7I=
    github.com/google/uuid v1.3.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
    golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c h1:qgOY6WgZOaTkIIMiVjBQcw93ERBE4m30iBm00nkL0i8=
    golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c/go.mod h1:NqM8EUOU14njkJ3fqMW+pc6Ldnwhi/IjpwHt7yyuwOQ=
    rsc.io/quote v1.5.2 h1:w5fcysjrx7yqtD/aO+QwRjYZOKnaM9Uh2b40tElTs3Y=
    rsc.io/quote v1.5.2/go.mod h1:LzX7hefJvL54yjefDEDHNONDjII0t9xZLPXsUe+TKr0=
    rsc.io/sampler v1.3.0 h1:7uVkIFmeBqHfdjD+gZwtXXI+RODJ2Wc4O7MPEh/QiW4=
    rsc.io/sampler v1.3.0/go.mod h1:T1hPZKmBbMNahiBKFy5HrXp6adAjACjK9JXDnKaTXpA=
    """
)


def set_up_go_mod(rule_runner: RuleRunner, go_mod: str, go_sum: str) -> Digest:
    return rule_runner.make_snapshot({"go.mod": go_mod, "go.sum": go_sum}).digest


def test_download_and_analyze_all_packages(rule_runner: RuleRunner) -> None:
    input_digest = rule_runner.make_snapshot({"go.mod": GO_MOD, "go.sum": GO_SUM}).digest
    all_packages = rule_runner.request(
        AllThirdPartyPackages, [AllThirdPartyPackagesRequest(input_digest, "go.mod")]
    )
    assert set(all_packages.import_paths_to_pkg_info.keys()) == {
        "golang.org/x/text/encoding/japanese",
        "golang.org/x/text/message/catalog",
        "golang.org/x/text/internal/testtext",
        "golang.org/x/text/encoding/ianaindex",
        "golang.org/x/text/cmd/gotext",
        "golang.org/x/text/width",
        "golang.org/x/text/internal/format",
        "rsc.io/sampler",
        "golang.org/x/text/internal/tag",
        "golang.org/x/text/unicode/norm",
        "golang.org/x/text/number",
        "golang.org/x/text/transform",
        "golang.org/x/text/internal",
        "golang.org/x/text/internal/utf8internal",
        "golang.org/x/text/language/display",
        "golang.org/x/text/internal/stringset",
        "golang.org/x/text/encoding/korean",
        "golang.org/x/text/internal/triegen",
        "golang.org/x/text/secure/bidirule",
        "golang.org/x/text/secure/precis",
        "golang.org/x/text/language",
        "golang.org/x/text/encoding/unicode/utf32",
        "golang.org/x/text/internal/colltab",
        "golang.org/x/text/unicode/rangetable",
        "golang.org/x/text/encoding/htmlindex",
        "golang.org/x/text/internal/export/idna",
        "golang.org/x/text/encoding/charmap",
        "golang.org/x/text/unicode/cldr",
        "golang.org/x/text/secure",
        "golang.org/x/text/internal/ucd",
        "golang.org/x/text/feature/plural",
        "golang.org/x/text/unicode",
        "golang.org/x/text/encoding/traditionalchinese",
        "golang.org/x/text/runes",
        "golang.org/x/text/internal/catmsg",
        "rsc.io/quote/buggy",
        "golang.org/x/text/encoding/simplifiedchinese",
        "golang.org/x/text/cases",
        "golang.org/x/text/encoding/internal",
        "github.com/google/uuid",
        "golang.org/x/text/encoding/internal/enctest",
        "golang.org/x/text/collate/build",
        "golang.org/x/text",
        "golang.org/x/text/unicode/bidi",
        "golang.org/x/text/search",
        "golang.org/x/text/unicode/runenames",
        "golang.org/x/text/message",
        "golang.org/x/text/encoding",
        "golang.org/x/text/encoding/unicode",
        "rsc.io/quote",
        "golang.org/x/text/currency",
        "golang.org/x/text/internal/number",
        "golang.org/x/text/collate/tools/colcmp",
        "golang.org/x/text/encoding/internal/identifier",
        "golang.org/x/text/collate",
        "golang.org/x/text/internal/gen",
    }

    def assert_pkg_info(
        import_path: str,
        dir_path: str,
        imports: tuple[str, ...],
        go_files: tuple[str, ...],
        extra_files: tuple[str, ...],
        minimum_go_version: str | None,
    ) -> None:
        assert import_path in all_packages.import_paths_to_pkg_info
        pkg_info = all_packages.import_paths_to_pkg_info[import_path]
        assert pkg_info.import_path == import_path
        assert pkg_info.dir_path == dir_path
        assert pkg_info.imports == imports
        assert pkg_info.go_files == go_files
        assert not pkg_info.s_files
        snapshot = rule_runner.request(Snapshot, [pkg_info.digest])
        assert set(snapshot.files) == {
            os.path.join(dir_path, file_name) for file_name in (*go_files, *extra_files)
        }
        assert pkg_info.minimum_go_version == minimum_go_version

    assert_pkg_info(
        import_path="github.com/google/uuid",
        dir_path="gopath/pkg/mod/github.com/google/uuid@v1.3.0",
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
        extra_files=(
            ".travis.yml",
            "CONTRIBUTING.md",
            "CONTRIBUTORS",
            "LICENSE",
            "README.md",
            "go.mod",
            "json_test.go",
            "node_js.go",
            "null_test.go",
            "seq_test.go",
            "sql_test.go",
            "uuid_test.go",
        ),
        minimum_go_version=None,
    )
    assert_pkg_info(
        import_path="golang.org/x/text/unicode/bidi",
        dir_path="gopath/pkg/mod/golang.org/x/text@v0.0.0-20170915032832-14c0d48ead0c/unicode/bidi",
        imports=("container/list", "fmt", "log", "sort", "unicode/utf8"),
        go_files=("bidi.go", "bracket.go", "core.go", "prop.go", "tables.go", "trieval.go"),
        extra_files=(
            "core_test.go",
            "gen.go",
            "gen_ranges.go",
            "gen_trieval.go",
            "ranges_test.go",
            "tables_test.go",
        ),
        minimum_go_version=None,
    )


def test_invalid_go_sum(rule_runner: RuleRunner) -> None:
    digest = set_up_go_mod(
        rule_runner,
        dedent(
            """\
            module example.com/third-party-module
            go 1.17
            require github.com/google/uuid v1.3.0
            """
        ),
        dedent(
            """\
            github.com/google/uuid v1.3.0 h1:00000gmwXMjEs8VusXIJk2BXHsn+wx8BZdTaoZ5fu7I=
            github.com/google/uuid v1.3.0/go.mod h1:00000e4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
            """
        ),
    )
    with engine_error(ProcessExecutionFailure, contains="SECURITY ERROR"):
        rule_runner.request(AllThirdPartyPackages, [AllThirdPartyPackagesRequest(digest, "go.mod")])


@pytest.mark.skip("broken test")
def test_missing_go_sum(rule_runner: RuleRunner) -> None:
    digest = set_up_go_mod(
        rule_runner,
        dedent(
            """\
            module example.com/third-party-module
            go 1.17
            require github.com/google/uuid v1.3.0
            """
        ),
        # `go.sum` is for a different module.
        dedent(
            """\
            cloud.google.com/go v0.26.0 h1:e0WKqKTd5BnrG8aKH3J3h+QvEIQtSUcf2n5UZ5ZgLtQ=
            cloud.google.com/go v0.26.0/go.mod h1:aQUYkXzVsufM+DwF1aE+0xfcU+56JwCaLick0ClmMTw=
            """
        ),
    )
    with engine_error(contains="github.com/google/uuid@v1.3.0: missing go.sum entry"):
        rule_runner.request(AllThirdPartyPackages, [AllThirdPartyPackagesRequest(digest, "go.mod")])
        assert False, "should not get here!"


@pytest.mark.skip("broken test")
def test_stale_go_mod(rule_runner: RuleRunner) -> None:
    digest = set_up_go_mod(
        rule_runner,
        # Go 1.17+ expects indirect dependencies to be included in the `go.mod`, i.e.
        # `golang.org/x/xerrors `.
        dedent(
            """\
            module example.com/third-party-module
            go 1.17
            require github.com/google/go-cmp v0.5.6
            """
        ),
        dedent(
            """\
            github.com/google/go-cmp v0.5.6 h1:BKbKCqvP6I+rmFHt06ZmyQtvB8xAkWdhFyr0ZUNZcxQ=
            github.com/google/go-cmp v0.5.6/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
            golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 h1:E7g+9GITq07hpfrRu66IVDexMakfv52eLZ2CXBWiKr4=
            golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
            """
        ),
    )
    with engine_error(ProcessExecutionFailure, contains="updates to go.mod needed"):
        rule_runner.request(AllThirdPartyPackages, [AllThirdPartyPackagesRequest(digest, "go.mod")])
        assert False, "should not get here!"


def test_pkg_missing(rule_runner: RuleRunner) -> None:
    digest = set_up_go_mod(rule_runner, GO_MOD, GO_SUM)
    with engine_error(
        AssertionError, contains="The package `another_project.org/foo` was not downloaded"
    ):
        rule_runner.request(
            ThirdPartyPkgAnalysis,
            [ThirdPartyPkgAnalysisRequest("another_project.org/foo", digest, "go.mod")],
        )


def test_module_with_no_packages(rule_runner) -> None:
    digest = set_up_go_mod(
        rule_runner,
        dedent(
            """\
            module example.com/third-party-module
            go 1.17
            require github.com/Azure/go-autorest v13.3.2+incompatible
            """
        ),
        dedent(
            """\
            github.com/Azure/go-autorest v13.3.2+incompatible h1:VxzPyuhtnlBOzc4IWCZHqpyH2d+QMLQEuy3wREyY4oc=
            github.com/Azure/go-autorest v13.3.2+incompatible/go.mod h1:r+4oMnoxhatjLLJ6zxSWATqVooLgysK6ZNox3g/xq24=
            """
        ),
    )
    all_packages = rule_runner.request(
        AllThirdPartyPackages, [AllThirdPartyPackagesRequest(digest, "go.mod")]
    )
    assert not all_packages.import_paths_to_pkg_info


def test_unsupported_sources(rule_runner: RuleRunner) -> None:
    # `golang.org/x/mobile/bind/objc` uses `.h` files on both Linux and macOS.
    digest = set_up_go_mod(
        rule_runner,
        dedent(
            """\
            module example.com/unsupported
            go 1.16
            require golang.org/x/mobile v0.0.0-20210924032853-1c027f395ef7
            """
        ),
        dedent(
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
    )
    pkg_info = rule_runner.request(
        ThirdPartyPkgAnalysis,
        [ThirdPartyPkgAnalysisRequest("golang.org/x/mobile/bind/objc", digest, "go.mod")],
    )
    assert pkg_info.error is not None


def test_determine_pkg_info_module_with_replace_directive(rule_runner: RuleRunner) -> None:
    """Regression test for https://github.com/pantsbuild/pants/issues/13138."""
    digest = set_up_go_mod(
        rule_runner,
        dedent(
            """\
            module example.com/third-party-module
            go 1.16
            require github.com/hashicorp/consul/api v1.3.0
            """
        ),
        dedent(
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
    )
    pkg_info = rule_runner.request(
        ThirdPartyPkgAnalysis,
        [ThirdPartyPkgAnalysisRequest("github.com/hashicorp/consul/api", digest, "go.mod")],
    )
    assert pkg_info.dir_path == "gopath/pkg/mod/github.com/hashicorp/consul/api@v1.3.0"
    assert "raw.go" in pkg_info.go_files


def test_ambiguous_package(rule_runner: RuleRunner) -> None:
    digest = set_up_go_mod(
        rule_runner,
        dedent(
            """\
            module example.com/third-party-module
            go 1.16
            require github.com/ugorji/go v1.1.4
            require github.com/ugorji/go/codec v0.0.0-20181204163529-d75b2dcb6bc8
            """
        ),
        dedent(
            """\
            github.com/ugorji/go v1.1.4 h1:j4s+tAvLfL3bZyefP2SEWmhBzmuIlH/eqNuPdFPgngw=
            github.com/ugorji/go v1.1.4/go.mod h1:uQMGLiO92mf5W77hV/PUCpI3pbzQx3CRekS0kk+RGrc=
            github.com/ugorji/go/codec v0.0.0-20181204163529-d75b2dcb6bc8 h1:3SVOIvH7Ae1KRYyQWRjXWJEA9sS/c/pjvH++55Gr648=
            github.com/ugorji/go/codec v0.0.0-20181204163529-d75b2dcb6bc8/go.mod h1:VFNgLljTbGfSG7qAOspJ7OScBnGdDN/yBr0sguwnwf0=
            """
        ),
    )
    pkg_info = rule_runner.request(
        ThirdPartyPkgAnalysis,
        [ThirdPartyPkgAnalysisRequest("github.com/ugorji/go/codec", digest, "go.mod")],
    )
    assert pkg_info.error is None
    assert (
        pkg_info.dir_path
        == "gopath/pkg/mod/github.com/ugorji/go/codec@v0.0.0-20181204163529-d75b2dcb6bc8"
    )
    assert "encode.go" in pkg_info.go_files
