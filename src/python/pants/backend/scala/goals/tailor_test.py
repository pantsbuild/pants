# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.scala.goals.tailor import classify_source_files
from pants.backend.scala.target_types import (
    ScalaJunitTestsGeneratorTarget,
    ScalameterBenchmarksGeneratorTarget,
    ScalaSourcesGeneratorTarget,
    ScalatestTestsGeneratorTarget,
)


def test_classify_source_files() -> None:
    scalatest_files = {
        "foo/bar/BazSpec.scala",
    }
    junit_files = {
        "foo/bar/BazTest.scala",
    }
    scalameter_files = {
        "foo/bar/BazBenchmark.scala",
    }
    lib_files = {"foo/bar/Baz.scala"}

    assert {
        ScalatestTestsGeneratorTarget: scalatest_files,
        ScalaJunitTestsGeneratorTarget: junit_files,
        ScalaSourcesGeneratorTarget: lib_files,
        ScalameterBenchmarksGeneratorTarget: scalameter_files,
    } == classify_source_files(junit_files | lib_files | scalatest_files | scalameter_files)
