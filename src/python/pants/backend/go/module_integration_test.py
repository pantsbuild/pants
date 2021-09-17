# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap

import pytest

from pants.backend.go import module
from pants.backend.go.module import (
    DownloadedExternalModule,
    DownloadExternalModuleRequest,
    ResolvedGoModule,
    ResolveGoModuleRequest,
)
from pants.backend.go.target_types import GoModule, GoPackage
from pants.backend.go.util_rules import sdk
from pants.build_graph.address import Address
from pants.core.util_rules import external_tool, source_files
from pants.engine import fs
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *external_tool.rules(),
            *source_files.rules(),
            *fs.rules(),
            *sdk.rules(),
            *module.rules(),
            QueryRule(ResolvedGoModule, [ResolveGoModuleRequest]),
            QueryRule(DownloadedExternalModule, [DownloadExternalModuleRequest]),
            QueryRule(DigestContents, [Digest]),
        ],
        target_types=[GoPackage, GoModule],
    )
    rule_runner.set_options(["--backend-packages=pants.backend.experimental.go"])
    return rule_runner


def test_resolve_go_module(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/pkg/foo.go": "package pkg\n",
            "foo/go.mod": "module go.example.com/foo\ngo 1.16\nrequire github.com/golang/protobuf v1.4.2\n",
            "foo/go.sum": textwrap.dedent(
                """\
                github.com/golang/protobuf v1.4.0-rc.1/go.mod h1:ceaxUfeHdC40wWswd/P6IGgMaK3YpKi5j83Wpe3EHw8=
                github.com/golang/protobuf v1.4.0-rc.1.0.20200221234624-67d41d38c208/go.mod h1:xKAWHe0F5eneWXFV3EuXVDTCmh+JuBKY0li0aMyXATA=
                github.com/golang/protobuf v1.4.0-rc.2/go.mod h1:LlEzMj4AhA7rCAGe4KMBDvJI+AwstrUpVNzEA03Pprs=
                github.com/golang/protobuf v1.4.0-rc.4.0.20200313231945-b860323f09d0/go.mod h1:WU3c8KckQ9AFe+yFwt9sWVRKCVIyN9cPHBJSNnbL67w=
                github.com/golang/protobuf v1.4.0/go.mod h1:jodUvKwWbYaEsadDk5Fwe5c77LiNKVO9IDvqG2KuDX0=
                github.com/golang/protobuf v1.4.2 h1:+Z5KGCizgyZCbGh1KZqA0fcLLkwbsjIzS4aV2v7wJX0=
                github.com/golang/protobuf v1.4.2/go.mod h1:oDoupMAO8OvCJWAcko0GGGIgR6R6ocIYbsSw735rRwI=
                github.com/google/go-cmp v0.3.0/go.mod h1:8QqcDgzrUqlUb/G2PQTWiueGozuR1884gddMywk6iLU=
                github.com/google/go-cmp v0.3.1/go.mod h1:8QqcDgzrUqlUb/G2PQTWiueGozuR1884gddMywk6iLU=
                github.com/google/go-cmp v0.4.0 h1:xsAVV57WRhGj6kEIi8ReJzQlHHqcBYCElAvkovg3B/4=
                github.com/google/go-cmp v0.4.0/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                google.golang.org/protobuf v0.0.0-20200109180630-ec00e32a8dfd/go.mod h1:DFci5gLYBciE7Vtevhsrf46CRTquxDuWsQurQQe4oz8=
                google.golang.org/protobuf v0.0.0-20200221191635-4d8936d0db64/go.mod h1:kwYJMbMJ01Woi6D6+Kah6886xMZcty6N08ah7+eCXa0=
                google.golang.org/protobuf v0.0.0-20200228230310-ab0ca4ff8a60/go.mod h1:cfTl7dwQJ+fmap5saPgwCLgHXTUD7jkjRqWcaiX5VyM=
                google.golang.org/protobuf v1.20.1-0.20200309200217-e05f789c0967/go.mod h1:A+miEFZTKqfCUM6K7xSMQL9OKL/b6hQv+e19PK+JZNE=
                google.golang.org/protobuf v1.21.0/go.mod h1:47Nbq4nVaFHyn7ilMalzfO3qCViNmqZ2kzikPIcrTAo=
                google.golang.org/protobuf v1.23.0/go.mod h1:EGpADcykh3NcUnDUJcl1+ZksZNG86OlYog2l/sGQquU=
                """
            ),
            "foo/main.go": "package main\nfunc main() { }\n",
            "foo/BUILD": "go_module(name='mod')\ngo_package(name='pkg')\n",
        }
    )
    resolved_go_module = rule_runner.request(
        ResolvedGoModule, [ResolveGoModuleRequest(Address("foo", target_name="mod"))]
    )
    assert resolved_go_module.import_path == "go.example.com/foo"
    assert resolved_go_module.minimum_go_version == "1.16"
    assert len(resolved_go_module.modules) > 0
    found_protobuf_module = False
    for module_descriptor in resolved_go_module.modules:
        if module_descriptor.path == "github.com/golang/protobuf":
            found_protobuf_module = True
    assert found_protobuf_module


def test_download_external_module(rule_runner: RuleRunner) -> None:
    downloaded_module = rule_runner.request(
        DownloadedExternalModule,
        [DownloadExternalModuleRequest(path="github.com/google/uuid", version="v1.3.0")],
    )
    assert downloaded_module.path == "github.com/google/uuid"
    assert downloaded_module.version == "v1.3.0"

    digest_contents = rule_runner.request(DigestContents, [downloaded_module.digest])
    found_uuid_go_file = False
    for file_content in digest_contents:
        if file_content.path == "uuid.go":
            found_uuid_go_file = True
            break
    assert found_uuid_go_file


def test_download_external_module_with_no_gomod(rule_runner: RuleRunner) -> None:
    downloaded_module = rule_runner.request(
        DownloadedExternalModule,
        [DownloadExternalModuleRequest(path="cloud.google.com/go", version="v0.26.0")],
    )
    assert downloaded_module.path == "cloud.google.com/go"
    assert downloaded_module.version == "v0.26.0"

    digest_contents = rule_runner.request(DigestContents, [downloaded_module.digest])
    found_go_mod = False
    for file_content in digest_contents:
        if file_content.path == "go.mod":
            found_go_mod = True
            break
    assert found_go_mod
