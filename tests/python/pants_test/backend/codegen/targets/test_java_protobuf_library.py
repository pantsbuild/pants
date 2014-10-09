# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

from pants.backend.codegen.targets.java_protobuf_library import JavaProtobufLibrary
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget

from pants.base.address import SyntheticAddress

from pants_test.base_test import BaseTest


class JavaProtobufLibraryTest(BaseTest):

  def setUp(self):
    super(JavaProtobufLibraryTest, self).setUp()
    self.build_file_parser._build_configuration.register_target_alias('java_protobuf_library', JavaProtobufLibrary)
    self.build_file_parser._build_configuration.register_target_alias('jar_library', JarLibrary)
    self.build_file_parser._build_configuration.register_exposed_object('jar', JarDependency)

  def test_empty(self):
    self.add_to_build_file('BUILD', dedent('''
    java_protobuf_library(name='foo',
      sources=[],
    )'''))
    self.build_graph.inject_spec_closure('//:foo')
    target = self.build_graph.get_target(SyntheticAddress.parse('//:foo'))
    self.assertIsInstance(target, JavaProtobufLibrary)
    self.assertSequenceEqual([], target.imports)
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
    self.build_graph.inject_spec_closure('//:foo')
    target = self.build_graph.get_target(SyntheticAddress.parse('//:foo'))
    self.assertIsInstance(target, JavaProtobufLibrary)
    self.assertEquals(1, len(target.imports))
    import_jar_dep = target.imports[0]
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
    self.build_graph.inject_spec_closure('//:foo')
    target = self.build_graph.get_target(SyntheticAddress.parse('//:foo'))
    self.assertIsInstance(target, JavaProtobufLibrary)
    with self.assertRaises(JarLibrary.WrongTargetTypeError):
      target.imports

  def test_wrong_import_type2(self):
    self.add_to_build_file('BUILD', dedent('''
      java_protobuf_library(name='foo',
        sources=[],
        imports=[
          jar(org='foo', name='bar', rev='123'),
        ],
      )
      '''))
    self.build_graph.inject_spec_closure('//:foo')
    target = self.build_graph.get_target(SyntheticAddress.parse('//:foo'))
    self.assertIsInstance(target, JavaProtobufLibrary)
    with self.assertRaises(JarLibrary.ExpectedAddressError):
      target.imports

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
    self.build_graph.inject_spec_closure('//:foo')
    target = self.build_graph.get_target(SyntheticAddress.parse('//:foo'))
    self.assertIsInstance(target, JavaProtobufLibrary)
    traversable_specs = [spec for spec in target.traversable_specs]
    self.assertSequenceEqual([':import_jars'], traversable_specs)


