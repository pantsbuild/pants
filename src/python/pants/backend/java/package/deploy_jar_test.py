# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.dependency_inference.rules import rules as java_dep_inf_rules
from pants.backend.java.package.deploy_jar import DeployJarFieldSet
from pants.backend.java.package.deploy_jar import rules as deploy_jar_rules
from pants.backend.java.target_types import DeployJarTarget, JavaSourcesGeneratorTarget
from pants.backend.java.target_types import rules as target_types_rules
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.jvm import jdk_rules
from pants.jvm.classpath import rules as classpath_rules
from pants.jvm.jdk_rules import JdkSetup
from pants.jvm.resolve.common import CoursierResolvedLockfile
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.resolve.user_resolves import rules as coursier_fetch_rules
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *classpath_rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *deploy_jar_rules(),
            *javac_rules(),
            *jdk_rules.rules(),
            *java_dep_inf_rules(),
            *target_types_rules(),
            *util_rules(),
            QueryRule(BashBinary, ()),
            QueryRule(BuiltPackage, (DeployJarFieldSet,)),
            QueryRule(JdkSetup, ()),
            QueryRule(ProcessResult, (Process,)),
        ],
        target_types=[
            JavaSourcesGeneratorTarget,
            JvmArtifactTarget,
            DeployJarTarget,
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


JAVA_LIB_SOURCE = dedent(
    """
    package org.pantsbuild.example.lib;

    public class ExampleLib {
        public static String hello() {
            return "Hello, World!";
        }
    }
    """
)


JAVA_JSON_MANGLING_LIB_SOURCE = dedent(
    """
    package org.pantsbuild.example.lib;

    import com.fasterxml.jackson.databind.ObjectMapper;

    public class ExampleLib {

        private String template = "{\\"contents\\": \\"Hello, World!\\"}";

        public String getGreeting() {
            ObjectMapper mapper = new ObjectMapper();
            try {
                SerializedThing thing = mapper.readValue(template, SerializedThing.class);
                return thing.contents;
            } catch (Exception e) {
                throw new RuntimeException(e);
            }
        }

        public static String hello() {
            return new ExampleLib().getGreeting();
        }
    }

    class SerializedThing {
        public String contents;
    }
    """
)


JAVA_MAIN_SOURCE = dedent(
    """
    package org.pantsbuild.example;

    import org.pantsbuild.example.lib.ExampleLib;

    public class Example {
        public static void main(String[] args) {
            System.out.println(ExampleLib.hello());
        }
    }
    """
)

JAVA_MAIN_SOURCE_NO_DEPS = dedent(
    """
    package org.pantsbuild.example;

    public class Example {
        public static void main(String[] args) {
            System.out.println("Hello, World!");
        }
    }
    """
)


COURSIER_LOCKFILE_SOURCE = dedent(
    """
    [
        {
            "coord": {
                "group": "com.fasterxml.jackson.core",
                "artifact": "jackson-annotations",
                "version": "2.12.5",
                "packaging": "jar"
            },
            "directDependencies": [],
            "dependencies": [],
            "file_name": "jackson-annotations-2.12.5.jar",
            "file_digest": {
                "fingerprint": "517926d9fe04cadd55120790d0b5355e4f656ffe2969e4d480a0e7f95a983e9e",
                "serialized_bytes_length": 75704
            }
        },
        {
            "coord": {
                "group": "com.fasterxml.jackson.core",
                "artifact": "jackson-core",
                "version": "2.12.5",
                "packaging": "jar"
            },
            "directDependencies": [],
            "dependencies": [],
            "file_name": "jackson-core-2.12.5.jar",
            "file_digest": {
                "fingerprint": "0c9860b8fb6f24f59e083e0b92a17c515c45312951fc272d093e4709faed6356",
                "serialized_bytes_length": 365536
            }
        },
        {
            "coord": {
                "group": "com.fasterxml.jackson.core",
                "artifact": "jackson-databind",
                "version": "2.12.5",
                "packaging": "jar"
            },
            "directDependencies": [
                {
                    "group": "com.fasterxml.jackson.core",
                    "artifact": "jackson-annotations",
                    "version": "2.12.5",
                    "packaging": "jar"
                },
                {
                    "group": "com.fasterxml.jackson.core",
                    "artifact": "jackson-core",
                    "version": "2.12.5",
                    "packaging": "jar"
                }
            ],
            "dependencies": [
                {
                    "group": "com.fasterxml.jackson.core",
                    "artifact": "jackson-core",
                    "version": "2.12.5",
                    "packaging": "jar"
                },
                {
                    "group": "com.fasterxml.jackson.core",
                    "artifact": "jackson-annotations",
                    "version": "2.12.5",
                    "packaging": "jar"
                }
            ],
            "file_name": "jackson-databind-2.12.5.jar",
            "file_digest": {
                "fingerprint": "d49cdfd82443fa5869d75fe53680012cef2dd74621b69d37da69087c40f1575a",
                "serialized_bytes_length": 1515991
            }
        }
    ]
"""
)


@maybe_skip_jdk_test
def test_deploy_jar_no_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                    deploy_jar(
                        name="example_app_deploy_jar",
                        main="org.pantsbuild.example.Example",
                        output_path="dave.jar",
                        dependencies=[
                            ":example",
                        ],
                    )

                    java_sources(
                        name="example",
                    )
                """
            ),
            "3rdparty/jvm/default.lock": CoursierResolvedLockfile(()).to_serialized().decode(),
            "Example.java": JAVA_MAIN_SOURCE_NO_DEPS,
        }
    )

    _deploy_jar_test(rule_runner, "example_app_deploy_jar")


@maybe_skip_jdk_test
def test_deploy_jar_local_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                    deploy_jar(
                        name="example_app_deploy_jar",
                        main="org.pantsbuild.example.Example",
                        output_path="dave.jar",
                        dependencies=[
                            ":example",
                        ],
                    )

                    java_sources(
                        name="example",
                        sources=["**/*.java", ],
                    )
                """
            ),
            "3rdparty/jvm/default.lock": CoursierResolvedLockfile(()).to_serialized().decode(),
            "Example.java": JAVA_MAIN_SOURCE,
            "lib/ExampleLib.java": JAVA_LIB_SOURCE,
        }
    )

    _deploy_jar_test(rule_runner, "example_app_deploy_jar")


@maybe_skip_jdk_test
def test_deploy_jar_coursier_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                    deploy_jar(
                        name="example_app_deploy_jar",
                        main="org.pantsbuild.example.Example",
                        output_path="dave.jar",
                        dependencies=[
                            ":example",
                        ],
                    )

                    java_sources(
                        name="example",
                        sources=["**/*.java", ],
                        dependencies=[
                            ":com.fasterxml.jackson.core_jackson-databind",
                        ],
                    )

                    jvm_artifact(
                        name = "com.fasterxml.jackson.core_jackson-databind",
                        group = "com.fasterxml.jackson.core",
                        artifact = "jackson-databind",
                        version = "2.12.5",
                    )
                """
            ),
            "3rdparty/jvm/default.lock": COURSIER_LOCKFILE_SOURCE,
            "Example.java": JAVA_MAIN_SOURCE,
            "lib/ExampleLib.java": JAVA_JSON_MANGLING_LIB_SOURCE,
        }
    )

    _deploy_jar_test(rule_runner, "example_app_deploy_jar")


def _deploy_jar_test(rule_runner: RuleRunner, target_name: str) -> None:
    tgt = rule_runner.get_target(Address("", target_name=target_name))
    fat_jar = rule_runner.request(
        BuiltPackage,
        [DeployJarFieldSet.create(tgt)],
    )

    jdk_setup = rule_runner.request(JdkSetup, [])
    bash = rule_runner.request(BashBinary, [])

    process_result = rule_runner.request(
        ProcessResult,
        [
            Process(
                argv=jdk_setup.args(bash, []) + ("-jar", "dave.jar"),
                description="Run that test jar",
                input_digest=fat_jar.digest,
                append_only_caches=jdk_setup.append_only_caches,
                immutable_input_digests=jdk_setup.immutable_input_digests,
                env=jdk_setup.env,
            )
        ],
    )

    assert process_result.stdout.decode("utf-8").strip() == "Hello, World!"
