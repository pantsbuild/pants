# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.codegen.targets.java_protobuf_library import JavaProtobufLibrary
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.build_file_aliases import BuildFileAliases
from pants_test.base_test import BaseTest


class JavaProtobufLibraryTest(BaseTest):

  @property
  def alias_groups(self):
    return BuildFileAliases.create(targets={'java_protobuf_library': JavaProtobufLibrary,
                                            'jar_library': JarLibrary},
                                   objects={'jar': JarDependency})

  def test_empty(self):
    self.add_to_build_file('BUILD', dedent('''
    java_protobuf_library(name='foo',
      sources=[],
    )'''))
    target = self.target('//:foo')
    self.assertIsInstance(target, JavaProtobufLibrary)
    self.assertSequenceEqual([], target.imported_jars)
    traversable_specs = [seq for seq in target.traversable_specs]
    self.assertSequenceEqual([], traversable_specs)

  def test_jar_library_imports(self):
    self.add_to_build_file('BUILD', dedent('''
    java_protobuf_library(name='foo',
      sources=[],
      imports=[':import_jars',]
    )
    jar_library(name='import_jars',
      jars=[
        jar(org='foo', name='bar', rev='123'),
      ],
    )
    '''))
    target = self.target('//:foo')
    self.assertIsInstance(target, JavaProtobufLibrary)
    self.assertEquals(1, len(target.imported_jars))
    import_jar_dep = target.imported_jars[0]
    self.assertIsInstance(import_jar_dep, JarDependency)

  def test_wrong_import_type1(self):
    self.add_to_build_file('BUILD', dedent('''
      java_protobuf_library(name='foo',
        sources=[],
        imports=[':not_jar']
      )

      java_protobuf_library(name='not_jar',
        sources=[],
      )
      '''))
    target = self.target('//:foo')
    self.assertIsInstance(target, JavaProtobufLibrary)
    with self.assertRaises(JarLibrary.WrongTargetTypeError):
      target.imported_jars

  def test_wrong_import_type2(self):
    self.add_to_build_file('BUILD', dedent('''
      java_protobuf_library(name='foo',
        sources=[],
        imports=[
          jar(org='foo', name='bar', rev='123'),
        ],
      )
      '''))
    target = self.target('//:foo')
    self.assertIsInstance(target, JavaProtobufLibrary)
    with self.assertRaises(JarLibrary.ExpectedAddressError):
      target.imported_jars

  def test_traversable_specs(self):
    self.add_to_build_file('BUILD', dedent('''
    java_protobuf_library(name='foo',
      sources=[],
      imports=[':import_jars',],
      # Note: Should not be a part of traversable_specs
      dependencies=[
        ':proto_dep',
      ]
    )
    jar_library(name='import_jars',
      jars=[
        jar(org='foo', name='bar', rev='123'),
      ],
    )
    java_protobuf_library(name='proto_dep',
        sources=[],
    )
    '''))
    target = self.target('//:foo')
    self.assertIsInstance(target, JavaProtobufLibrary)
    traversable_specs = [spec for spec in target.traversable_specs]
    self.assertSequenceEqual([':import_jars'], traversable_specs)
