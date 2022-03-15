# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent
from typing import Iterable

import pytest

from pants.backend.codegen.protobuf import target_types
from pants.backend.codegen.protobuf.go.rules import (
    GenerateGoFromProtobufRequest,
    parse_go_package_option,
)
from pants.backend.codegen.protobuf.go.rules import rules as go_protobuf_rules
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourceField,
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
)
from pants.backend.codegen.protobuf.target_types import rules as protobuf_target_types_rules
from pants.backend.go import target_type_rules
from pants.backend.go.goals import test
from pants.backend.go.goals.test import GoTestFieldSet
from pants.backend.go.target_types import GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    build_pkg_target,
    first_party_pkg,
    go_mod,
    link,
    sdk,
    tests_analysis,
    third_party_pkg,
)
from pants.build_graph.address import Address
from pants.core.goals.test import TestResult
from pants.core.util_rules import config_files, source_files, stripped_source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import QueryRule
from pants.engine.target import GeneratedSources, HydratedSources, HydrateSourcesRequest
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner, logging


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *protobuf_target_types_rules(),
            *stripped_source_files.rules(),
            *go_protobuf_rules(),
            *sdk.rules(),
            *target_types.rules(),
            # Rules needed to run Go unit test.
            *test.rules(),
            *assembly.rules(),
            *build_pkg.rules(),
            *build_pkg_target.rules(),
            *first_party_pkg.rules(),
            *go_mod.rules(),
            *link.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            *tests_analysis.rules(),
            *third_party_pkg.rules(),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GenerateGoFromProtobufRequest]),
            QueryRule(DigestContents, (Digest,)),
            QueryRule(TestResult, (GoTestFieldSet,)),
        ],
        target_types=[
            GoModTarget,
            GoPackageTarget,
            ProtobufSourceTarget,
            ProtobufSourcesGeneratorTarget,
        ],
    )
    rule_runner.set_options(
        [],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


def assert_files_generated(
    rule_runner: RuleRunner,
    address: Address,
    *,
    expected_files: list[str],
    source_roots: list[str],
    extra_args: Iterable[str] = (),
) -> None:
    args = [f"--source-root-patterns={repr(source_roots)}", *extra_args]
    rule_runner.set_options(args, env_inherit=PYTHON_BOOTSTRAP_ENV)
    tgt = rule_runner.get_target(address)
    protocol_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[ProtobufSourceField])]
    )
    generated_sources = rule_runner.request(
        GeneratedSources, [GenerateGoFromProtobufRequest(protocol_sources.snapshot, tgt)]
    )
    assert set(generated_sources.snapshot.files) == set(expected_files)


def test_extracts_go_package() -> None:
    import_path = parse_go_package_option("""option go_package = "example.com/dir1";""".encode())
    assert import_path == "example.com/dir1"


@logging
def test_generates_go(rule_runner: RuleRunner) -> None:
    # This tests a few things:
    #  * We generate the correct file names.
    #  * Protobuf files can import other protobuf files, and those can import others
    #    (transitive dependencies). We'll only generate the requested target, though.
    #  * We can handle multiple source roots, which need to be preserved in the final output.
    rule_runner.write_files(
        {
            "src/protobuf/dir1/f.proto": dedent(
                """\
                syntax = "proto3";

                option go_package = "example.com/dir1";

                package dir1;

                message Person {
                  string name = 1;
                  int32 id = 2;
                  string email = 3;
                }
                """
            ),
            "src/protobuf/dir1/f2.proto": dedent(
                """\
                syntax = "proto3";

                option go_package = "example.com/dir1";

                package dir1;

                message Place {
                  string town = 1;
                  string country = 2;
                }
                """
            ),
            "src/protobuf/dir1/BUILD": dedent(
                """\
                protobuf_sources()
                """
            ),
            "src/protobuf/dir2/f.proto": dedent(
                """\
                syntax = "proto3";

                option go_package = "example.com/dir2";

                package dir2;

                import "dir1/f.proto";

                message Employee {
                  dir1.Person self = 1;
                  dir1.Person manager = 2;
                }
                """
            ),
            "src/protobuf/dir2/BUILD": "protobuf_sources(dependencies=['src/protobuf/dir1'])",
            # Test another source root.
            "tests/protobuf/test_protos/f.proto": dedent(
                """\
                syntax = "proto3";

                option go_package = "example.com/test_protos";

                package test_protos;

                import "dir2/f.proto";
                """
            ),
            "tests/protobuf/test_protos/BUILD": (
                "protobuf_sources(dependencies=['src/protobuf/dir2'])"
            ),
            "src/go/people/BUILD": dedent(
                """\
                go_mod(name="mod")
                go_package(name="pkg", dependencies=["src/protobuf/dir1", "src/protobuf/dir2"])
                """
            ),
            "src/go/people/go.mod": dedent(
                """\
                module example.com/people
                require (
                \tgithub.com/golang/protobuf v1.5.2
                \tgoogle.golang.org/genproto v0.0.0-20200526211855-cb27e3aa2013
                \tgoogle.golang.org/protobuf v1.27.1
                )
                """
            ),
            "src/go/people/go.sum": dedent(
                """\
                cloud.google.com/go v0.26.0 h1:e0WKqKTd5BnrG8aKH3J3h+QvEIQtSUcf2n5UZ5ZgLtQ=
                cloud.google.com/go v0.26.0/go.mod h1:aQUYkXzVsufM+DwF1aE+0xfcU+56JwCaLick0ClmMTw=
                github.com/BurntSushi/toml v0.3.1 h1:WXkYYl6Yr3qBf1K79EBnL4mak0OimBfB0XUf9Vl28OQ=
                github.com/BurntSushi/toml v0.3.1/go.mod h1:xHWCNGjB5oqiDr8zfno3MHue2Ht5sIBksp03qcyfWMU=
                github.com/census-instrumentation/opencensus-proto v0.2.1 h1:glEXhBS5PSLLv4IXzLA5yPRVX4bilULVyxxbrfOtDAk=
                github.com/census-instrumentation/opencensus-proto v0.2.1/go.mod h1:f6KPmirojxKA12rnyqOA5BBL4O983OfeGPqjHWSTneU=
                github.com/client9/misspell v0.3.4 h1:ta993UF76GwbvJcIo3Y68y/M3WxlpEHPWIGDkJYwzJI=
                github.com/client9/misspell v0.3.4/go.mod h1:qj6jICC3Q7zFZvVWo7KLAzC3yx5G7kyvSDkc90ppPyw=
                github.com/envoyproxy/go-control-plane v0.9.1-0.20191026205805-5f8ba28d4473 h1:4cmBvAEBNJaGARUEs3/suWRyfyBfhf7I60WBZq+bv2w=
                github.com/envoyproxy/go-control-plane v0.9.1-0.20191026205805-5f8ba28d4473/go.mod h1:YTl/9mNaCwkRvm6d1a2C3ymFceY/DCBVvsKhRF0iEA4=
                github.com/envoyproxy/protoc-gen-validate v0.1.0 h1:EQciDnbrYxy13PgWoY8AqoxGiPrpgBZ1R8UNe3ddc+A=
                github.com/envoyproxy/protoc-gen-validate v0.1.0/go.mod h1:iSmxcyjqTsJpI2R4NaDN7+kN2VEUnK/pcBlmesArF7c=
                github.com/golang/glog v0.0.0-20160126235308-23def4e6c14b h1:VKtxabqXZkF25pY9ekfRL6a582T4P37/31XEstQ5p58=
                github.com/golang/glog v0.0.0-20160126235308-23def4e6c14b/go.mod h1:SBH7ygxi8pfUlaOkMMuAQtPIUF8ecWP5IEl/CR7VP2Q=
                github.com/golang/mock v1.1.1 h1:G5FRp8JnTd7RQH5kemVNlMeyXQAztQ3mOWV95KxsXH8=
                github.com/golang/mock v1.1.1/go.mod h1:oTYuIxOrZwtPieC+H1uAHpcLFnEyAGVDL/k47Jfbm0A=
                github.com/golang/protobuf v1.2.0/go.mod h1:6lQm79b+lXiMfvg/cZm0SGofjICqVBUtrP5yJMmIC1U=
                github.com/golang/protobuf v1.3.2/go.mod h1:6lQm79b+lXiMfvg/cZm0SGofjICqVBUtrP5yJMmIC1U=
                github.com/golang/protobuf v1.4.0-rc.1/go.mod h1:ceaxUfeHdC40wWswd/P6IGgMaK3YpKi5j83Wpe3EHw8=
                github.com/golang/protobuf v1.4.0-rc.1.0.20200221234624-67d41d38c208/go.mod h1:xKAWHe0F5eneWXFV3EuXVDTCmh+JuBKY0li0aMyXATA=
                github.com/golang/protobuf v1.4.0-rc.2/go.mod h1:LlEzMj4AhA7rCAGe4KMBDvJI+AwstrUpVNzEA03Pprs=
                github.com/golang/protobuf v1.4.0-rc.4.0.20200313231945-b860323f09d0/go.mod h1:WU3c8KckQ9AFe+yFwt9sWVRKCVIyN9cPHBJSNnbL67w=
                github.com/golang/protobuf v1.4.0/go.mod h1:jodUvKwWbYaEsadDk5Fwe5c77LiNKVO9IDvqG2KuDX0=
                github.com/golang/protobuf v1.4.1/go.mod h1:U8fpvMrcmy5pZrNK1lt4xCsGvpyWQ/VVv6QDs8UjoX8=
                github.com/golang/protobuf v1.5.0/go.mod h1:FsONVRAS9T7sI+LIUmWTfcYkHO4aIWwzhcaSAoJOfIk=
                github.com/golang/protobuf v1.5.2 h1:ROPKBNFfQgOUMifHyP+KYbvpjbdoFNs+aK7DXlji0Tw=
                github.com/golang/protobuf v1.5.2/go.mod h1:XVQd3VNwM+JqD3oG2Ue2ip4fOMUkwXdXDdiuN0vRsmY=
                github.com/google/go-cmp v0.2.0/go.mod h1:oXzfMopK8JAjlY9xF4vHSVASa0yLyX7SntLO5aqRK0M=
                github.com/google/go-cmp v0.3.0/go.mod h1:8QqcDgzrUqlUb/G2PQTWiueGozuR1884gddMywk6iLU=
                github.com/google/go-cmp v0.3.1/go.mod h1:8QqcDgzrUqlUb/G2PQTWiueGozuR1884gddMywk6iLU=
                github.com/google/go-cmp v0.4.0/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
                github.com/google/go-cmp v0.5.5 h1:Khx7svrCpmxxtHBq5j2mp/xVjsi8hQMfNLvJFAlrGgU=
                github.com/google/go-cmp v0.5.5/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
                github.com/prometheus/client_model v0.0.0-20190812154241-14fe0d1b01d4 h1:gQz4mCbXsO+nc9n1hCxHcGA3Zx3Eo+UHZoInFGUIXNM=
                github.com/prometheus/client_model v0.0.0-20190812154241-14fe0d1b01d4/go.mod h1:xMI15A0UPsDsEKsMN9yxemIoYk6Tm2C1GtYGdfGttqA=
                golang.org/x/crypto v0.0.0-20190308221718-c2843e01d9a2 h1:VklqNMn3ovrHsnt90PveolxSbWFaJdECFbxSq0Mqo2M=
                golang.org/x/crypto v0.0.0-20190308221718-c2843e01d9a2/go.mod h1:djNgcEr1/C05ACkg1iLfiJU5Ep61QUkGW8qpdssI0+w=
                golang.org/x/exp v0.0.0-20190121172915-509febef88a4 h1:c2HOrn5iMezYjSlGPncknSEr/8x5LELb/ilJbXi9DEA=
                golang.org/x/exp v0.0.0-20190121172915-509febef88a4/go.mod h1:CJ0aWSM057203Lf6IL+f9T1iT9GByDxfZKAQTCR3kQA=
                golang.org/x/lint v0.0.0-20181026193005-c67002cb31c3/go.mod h1:UVdnD1Gm6xHRNCYTkRU2/jEulfH38KcIWyp/GAMgvoE=
                golang.org/x/lint v0.0.0-20190227174305-5b3e6a55c961/go.mod h1:wehouNa3lNwaWXcvxsM5YxQ5yQlVC4a0KAMCusXpPoU=
                golang.org/x/lint v0.0.0-20190313153728-d0100b6bd8b3 h1:XQyxROzUlZH+WIQwySDgnISgOivlhjIEwaQaJEJrrN0=
                golang.org/x/lint v0.0.0-20190313153728-d0100b6bd8b3/go.mod h1:6SW0HCj/g11FgYtHlgUYUwCkIfeOF89ocIRzGO/8vkc=
                golang.org/x/net v0.0.0-20180724234803-3673e40ba225/go.mod h1:mL1N/T3taQHkDXs73rZJwtUhF3w3ftmwwsq0BUmARs4=
                golang.org/x/net v0.0.0-20180826012351-8a410e7b638d/go.mod h1:mL1N/T3taQHkDXs73rZJwtUhF3w3ftmwwsq0BUmARs4=
                golang.org/x/net v0.0.0-20190213061140-3a22650c66bd/go.mod h1:mL1N/T3taQHkDXs73rZJwtUhF3w3ftmwwsq0BUmARs4=
                golang.org/x/net v0.0.0-20190311183353-d8887717615a h1:oWX7TPOiFAMXLq8o0ikBYfCJVlRHBcsciT5bXOrH628=
                golang.org/x/net v0.0.0-20190311183353-d8887717615a/go.mod h1:t9HGtf8HONx5eT2rtn7q6eTqICYqUVnKs3thJo3Qplg=
                golang.org/x/oauth2 v0.0.0-20180821212333-d2e6202438be h1:vEDujvNQGv4jgYKudGeI/+DAX4Jffq6hpD55MmoEvKs=
                golang.org/x/oauth2 v0.0.0-20180821212333-d2e6202438be/go.mod h1:N/0e6XlmueqKjAGxoOufVs8QHGRruUQn6yWY3a++T0U=
                golang.org/x/sync v0.0.0-20180314180146-1d60e4601c6f/go.mod h1:RxMgew5VJxzue5/jJTE5uejpjVlOe/izrB70Jof72aM=
                golang.org/x/sync v0.0.0-20181108010431-42b317875d0f/go.mod h1:RxMgew5VJxzue5/jJTE5uejpjVlOe/izrB70Jof72aM=
                golang.org/x/sync v0.0.0-20190423024810-112230192c58 h1:8gQV6CLnAEikrhgkHFbMAEhagSSnXWGV915qUMm9mrU=
                golang.org/x/sync v0.0.0-20190423024810-112230192c58/go.mod h1:RxMgew5VJxzue5/jJTE5uejpjVlOe/izrB70Jof72aM=
                golang.org/x/sys v0.0.0-20180830151530-49385e6e1522/go.mod h1:STP8DvDyc/dI5b8T5hshtkjS+E42TnysNCUPdjciGhY=
                golang.org/x/sys v0.0.0-20190215142949-d0b11bdaac8a h1:1BGLXjeY4akVXGgbC9HugT3Jv3hCI0z56oJR5vAMgBU=
                golang.org/x/sys v0.0.0-20190215142949-d0b11bdaac8a/go.mod h1:STP8DvDyc/dI5b8T5hshtkjS+E42TnysNCUPdjciGhY=
                golang.org/x/text v0.3.0 h1:g61tztE5qeGQ89tm6NTjjM9VPIm088od1l6aSorWRWg=
                golang.org/x/text v0.3.0/go.mod h1:NqM8EUOU14njkJ3fqMW+pc6Ldnwhi/IjpwHt7yyuwOQ=
                golang.org/x/tools v0.0.0-20190114222345-bf090417da8b/go.mod h1:n7NCudcB/nEzxVGmLbDWY5pfWTLqBcC2KZ6jyYvM4mQ=
                golang.org/x/tools v0.0.0-20190226205152-f727befe758c/go.mod h1:9Yl7xja0Znq3iFh3HoIrodX9oNMXvdceNzlUR8zjMvY=
                golang.org/x/tools v0.0.0-20190311212946-11955173bddd/go.mod h1:LCzVGOaR6xXOjkQ3onu1FJEFr0SW1gC7cKk1uF8kGRs=
                golang.org/x/tools v0.0.0-20190524140312-2c0ae7006135 h1:5Beo0mZN8dRzgrMMkDp0jc8YXQKx9DiJ2k1dkvGsn5A=
                golang.org/x/tools v0.0.0-20190524140312-2c0ae7006135/go.mod h1:RgjU9mgBXZiqYHBnxXauZ1Gv1EHHAz9KjViQ78xBX0Q=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 h1:E7g+9GITq07hpfrRu66IVDexMakfv52eLZ2CXBWiKr4=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                google.golang.org/appengine v1.1.0/go.mod h1:EbEs0AVv82hx2wNQdGPgUI5lhzA/G0D9YwlJXL52JkM=
                google.golang.org/appengine v1.4.0 h1:/wp5JvzpHIxhs/dumFmF7BXTf3Z+dd4uXta4kVyO508=
                google.golang.org/appengine v1.4.0/go.mod h1:xpcJRLb0r/rnEns0DIKYYv+WjYCduHsrkT7/EB5XEv4=
                google.golang.org/genproto v0.0.0-20180817151627-c66870c02cf8/go.mod h1:JiN7NxoALGmiZfu7CAH4rXhgtRTLTxftemlI0sWmxmc=
                google.golang.org/genproto v0.0.0-20190819201941-24fa4b261c55/go.mod h1:DMBHOl98Agz4BDEuKkezgsaosCRResVns1a3J2ZsMNc=
                google.golang.org/genproto v0.0.0-20200526211855-cb27e3aa2013 h1:+kGHl1aib/qcwaRi1CbqBZ1rk19r85MNUf8HaBghugY=
                google.golang.org/genproto v0.0.0-20200526211855-cb27e3aa2013/go.mod h1:NbSheEEYHJ7i3ixzK3sjbqSGDJWnxyFXZblF3eUsNvo=
                google.golang.org/grpc v1.19.0/go.mod h1:mqu4LbDTu4XGKhr4mRzUsmM4RtVoemTSY81AxZiDr8c=
                google.golang.org/grpc v1.23.0/go.mod h1:Y5yQAOtifL1yxbo5wqy6BxZv8vAUGQwXBOALyacEbxg=
                google.golang.org/grpc v1.27.0 h1:rRYRFMVgRv6E0D70Skyfsr28tDXIuuPZyWGMPdMcnXg=
                google.golang.org/grpc v1.27.0/go.mod h1:qbnxyOmOxrQa7FizSgH+ReBfzJrCY1pSN7KXBS8abTk=
                google.golang.org/protobuf v0.0.0-20200109180630-ec00e32a8dfd/go.mod h1:DFci5gLYBciE7Vtevhsrf46CRTquxDuWsQurQQe4oz8=
                google.golang.org/protobuf v0.0.0-20200221191635-4d8936d0db64/go.mod h1:kwYJMbMJ01Woi6D6+Kah6886xMZcty6N08ah7+eCXa0=
                google.golang.org/protobuf v0.0.0-20200228230310-ab0ca4ff8a60/go.mod h1:cfTl7dwQJ+fmap5saPgwCLgHXTUD7jkjRqWcaiX5VyM=
                google.golang.org/protobuf v1.20.1-0.20200309200217-e05f789c0967/go.mod h1:A+miEFZTKqfCUM6K7xSMQL9OKL/b6hQv+e19PK+JZNE=
                google.golang.org/protobuf v1.21.0/go.mod h1:47Nbq4nVaFHyn7ilMalzfO3qCViNmqZ2kzikPIcrTAo=
                google.golang.org/protobuf v1.22.0/go.mod h1:EGpADcykh3NcUnDUJcl1+ZksZNG86OlYog2l/sGQquU=
                google.golang.org/protobuf v1.23.1-0.20200526195155-81db48ad09cc/go.mod h1:EGpADcykh3NcUnDUJcl1+ZksZNG86OlYog2l/sGQquU=
                google.golang.org/protobuf v1.26.0-rc.1/go.mod h1:jlhhOSvTdKEhbULTjvd4ARK9grFBp09yW+WbY/TyQbw=
                google.golang.org/protobuf v1.26.0/go.mod h1:9q0QmTI4eRPtz6boOQmLYwt+qCgq0jsYwAQnmE0givc=
                google.golang.org/protobuf v1.27.1 h1:SnqbnDw1V7RiZcXPx5MEeqPv2s79L9i7BJUlG/+RurQ=
                google.golang.org/protobuf v1.27.1/go.mod h1:9q0QmTI4eRPtz6boOQmLYwt+qCgq0jsYwAQnmE0givc=
                honnef.co/go/tools v0.0.0-20190102054323-c2f93a96b099/go.mod h1:rf3lG4BRIbNafJWhAfAdb/ePZxsR/4RtNHQocxwk9r4=
                honnef.co/go/tools v0.0.0-20190523083050-ea95bdfd59fc h1:/hemPrYIhOhy8zYrNj+069zDB68us2sMGsfkFJO0iZs=
                honnef.co/go/tools v0.0.0-20190523083050-ea95bdfd59fc/go.mod h1:rf3lG4BRIbNafJWhAfAdb/ePZxsR/4RtNHQocxwk9r4=
                """
            ),
            "src/go/people/proto_test.go": dedent(
                """\
                package people
                import (
                  "testing"
                  pb_dir1 "example.com/dir1"
                  pb_dir2 "example.com/dir2"
                )
                func TestProtoGen(t *testing.T) {
                  person := pb_dir1.Person{
                    Name: "name",
                    Id: 1,
                    Email: "name@example.com",
                  }
                  if person.Name != "name" {
                    t.Fail()
                  }
                  place := pb_dir1.Place{
                    Town: "Any Town",
                    Country: "Some Country",
                  }
                  if place.Town != "Any Town" {
                    t.Fail()
                  }
                  employee := pb_dir2.Employee{
                    Self: &pb_dir1.Person{
                      Name: "self",
                      Id: 1,
                      Email: "self@example.com",
                    },
                    Manager: &pb_dir1.Person{
                      Name: "manager",
                      Id: 2,
                      Email: "manager@example.com",
                    },
                  }
                  if employee.Self.Name != "self" {
                    t.Fail()
                  }
                }
                """
            ),
        }
    )

    def assert_gen(addr: Address, expected: Iterable[str]) -> None:
        assert_files_generated(
            rule_runner,
            addr,
            source_roots=["src/python", "/src/protobuf", "/tests/protobuf"],
            expected_files=list(expected),
        )

    assert_gen(
        Address("src/protobuf/dir1", relative_file_path="f.proto"),
        ("src/protobuf/dir1/f.pb.go",),
    )
    assert_gen(
        Address("src/protobuf/dir1", relative_file_path="f2.proto"),
        ("src/protobuf/dir1/f2.pb.go",),
    )
    assert_gen(
        Address("src/protobuf/dir2", relative_file_path="f.proto"),
        ("src/protobuf/dir2/f.pb.go",),
    )
    assert_gen(
        Address("tests/protobuf/test_protos", relative_file_path="f.proto"),
        ("tests/protobuf/test_protos/f.pb.go",),
    )

    rule_runner.set_options(
        ["--go-test-args=-v"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    tgt = rule_runner.get_target(Address("src/go/people", target_name="pkg"))
    result = rule_runner.request(TestResult, [GoTestFieldSet.create(tgt)])
    assert result.exit_code == 0
    assert "PASS: TestProtoGen" in result.stdout


def test_generates_go_grpc(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "protos/BUILD": "protobuf_sources(grpc=True)",
            "protos/service.proto": dedent(
                """\
            syntax = "proto3";

            option go_package = "example.com/protos";

            package service;

            message TestMessage {
              string foo = 1;
            }

            service TestService {
              rpc noStreaming (TestMessage) returns (TestMessage);
              rpc clientStreaming (stream TestMessage) returns (TestMessage);
              rpc serverStreaming (TestMessage) returns (stream TestMessage);
              rpc bothStreaming (stream TestMessage) returns (stream TestMessage);
            }
            """
            ),
        }
    )
    assert_files_generated(
        rule_runner,
        Address("protos", relative_file_path="service.proto"),
        source_roots=["/"],
        expected_files=[
            "protos/service.pb.go",
            "protos/service_grpc.pb.go",
        ],
    )
