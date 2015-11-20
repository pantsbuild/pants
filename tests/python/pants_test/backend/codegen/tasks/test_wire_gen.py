# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.codegen.register import build_file_aliases as register_codegen
from pants.backend.codegen.targets.java_wire_library import JavaWireLibrary
from pants.backend.codegen.tasks.wire_gen import WireGen
from pants.backend.core.register import build_file_aliases as register_core
from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.exceptions import TaskError
from pants.base.revision import Revision
from pants.build_graph.target import Target
from pants_test.tasks.task_test_base import TaskTestBase


class WireGenTest(TaskTestBase):

  # A bogus target workdir.
  TARGET_WORKDIR = ".pants.d/bogus/workdir"

  @classmethod
  def task_type(cls):
    return WireGen

  @property
  def alias_groups(self):
    return register_core().merge(register_codegen())

  def _create_fake_wire_tool(self, version='1.8.0'):
    self.make_target(':wire-compiler', JarLibrary, jars=[
      JarDependency(org='com.squareup.wire', name='wire-compiler', rev=version),
    ])

  def test_compiler_args(self):
    self._create_fake_wire_tool()
    simple_wire_target = self.make_target('src/wire:simple-wire-target', JavaWireLibrary,
                                          sources=['foo.proto'])
    context = self.context(target_roots=[simple_wire_target])
    task = self.create_task(context)
    self.assertEquals([
      '--java_out={}'.format(self.TARGET_WORKDIR),
      '--proto_path={}/src/wire'.format(self.build_root),
      'foo.proto'],
      task.format_args_for_target(simple_wire_target, self.TARGET_WORKDIR))

  def test_compiler_args_wirev1(self):
    self._create_fake_wire_tool()
    wire_targetv1 = self.make_target('src/wire:wire-targetv1', JavaWireLibrary,
                                     sources=['bar.proto'],
                                     service_writer='org.pantsbuild.DummyServiceWriter',
                                     service_writer_options=['opt1', 'opt2'])
    task = self.create_task(self.context(target_roots=[wire_targetv1]))
    self.assertEquals([
      '--java_out={}'.format(self.TARGET_WORKDIR),
      '--service_writer=org.pantsbuild.DummyServiceWriter',
      '--service_writer_opt', 'opt1',
      '--service_writer_opt', 'opt2',
      '--proto_path={}/src/wire'.format(self.build_root),
      'bar.proto'],
      task.format_args_for_target(wire_targetv1, self.TARGET_WORKDIR))

  def test_compiler_args_all(self):
    self._create_fake_wire_tool(version='1.8.0')
    kitchen_sink = self.make_target('src/wire:kitchen-sink', JavaWireLibrary,
                                    sources=['foo.proto', 'bar.proto', 'baz.proto'],
                                    registry_class='org.pantsbuild.Registry',
                                    service_writer='org.pantsbuild.DummyServiceWriter',
                                    no_options=True,
                                    roots=['root1', 'root2', 'root3'],
                                    enum_options=['enum1', 'enum2', 'enum3'],)
    task = self.create_task(self.context(target_roots=[kitchen_sink]))
    self.assertEquals([
      '--java_out={}'.format(self.TARGET_WORKDIR),
      '--no_options',
      '--service_writer=org.pantsbuild.DummyServiceWriter',
      '--registry_class=org.pantsbuild.Registry',
      '--roots=root1,root2,root3',
      '--enum_options=enum1,enum2,enum3',
      '--proto_path={}/src/wire'.format(self.build_root),
      'foo.proto',
      'bar.proto',
      'baz.proto'],
      task.format_args_for_target(kitchen_sink, self.TARGET_WORKDIR))

  def test_compiler_args_proto_paths(self):
    self._create_fake_wire_tool()
    parent_target = self.make_target('src/main/wire:parent-target', JavaWireLibrary,
                                     sources=['bar.proto'])
    simple_wire_target = self.make_target('src/wire:simple-wire-target', JavaWireLibrary,
                                          sources=['foo.proto'], dependencies=[parent_target])
    context = self.context(target_roots=[parent_target, simple_wire_target])
    task = self.create_task(context)
    self.assertEquals([
      '--java_out={}'.format(self.TARGET_WORKDIR),
      '--proto_path={}/src/wire'.format(self.build_root),
      'foo.proto'],
      task.format_args_for_target(simple_wire_target, self.TARGET_WORKDIR))
