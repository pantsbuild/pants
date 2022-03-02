# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap
import zipfile
from io import BytesIO

import pytest

from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.dependency_inference.rules import rules as java_dep_inf_rules
from pants.backend.java.target_types import rules as target_types_rules
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import FilesGeneratorTarget, FileTarget, RelocatedFiles
from pants.core.target_types import rules as core_target_types_rules
from pants.core.util_rules import archive
from pants.engine.fs import DigestContents
from pants.engine.internals.native_engine import EMPTY_DIGEST, FileDigest
from pants.engine.rules import QueryRule
from pants.jvm import classpath, jdk_rules
from pants.jvm.package import war
from pants.jvm.package.war import PackageWarFileFieldSet
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.common import ArtifactRequirement, Coordinate, Coordinates
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry
from pants.jvm.resolve.coursier_test_util import TestCoursierWrapper
from pants.jvm.target_types import JvmArtifactTarget, JvmWarTarget
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner():
    rule_runner = RuleRunner(
        rules=[
            *war.rules(),
            *jvm_tool.rules(),
            *classpath.rules(),
            *javac_rules(),
            *jdk_rules.rules(),
            *java_dep_inf_rules(),
            *target_types_rules(),
            *core_target_types_rules(),
            *util_rules(),
            *archive.rules(),
            QueryRule(BuiltPackage, (PackageWarFileFieldSet,)),
        ],
        target_types=[
            JvmArtifactTarget,
            JvmWarTarget,
            FileTarget,
            FilesGeneratorTarget,
            RelocatedFiles,
        ],
    )
    rule_runner.set_options([], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


@maybe_skip_jdk_test
def test_basic_war_packaging(rule_runner: RuleRunner) -> None:
    servlet_coordinate = Coordinate(group="javax.servlet", artifact="servlet-api", version="2.5")
    rule_runner.write_files(
        {
            "war-test/BUILD": textwrap.dedent(
                """\
            jvm_artifact(
              name="javax.servlet_servlet-api",
              group="javax.servlet",
              artifact="servlet-api",
              version="2.5",
            )

            jvm_war(
              name="war",
              dependencies=[":javax.servlet_servlet-api"],
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
            "3rdparty/jvm/default.lock": TestCoursierWrapper.new(
                (
                    CoursierLockfileEntry(
                        coord=servlet_coordinate,
                        file_name="javax.servlet_servlet-api_2.5.jar",
                        direct_dependencies=Coordinates(),
                        dependencies=Coordinates(),
                        file_digest=FileDigest(
                            "c658ea360a70faeeadb66fb3c90a702e4142a0ab7768f9ae9828678e0d9ad4dc",
                            105112,
                        ),
                    ),
                ),
            ).serialize([ArtifactRequirement(servlet_coordinate)]),
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
