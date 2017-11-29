# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.avro.targets.java_avro_library import JavaAvroLibrary
from pants.contrib.avro.tasks.avro_gen import AvroJavaGenTask


def build_file_aliases():
  return BuildFileAliases(
    targets={
      JavaAvroLibrary.alias(): JavaAvroLibrary,
    }
  )


def register_goals():
  task(name='avro-java', action=AvroJavaGenTask).install('gen')
