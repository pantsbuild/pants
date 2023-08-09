# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import textwrap
import zipfile
from io import BytesIO

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.dependency_inference.rules import rules as java_dep_inf_rules
from pants.backend.java.target_types import rules as target_types_rules
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import FilesGeneratorTarget, FileTarget, RelocatedFiles
from pants.core.target_types import rules as core_target_types_rules
from pants.core.util_rules import archive
from pants.core.util_rules.archive import ExtractedArchive, MaybeExtractArchiveRequest
from pants.engine.fs import EMPTY_DIGEST, DigestContents
from pants.engine.rules import QueryRule
from pants.jvm import classpath, jdk_rules
from pants.jvm.package import war
from pants.jvm.package.war import PackageWarFileFieldSet
from pants.jvm.resolve import jvm_tool
from pants.jvm.shading.rules import rules as shading_rules
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import JVM_SHADING_RULE_TYPES, JvmArtifactTarget, JvmWarTarget
from pants.jvm.testutil import _get_jar_contents_snapshot, maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def servlet_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "servlet.test.lock",
        ["javax.servlet:servlet-api:2.5"],
    )


@pytest.fixture
def servlet_lockfile(
    servlet_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return servlet_lockfile_def.load(request)


@pytest.fixture
def rule_runner():
    rule_runner = RuleRunner(
        rules=[
            *war.rules(),
            *jvm_tool.rules(),
            *classpath.rules(),
            *strip_jar.rules(),
            *javac_rules(),
            *jdk_rules.rules(),
            *java_dep_inf_rules(),
            *target_types_rules(),
            *core_target_types_rules(),
            *util_rules(),
            *archive.rules(),
            *shading_rules(),
            QueryRule(BuiltPackage, (PackageWarFileFieldSet,)),
            QueryRule(ExtractedArchive, (MaybeExtractArchiveRequest,)),
        ],
        target_types=[
            JvmArtifactTarget,
            JvmWarTarget,
            FileTarget,
            FilesGeneratorTarget,
            RelocatedFiles,
        ],
        objects={rule.alias: rule for rule in JVM_SHADING_RULE_TYPES},
    )
    rule_runner.set_options([], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


@maybe_skip_jdk_test
def test_basic_war_packaging(rule_runner: RuleRunner, servlet_lockfile: JVMLockfileFixture) -> None:
    rule_runner.write_files(
        {
            "war-test/BUILD": textwrap.dedent(
                """\
            jvm_war(
              name="war",
              dependencies=["3rdparty/jvm:javax.servlet_servlet-api"],
              descriptor="web.xml",
              content=[":html"],
            )

            files(name="orig_html", sources=["*.html"])
            relocated_files(
              name="html",
              files_targets=[":orig_html"],
              src="war-test",
              dest="",
            )
            """
            ),
            "war-test/web.xml": textwrap.dedent(
                """\
            <web-app>
            </web-app>
            """
            ),
            "war-test/index.html": textwrap.dedent(
                """\
            <html>
            <body>
            <p>This is the home page.</p>
            </html>
            """
            ),
            "3rdparty/jvm/default.lock": servlet_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": servlet_lockfile.requirements_as_jvm_artifact_targets(),
        }
    )

    war_tgt = rule_runner.get_target(Address("war-test", target_name="war"))
    built_package = rule_runner.request(BuiltPackage, [PackageWarFileFieldSet.create(war_tgt)])
    assert built_package.digest != EMPTY_DIGEST
    assert len(built_package.artifacts) == 1
    package = built_package.artifacts[0]
    assert package.relpath == "war-test/war.war"

    contents = rule_runner.request(DigestContents, [built_package.digest])
    assert len(contents) == 1
    zip_bytes = BytesIO(contents[0].content)
    with zipfile.ZipFile(zip_bytes, "r") as zf:
        files = zf.filelist
    filenames = [f.filename for f in files]
    assert sorted(filenames) == [
        "WEB-INF/",
        "WEB-INF/classes/",
        "WEB-INF/lib/",
        "WEB-INF/lib/javax.servlet_servlet-api_2.5.jar",
        "WEB-INF/web.xml",
        "index.html",
    ]


@maybe_skip_jdk_test
def test_shade_servletapi_in_war(
    rule_runner: RuleRunner, servlet_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "war-test/BUILD": textwrap.dedent(
                """\
                jvm_war(
                    name="war",
                    dependencies=["3rdparty/jvm:javax.servlet_servlet-api"],
                    descriptor="web.xml",
                    shading_rules=[
                        shading_zap(pattern="javax.servlet.**"),
                    ],
                )
                """
            ),
            "war-test/web.xml": textwrap.dedent(
                """\
                <web-app>
                </web-app>
                """
            ),
            "3rdparty/jvm/default.lock": servlet_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": servlet_lockfile.requirements_as_jvm_artifact_targets(),
        }
    )

    war_tgt = rule_runner.get_target(Address("war-test", target_name="war"))
    built_package = rule_runner.request(BuiltPackage, [PackageWarFileFieldSet.create(war_tgt)])
    assert len(built_package.artifacts) == 1
    assert built_package.digest != EMPTY_DIGEST

    war_contents = _get_jar_contents_snapshot(
        rule_runner, filename=str(built_package.artifacts[0].relpath), digest=built_package.digest
    )
    assert "WEB-INF/lib/javax.servlet_servlet-api_2.5.jar" in war_contents.files

    servletapi_contents = _get_jar_contents_snapshot(
        rule_runner,
        filename="WEB-INF/lib/javax.servlet_servlet-api_2.5.jar",
        digest=war_contents.digest,
    )
    class_files_found = [
        filename for filename in servletapi_contents.files if filename.endswith(".class")
    ]
    assert len(class_files_found) == 0
