# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Code generation from the Apache Avro format into Java targets (deprecated)."""

from pants.base.deprecated import _deprecated_contrib_plugin
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.avro.rules.targets import JavaAvroLibrary
from pants.contrib.avro.targets.java_avro_library import JavaAvroLibrary as JavaAvroLibraryV1
from pants.contrib.avro.tasks.avro_gen import AvroJavaGenTask


def build_file_aliases():
    return BuildFileAliases(targets={JavaAvroLibraryV1.alias(): JavaAvroLibraryV1})


_deprecated_contrib_plugin("pantsbuild.pants.contrib.avro")


def register_goals():
    task(name="avro-java", action=AvroJavaGenTask).install("gen")


def targets2():
    return [JavaAvroLibrary]
