# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest

from pants.build_graph.address import Address
from pants.core.target_types import ResourcesGeneratorTarget, ResourceTarget
from pants.core.target_types import rules as core_target_types_rules
from pants.engine.addresses import Addresses
from pants.engine.fs import DigestContents, FileContent
from pants.engine.internals.native_engine import Digest
from pants.jvm import jdk_rules, resources, testutil
from pants.jvm.classpath import Classpath
from pants.jvm.classpath import rules as classpath_rules
from pants.jvm.goals import lockfile
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_test_util import EMPTY_JVM_LOCKFILE
from pants.jvm.strip_jar import strip_jar
from pants.jvm.testutil import RenderedClasspath, maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *core_target_types_rules(),
            *coursier_fetch_rules(),
            *lockfile.rules(),
            *jvm_tool.rules(),
            *jdk_rules.rules(),
            *strip_jar.rules(),
            *resources.rules(),
            *classpath_rules(),
            *util_rules(),
            *testutil.rules(),
            QueryRule(Classpath, (Addresses,)),
            QueryRule(RenderedClasspath, (Addresses,)),
            QueryRule(DigestContents, (Digest,)),
        ],
        target_types=[
            ResourcesGeneratorTarget,
            ResourceTarget,
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


def filenames_from_zip(file_content: FileContent) -> list[str]:
    z = ZipFile(BytesIO(file_content.content))
    files = z.filelist
    return [file_.filename for file_ in files]


@maybe_skip_jdk_test
def test_resources(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "resources(name='root', sources=['**/*.txt'])",
            "one.txt": "",
            "two.txt": "",
            "three/four.txt": "",
            "three/five.txt": "",
            "three/six/seven/eight.txt": "",
            "3rdparty/jvm/default.lock": EMPTY_JVM_LOCKFILE,
        }
    )

    # Building the generator target should exclude the individual files and result in a single jar
    # for the generator.
    classpath = rule_runner.request(
        Classpath, [Addresses([Address(spec_path="", target_name="root")])]
    )

    contents = rule_runner.request(DigestContents, list(classpath.digests()))
    assert contents[0].path == ".root.resources.jar"
    resources_filenames = set(filenames_from_zip(contents[0]))
    expected = {
        "one.txt",
        "two.txt",
        "three/",
        "three/four.txt",
        "three/five.txt",
        "three/six/",
        "three/six/seven/",
        "three/six/seven/eight.txt",
    }

    assert resources_filenames == expected

    # But requesting a single file should individually package it.
    classpath = rule_runner.request(
        Classpath,
        [Addresses([Address(spec_path="", target_name="root", relative_file_path="one.txt")])],
    )
    contents = rule_runner.request(DigestContents, list(classpath.digests()))
    assert contents[0].path == ".one.txt.root.resources.jar"
    assert filenames_from_zip(contents[0]) == ["one.txt"]


@maybe_skip_jdk_test
def test_resources_jar_is_deterministic(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "resources(name='root', sources=['**/*.txt'])",
            "one.txt": "",
            "two.txt": "",
            "three/four.txt": "",
            "three/five.txt": "",
            "three/six/seven/eight.txt": "",
            "3rdparty/jvm/default.lock": EMPTY_JVM_LOCKFILE,
        }
    )

    classpath = rule_runner.request(
        Classpath, [Addresses([Address(spec_path="", target_name="root")])]
    )

    contents = rule_runner.request(DigestContents, list(classpath.digests()))

    z = ZipFile(BytesIO(contents[0].content))
    for info in z.infolist():
        assert info.date_time == (1980, 1, 1, 0, 0, 0)
