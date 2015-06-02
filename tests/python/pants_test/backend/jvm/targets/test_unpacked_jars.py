# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.core.register import build_file_aliases as register_core
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.jvm.targets.import_jars_mixin import ImportJarsMixin
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.base.address import BuildFileAddress
from pants_test.base_test import BaseTest


class UnpackedJarsTest(BaseTest):

  @property
  def alias_groups(self):
    return register_core().merge(register_jvm())

  def test_empty_libraries(self):
    build_file = self.add_to_build_file('BUILD', dedent('''
    unpacked_jars(name='foo',
    )'''))
    with self.assertRaises(UnpackedJars.ExpectedLibrariesError):
      self.build_graph.inject_address_closure(BuildFileAddress(build_file, 'foo'))


  def test_simple(self):
    build_file = self.add_to_build_file('BUILD', dedent('''
    unpacked_jars(name='foo',
      libraries=[':import_jars'],
    )

    jar_library(name='import_jars',
      jars=[
        jar(org='foo', name='bar', rev='123'),
      ],
    )
   '''))

    address = BuildFileAddress(build_file, 'foo')
    self.build_graph.inject_address_closure(address)
    target = self.build_graph.get_target(address)
    self.assertIsInstance(target, UnpackedJars)
    traversable_specs = [spec for spec in target.traversable_specs]
    self.assertSequenceEqual([':import_jars'], traversable_specs)
    self.assertEquals(1, len(target.imported_jars))
    import_jar_dep = target.imported_jars[0]
    self.assertIsInstance(import_jar_dep, JarDependency)


  def test_bad_libraries_ref(self):
    build_file = self.add_to_build_file('BUILD', dedent('''
    unpacked_jars(name='foo',
      libraries=[':wrong-type'],
    )

    unpacked_jars(name='wrong-type',
      libraries=[':right-type'],
    )

    jar_library(name='right-type',
      jars=[
        jar(org='foo', name='bar', rev='123'),
      ],
    )
   '''))
    address = BuildFileAddress(build_file, 'foo')
    self.build_graph.inject_address_closure(address)
    target = self.build_graph.get_target(address)
    with self.assertRaises(ImportJarsMixin.ExpectedJarLibraryError):
      target.imported_jar_libraries
