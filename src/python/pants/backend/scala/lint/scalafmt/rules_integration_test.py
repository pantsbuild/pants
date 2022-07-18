# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import textwrap

import pytest

from pants.backend.scala import target_types
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.lint.scalafmt import skip_field
from pants.backend.scala.lint.scalafmt.rules import (
    GatherScalafmtConfigFilesRequest,
    ScalafmtConfigFiles,
    ScalafmtFieldSet,
    ScalafmtRequest,
    find_nearest_ancestor_file,
)
from pants.backend.scala.lint.scalafmt.rules import rules as scalafmt_rules
from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget, ScalaSourceTarget
from pants.build_graph.address import Address
from pants.core.goals.fmt import FmtResult
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, Digest, FileContent, PathGlobs, Snapshot
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.jvm import classpath
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.strip_jar import strip_jar
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *classpath.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *strip_jar.rules(),
            *scalac_rules(),
            *util_rules(),
            *jdk_rules(),
            *target_types.rules(),
            *scalafmt_rules(),
            *skip_field.rules(),
            QueryRule(FmtResult, (ScalafmtRequest,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
            QueryRule(Snapshot, (PathGlobs,)),
            QueryRule(ScalafmtConfigFiles, (GatherScalafmtConfigFilesRequest,)),
        ],
        target_types=[ScalaSourceTarget, ScalaSourcesGeneratorTarget],
    )
    rule_runner.set_options([], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


GOOD_FILE = """\
package org.pantsbuild.example

object Foo {
  val Foo = 3
}
"""

BAD_FILE = """\
package org.pantsbuild.example

object Bar {
val Foo = 3
}
"""

FIXED_BAD_FILE = """\
package org.pantsbuild.example

object Bar {
  val Foo = 3
}
"""

FIXED_BAD_FILE_INDENT_4 = """\
package org.pantsbuild.example

object Bar {
    val Foo = 3
}
"""

SCALAFMT_CONF_FILENAME = ".scalafmt.conf"

BASIC_SCALAFMT_CONF = """\
version = "3.2.1"
runner.dialect = scala213
"""


def run_scalafmt(rule_runner: RuleRunner, targets: list[Target]) -> FmtResult:
    field_sets = [ScalafmtFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.source for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            ScalafmtRequest(field_sets, snapshot=input_sources.snapshot),
        ],
    )
    return fmt_result


def get_snapshot(rule_runner: RuleRunner, source_files: dict[str, str]) -> Snapshot:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    digest = rule_runner.request(Digest, [CreateDigest(files)])
    return rule_runner.request(Snapshot, [digest])


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "Foo.scala": GOOD_FILE,
            "BUILD": "scala_sources(name='t')",
            ".scalafmt.conf": BASIC_SCALAFMT_CONF,
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="Foo.scala"))
    fmt_result = run_scalafmt(rule_runner, [tgt])
    assert fmt_result.output == get_snapshot(rule_runner, {"Foo.scala": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "Bar.scala": BAD_FILE,
            "BUILD": "scala_sources(name='t')",
            ".scalafmt.conf": BASIC_SCALAFMT_CONF,
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="Bar.scala"))
    fmt_result = run_scalafmt(rule_runner, [tgt])
    assert fmt_result.output == get_snapshot(rule_runner, {"Bar.scala": FIXED_BAD_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "Foo.scala": GOOD_FILE,
            "Bar.scala": BAD_FILE,
            "BUILD": "scala_sources(name='t')",
            ".scalafmt.conf": BASIC_SCALAFMT_CONF,
        }
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="Foo.scala")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="Bar.scala")),
    ]
    fmt_result = run_scalafmt(rule_runner, tgts)
    assert fmt_result.output == get_snapshot(
        rule_runner, {"Foo.scala": GOOD_FILE, "Bar.scala": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True


def test_multiple_config_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            SCALAFMT_CONF_FILENAME: BASIC_SCALAFMT_CONF,
            "foo/BUILD": "scala_sources()",
            "foo/Foo.scala": GOOD_FILE,
            "foo/bar/BUILD": "scala_sources()",
            "foo/bar/Bar.scala": BAD_FILE,
            f"foo/bar/{SCALAFMT_CONF_FILENAME}": textwrap.dedent(
                f"""\
                {BASIC_SCALAFMT_CONF}
                indent.main = 4
                """
            ),
        }
    )
    tgts = [
        rule_runner.get_target(Address("foo", target_name="foo", relative_file_path="Foo.scala")),
        rule_runner.get_target(
            Address("foo/bar", target_name="bar", relative_file_path="Bar.scala")
        ),
    ]
    fmt_result = run_scalafmt(rule_runner, tgts)
    assert fmt_result.output == get_snapshot(
        rule_runner, {"foo/Foo.scala": GOOD_FILE, "foo/bar/Bar.scala": FIXED_BAD_FILE_INDENT_4}
    )
    assert fmt_result.did_change is True


def test_find_nearest_ancestor_file() -> None:
    files = {"grok.conf", "foo/bar/grok.conf", "hello/world/grok.conf"}
    assert find_nearest_ancestor_file(files, "foo/bar", "grok.conf") == "foo/bar/grok.conf"
    assert find_nearest_ancestor_file(files, "foo/bar/", "grok.conf") == "foo/bar/grok.conf"
    assert find_nearest_ancestor_file(files, "foo", "grok.conf") == "grok.conf"
    assert find_nearest_ancestor_file(files, "foo/", "grok.conf") == "grok.conf"
    assert find_nearest_ancestor_file(files, "foo/xyzzy", "grok.conf") == "grok.conf"
    assert find_nearest_ancestor_file(files, "foo/xyzzy", "grok.conf") == "grok.conf"
    assert find_nearest_ancestor_file(files, "", "grok.conf") == "grok.conf"
    assert find_nearest_ancestor_file(files, "hello", "grok.conf") == "grok.conf"
    assert find_nearest_ancestor_file(files, "hello/", "grok.conf") == "grok.conf"
    assert (
        find_nearest_ancestor_file(files, "hello/world/foo", "grok.conf") == "hello/world/grok.conf"
    )
    assert (
        find_nearest_ancestor_file(files, "hello/world/foo/", "grok.conf")
        == "hello/world/grok.conf"
    )

    files2 = {"foo/bar/grok.conf", "hello/world/grok.conf"}
    assert find_nearest_ancestor_file(files2, "foo", "grok.conf") is None
    assert find_nearest_ancestor_file(files2, "foo/", "grok.conf") is None
    assert find_nearest_ancestor_file(files2, "", "grok.conf") is None


def test_gather_scalafmt_config_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            SCALAFMT_CONF_FILENAME: "",
            f"foo/bar/{SCALAFMT_CONF_FILENAME}": "",
            f"hello/{SCALAFMT_CONF_FILENAME}": "",
            "hello/Foo.scala": "",
            "hello/world/Foo.scala": "",
            "foo/bar/Foo.scala": "",
            "foo/bar/xyyzzy/Foo.scala": "",
            "foo/blah/Foo.scala": "",
        }
    )

    snapshot = rule_runner.request(Snapshot, [PathGlobs(["**/*.scala"])])
    request = rule_runner.request(ScalafmtConfigFiles, [GatherScalafmtConfigFilesRequest(snapshot)])
    assert sorted(request.source_dir_to_config_file.items()) == [
        ("foo/bar", "foo/bar/.scalafmt.conf"),
        ("foo/bar/xyyzzy", "foo/bar/.scalafmt.conf"),
        ("foo/blah", ".scalafmt.conf"),
        ("hello", "hello/.scalafmt.conf"),
        ("hello/world", "hello/.scalafmt.conf"),
    ]
