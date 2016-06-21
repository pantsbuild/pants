# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.codegen.targets.java_protobuf_library import JavaProtobufLibrary
from pants.backend.graph_info.tasks.cloc import CountLinesOfCode
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.build_environment import get_buildroot
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.from_target import FromTarget
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class ClocTest(ConsoleTaskTestBase):
  @classmethod
  def task_type(cls):
    return CountLinesOfCode

  @property
  def alias_groups(self):
    return BuildFileAliases(
      targets={
        'jar_library': JarLibrary,
        'unpacked_jars': UnpackedJars,
        'java_protobuf_library': JavaProtobufLibrary,
      },
      context_aware_object_factories={
        'from_target': FromTarget,
      },
      objects={
        'jar': JarDependency,
      }
    )

  def assert_counts(self, res, lang, files, blank, comment, code):
    for line in res:
      fields = [f for f in line.split('  ') if f]
      if len(fields) >= 5:
        if fields[0] == lang:
          self.assertEquals(files, int(fields[1]))
          self.assertEquals(blank, int(fields[2]))
          self.assertEquals(comment, int(fields[3]))
          self.assertEquals(code, int(fields[4]))
          return
    self.fail('Found no output line for {}'.format(lang))

  def test_counts(self):
    dep_python_target = self.make_target('src/py/dep', PythonLibrary, sources=['dep.py'])
    python_target = self.make_target('src/py/foo', PythonLibrary, dependencies=[dep_python_target],
                              sources=['foo.py', 'bar.py'])
    java_target = self.make_target('src/java/foo', JavaLibrary, sources=['Foo.java'])
    self.create_file('src/py/foo/foo.py', '# A comment.\n\nprint("some code")\n# Another comment.')
    self.create_file('src/py/foo/bar.py', '# A comment.\n\nprint("some more code")')
    self.create_file('src/py/dep/dep.py', 'print("a dependency")')
    self.create_file('src/java/foo/Foo.java', '// A comment. \n class Foo(){}\n')
    self.create_file('src/java/foo/Bar.java', '// We do not expect this file to appear in counts.')

    res = self.execute_console_task(targets=[python_target, java_target], options={'transitive': True})
    self.assert_counts(res, 'Python', files=3, blank=2, comment=3, code=3)
    self.assert_counts(res, 'Java', files=1, blank=0, comment=1, code=1)

    res = self.execute_console_task(targets=[python_target, java_target], options={'transitive': False})
    self.assert_counts(res, 'Python', files=2, blank=2, comment=3, code=2)
    self.assert_counts(res, 'Java', files=1, blank=0, comment=1, code=1)

  def test_ignored(self):
    py_tgt = self.make_target('src/py/foo', PythonLibrary, sources=['foo.py', 'empty.py'])
    self.create_file('src/py/foo/foo.py', 'print("some code")')
    self.create_file('src/py/foo/empty.py', '')

    res = self.execute_console_task(targets=[py_tgt], options={'ignored': True})
    self.assertEquals(['Ignored the following files:',
                       '{}/src/py/foo/empty.py: zero sized file'.format(get_buildroot())],
                      filter(None, res)[-2:])

  def test_counts_on_protobufs(self):
    proto_target = self.make_target('src/proto/foo', JavaProtobufLibrary, sources=['foo.proto'])
    self.create_file('src/proto/foo/foo.proto', '// A comment\n\nmessage Foo { required string bar = 1; }')
    res = self.execute_console_task(targets=[proto_target])
    self.assert_counts(res, 'Protocol Buffers', files=1, blank=1, comment=1, code=1)

  def test_counts_with_no_sources(self):
    no_sources_target = self.make_target('src/py', PythonLibrary)
    res = self.execute_console_task(targets=[no_sources_target])
    self.assertEquals('No report file was generated.  Are there any source files in your project?', res[0])

  def test_counts_on_deferred_target(self):
    self.add_to_build_file('root/proto', dedent("""
        java_protobuf_library(name='proto',
          sources=from_target(':external-source'),
        )

        unpacked_jars(name='external-source',
          libraries=[':external-source-jars'],
          include_patterns=[
            'com/example/testing/**/*.proto',
          ],
        )

        jar_library(name='external-source-jars',
          jars=[
            jar(org='com.example.testing.protolib', name='protolib-external-test', rev='0.0.2'),
          ],
        )
    """))
    res = self.execute_console_task(targets=[self.target('root/proto:proto')])

    self.assertEquals('No report file was generated.  Are there any source files in your project?', res[0])
