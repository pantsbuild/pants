# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from textwrap import dedent

from pants.backend.codegen.protobuf.java.java_protobuf_library import JavaProtobufLibrary
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.scala_jar_dependency import ScalaJarDependency
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.java.jar.jar_dependency import JarDependency
from pants_test.test_base import TestBase


class JavaProtobufLibraryTest(TestBase):

  @classmethod
  def alias_groups(cls):
    return BuildFileAliases(
        targets={
          'java_protobuf_library': JavaProtobufLibrary,
          'jar_library': JarLibrary},
        objects={
          'jar': JarDependency,
          'scala_jar': ScalaJarDependency,
        }
      )

  def test_empty(self):
    self.add_to_build_file('BUILD', dedent('''
    java_protobuf_library(name='foo',
      sources=[],
    )'''))
    target = self.target('//:foo')
    self.assertIsInstance(target, JavaProtobufLibrary)
    self.assertSequenceEqual([], target.all_imported_jar_deps)

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
    self.assertEqual(1, len(target.all_imported_jar_deps))
    import_jar_dep = target.all_imported_jar_deps[0]
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
    with self.assertRaises(JavaProtobufLibrary.WrongTargetTypeError):
      target.all_imported_jar_deps

  def test_wrong_import_type2(self):
    self.add_to_build_file('BUILD', dedent('''
      java_protobuf_library(name='foo',
        sources=[],
        imports=[
          jar(org='foo', name='bar', rev='123'),
        ],
      )
      '''))
    with self.assertRaises(JavaProtobufLibrary.ExpectedAddressError):
      self.target('//:foo')

  def test_compute_dependency_specs(self):
    self.add_to_build_file('BUILD', dedent('''
    java_protobuf_library(name='foo',
      sources=[],
      imports=[':import_jars',],
      # Note: Should not be a part of dependency specs.
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
    self.assertEqual([':import_jars'], list(target.compute_dependency_specs(payload=target.payload)))
