# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase

from pants.contrib.avro.targets.java_avro_library import JavaAvroLibrary
from pants.contrib.avro.tasks.avro_gen import AvroJavaGenTask


class MockAvroJavaGenTest(AvroJavaGenTask):
  _test_cmd_log = []  # List of lists for commands run by the task under test.

  # Overide this method and record the command that would have been run.
  def _avro(self, args):
    self._test_cmd_log.append(args)

  def _test_reset(self):
    self._test_cmd_log = []


class AvroJavaGenTest(NailgunTaskTestBase):
  @classmethod
  def task_type(cls):
    return MockAvroJavaGenTest

  @property
  def alias_groups(self):
    return super(AvroJavaGenTest, self).alias_groups.merge(
      BuildFileAliases(targets={'java_avro_library': JavaAvroLibrary}))

  def _test_avro(self, target_spec):
    target = self.target(target_spec)
    context = self.context(target_roots=[target])
    task = self.prepare_execute(context)
    task._test_reset()
    task.execute()
    return task

  def test_avro_java_gen(self):
    # Disable lookup of avro-tools since not used for this unit test.
    self.set_options(runtime_deps=[])

    self.add_to_build_file('avro-build', dedent('''
      java_avro_library(name='avro-schema',
        sources=['src/avro/schema.avsc'],
      )
      java_avro_library(name='avro-protocol',
        sources=['src/avro/protocol.avpl'],
      )
      java_avro_library(name='avro-idl',
        sources=['src/avro/record.avdl'],
      )
    '''))

    self.create_file(relpath='avro-build/src/avro/schema.avsc', contents=dedent('''
      {
        "namespace": "",
        "type": "record",
        "name": "Person",
        "fields": [
          {"name": "name", "type": "string"},
          {"name": "age", "type": "int"}
        ]
      }
    '''))

    self.create_file(relpath='avro-build/src/avro/record.avdl', contents=dedent('''
      protocol Test {
        void test();
      }
    '''))

    task = self._test_avro('avro-build:avro-schema')
    self.assertEquals(len(task._test_cmd_log), 1)
    self.assertEquals(task._test_cmd_log[0][:-1], ['compile', 'schema', 'avro-build/src/avro/schema.avsc'])

    task = self._test_avro('avro-build:avro-idl')
    self.assertEquals(len(task._test_cmd_log), 2)
    self.assertEquals(task._test_cmd_log[0][:-1], ['idl', 'avro-build/src/avro/record.avdl'])
    generated_protocol_json_file = task._test_cmd_log[0][-1]
    self.assertEquals(task._test_cmd_log[1][:-1], ['compile', 'protocol', generated_protocol_json_file])
