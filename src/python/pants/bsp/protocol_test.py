# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from urllib.parse import urlparse

import pytest
from pylsp_jsonrpc.exceptions import JsonRpcException  # type: ignore[import]

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.java.bsp.rules import rules as java_bsp_rules
from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.target_types import JavaSourcesGeneratorTarget
from pants.backend.java.target_types import rules as java_target_types_rules
from pants.backend.scala.bsp.rules import rules as scala_bsp_rules
from pants.backend.scala.bsp.spec import ScalacOptionsParams, ScalacOptionsResult
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.dependency_inference.rules import rules as scala_dep_inf_rules
from pants.backend.scala.target_types import ScalatestTestsGeneratorTarget
from pants.backend.scala.target_types import rules as scala_target_types_rules
from pants.bsp.rules import rules as bsp_rules
from pants.bsp.spec.base import BuildTargetCapabilities, BuildTargetIdentifier, StatusCode
from pants.bsp.spec.compile import CompileParams, CompileResult
from pants.bsp.spec.lifecycle import (
    BuildClientCapabilities,
    InitializeBuildParams,
    InitializeBuildResult,
)
from pants.bsp.spec.resources import ResourcesParams
from pants.bsp.spec.targets import (
    DependencySourcesParams,
    SourcesParams,
    SourcesResult,
    WorkspaceBuildTargetsParams,
    WorkspaceBuildTargetsResult,
)
from pants.bsp.testutil import setup_bsp_server
from pants.core.util_rules import config_files, source_files, stripped_source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.jvm import classpath, jdk_rules, testutil
from pants.jvm.goals import lockfile
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


def test_basic_bsp_protocol() -> None:
    with setup_bsp_server() as (endpoint, _):
        with pytest.raises(JsonRpcException) as exc_info:
            response_fut = endpoint.request("foo")
            response_fut.result(timeout=15)
        assert exc_info.value.code == -32002
        assert exc_info.value.message == "Client must first call `build/initialize`."

        init_request = InitializeBuildParams(
            display_name="test",
            version="0.0.0",
            bsp_version="0.0.0",
            root_uri="https://example.com",
            capabilities=BuildClientCapabilities(language_ids=()),
            data={"test": "foo"},
        )
        response_fut = endpoint.request("build/initialize", init_request.to_json_dict())
        raw_response = response_fut.result(timeout=15)
        response = InitializeBuildResult.from_json_dict(raw_response)
        assert response.display_name == "Pants"
        assert response.bsp_version == "2.0.0"

        build_targets_request = WorkspaceBuildTargetsParams()
        response_fut = endpoint.request(
            "workspace/buildTargets", build_targets_request.to_json_dict()
        )
        raw_response = response_fut.result(timeout=15)
        response = WorkspaceBuildTargetsResult.from_json_dict(raw_response)
        assert response.targets == ()


@pytest.fixture
def jvm_rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *bsp_rules(),
            *java_bsp_rules(),
            *scala_bsp_rules(),
            *config_files.rules(),
            *coursier_fetch_rules(),
            *lockfile.rules(),
            *classpath.rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *scala_dep_inf_rules(),
            *strip_jar.rules(),
            *javac_rules(),
            *jdk_rules.rules(),
            *scalac_rules(),
            *source_files.rules(),
            *scala_target_types_rules(),
            *java_target_types_rules(),
            *util_rules(),
            *testutil.rules(),
            *stripped_source_files.rules(),
        ],
        target_types=[
            JavaSourcesGeneratorTarget,
            JvmArtifactTarget,
            ScalatestTestsGeneratorTarget,
        ],
    )
    rule_runner.set_options(
        args=[
            "--experimental-bsp-groups-config-files=bsp-groups.toml",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


@pytest.fixture
def jvm_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "protocol-intellij.test.lock",
        [
            "org.scala-lang:scala-library:2.13.6",
            "org.scalatest:scalatest_2.13:3.2.10",
        ],
    )


@pytest.fixture
def jvm_lockfile(jvm_lockfile_def: JVMLockfileFixtureDefinition, request) -> JVMLockfileFixture:
    return jvm_lockfile_def.load(request)


def test_intellij_test(jvm_rule_runner: RuleRunner, jvm_lockfile: JVMLockfileFixture) -> None:
    jvm_rule_runner.write_files(
        {
            "3rdparty/jvm/BUILD": jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": jvm_lockfile.serialized_lockfile,
            "BUILD": "scalatest_tests(name='main')",
            "Spec.scala": dedent(
                """\
                package org.pantsbuild.example

                import org.scalatest.funspec.AnyFunSpec

                import org.pantsbuild.example.lib.ExampleLib

                class ExampleLibSpec extends AnyFunSpec {
                  describe("ExampleLib") {
                    it("should say hello") {
                      assert(ExampleLib.HELLO == "hello!")
                    }
                  }
                }
                """
            ),
            "lib/BUILD": "java_sources()",
            "lib/ExampleLib.java": dedent(
                """\
                package org.pantsbuild.example.lib;

                public class ExampleLib {
                    public static String HELLO = "hello!";
                }
                """
            ),
            "bsp-groups.toml": dedent(
                """\
                [groups.default]
                addresses = ["::"]
                """
            ),
        }
    )

    target_ids = (BuildTargetIdentifier("pants:default"),)

    # We set a very high timeout here (was 15s) due to CI flakes as documented in:
    #   https://github.com/pantsbuild/pants/issues/15657
    # This seems to paper over some slow interaction between requests and the LMDB
    # store as noted in the ticket.
    timeout = 45

    with setup_bsp_server(
        jvm_rule_runner,
        notification_names={"build/taskStart", "build/taskProgress", "build/taskFinish"},
    ) as (endpoint, notifications):
        build_root = Path(jvm_rule_runner.build_root)

        # build/initialize
        _ = endpoint.request(
            "build/initialize",
            InitializeBuildParams(
                display_name="IntelliJ-BSP",
                version="2022.1.13",
                bsp_version="2.0",
                root_uri=build_root.as_uri(),
                capabilities=BuildClientCapabilities(language_ids=("scala", "java")),
                data={
                    "clientClassesRootDir": (build_root / "out").as_uri(),
                    "supportedScalaVersions": [],
                },
            ).to_json_dict(),
        ).result(timeout=timeout)

        # build/initialized
        endpoint.notify("build/initialized")

        # workspace/buildTargets
        build_targets = WorkspaceBuildTargetsResult.from_json_dict(
            endpoint.request("workspace/buildTargets").result(timeout=timeout)
        )
        assert len(build_targets.targets) == 1
        assert build_targets.targets[0].capabilities == BuildTargetCapabilities(can_compile=True)
        assert build_targets.targets[0].language_ids == ("java", "scala")

        # buildTarget/sources
        sources = SourcesResult.from_json_dict(
            endpoint.request(
                "buildTarget/sources", SourcesParams(target_ids).to_json_dict()
            ).result(timeout=timeout)
        )
        assert len(sources.items[0].sources) == 2

        # buildTarget/dependencySources - (NB: stubbed)
        _ = endpoint.request(
            "buildTarget/dependencySources", DependencySourcesParams(target_ids).to_json_dict()
        ).result(timeout=timeout)

        # buildTarget/resources - (NB: used only to index resources)
        _ = endpoint.request(
            "buildTarget/resources", ResourcesParams(target_ids).to_json_dict()
        ).result(timeout=timeout)

        # buildTarget/scalacOptions
        scalac_options = ScalacOptionsResult.from_json_dict(
            endpoint.request(
                "buildTarget/scalacOptions", ScalacOptionsParams(target_ids).to_json_dict()
            ).result(timeout=timeout)
        )
        assert scalac_options.items[0].classpath
        class_directory = Path(urlparse(scalac_options.items[0].class_directory).path)
        assert not class_directory.exists()

        # buildTarget/compile
        compile_result = CompileResult.from_json_dict(
            endpoint.request(
                "buildTarget/compile", CompileParams(target_ids).to_json_dict()
            ).result(timeout=timeout)
        )
        assert StatusCode(compile_result.status_code) == StatusCode.OK
        notifications.assert_received_unordered(
            [
                ("build/taskStart", {}),
                ("build/taskProgress", {"message": "//Spec.scala:main succeeded."}),
                ("build/taskProgress", {"message": "lib/ExampleLib.java succeeded."}),
                ("build/taskFinish", {}),
            ]
        )
        assert list(class_directory.iterdir())
