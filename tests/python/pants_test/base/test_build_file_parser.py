# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

import pytest

from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.repository import Repository
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.base.address import BuildFileAddress
from pants.base.build_file import FilesystemBuildFile
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.build_file_parser import BuildFileParser
from pants.base.target import Target
from pants_test.base_test import BaseTest


# TODO(Eric Ayers) Explicit unit tests are missing for registered_alises, parse_spec,
# parse_build_file_family

class ErrorTarget(Target):

  def __init__(self, *args, **kwargs):
    assert False, "This fake target should never be initialized in this test!"


class BuildFileParserBasicsTest(BaseTest):

  def test_addressable_exceptions(self):
    self.add_to_build_file('a/BUILD', 'target()')
    build_file_a = FilesystemBuildFile(self.build_root, 'a/BUILD')

    with pytest.raises(BuildFileParser.ExecuteError):
      self.build_file_parser.parse_build_file(build_file_a)

    self.add_to_build_file('b/BUILD', 'target(name="foo", "bad_arg")')
    build_file_b = FilesystemBuildFile(self.build_root, 'b/BUILD')
    with pytest.raises(BuildFileParser.BuildFileParserError):
      self.build_file_parser.parse_build_file(build_file_b)

    self.add_to_build_file('d/BUILD', dedent(
      '''
      target(
        name="foo",
        dependencies=[
          object(),
        ]
      )
      '''
    ))
    build_file_d = FilesystemBuildFile(self.build_root, 'd/BUILD')
    with pytest.raises(BuildFileParser.BuildFileParserError):
      self.build_file_parser.parse_build_file(build_file_d)

  def test_noop_parse(self):
    self.add_to_build_file('BUILD', '')
    build_file = FilesystemBuildFile(self.build_root, '')
    address_map = set(self.build_file_parser.parse_build_file(build_file))
    self.assertEqual(len(address_map), 0)


class BuildFileParserTargetTest(BaseTest):

  @property
  def alias_groups(self):
    return BuildFileAliases.create(targets={'fake': ErrorTarget})

  def test_trivial_target(self):
    self.add_to_build_file('BUILD', '''fake(name='foozle')''')
    build_file = FilesystemBuildFile(self.build_root, 'BUILD')
    address_map = self.build_file_parser.parse_build_file(build_file)

    self.assertEqual(len(address_map), 1)
    address, proxy = address_map.popitem()
    self.assertEqual(address, BuildFileAddress(build_file, 'foozle'))
    self.assertEqual(proxy.name, 'foozle')
    self.assertEqual(proxy.target_type, ErrorTarget)

  def test_trivial_target(self):
    self.add_to_build_file('BUILD', '''fake(name='foozle')''')
    build_file = FilesystemBuildFile(self.build_root, 'BUILD')
    address_map = self.build_file_parser.parse_build_file(build_file)
    self.assertEqual(len(address_map), 1)
    address, addressable = address_map.popitem()
    self.assertEqual(address, BuildFileAddress(build_file, 'foozle'))
    self.assertEqual(addressable.name, 'foozle')
    self.assertEqual(addressable.target_type, ErrorTarget)

  def test_sibling_build_files(self):
    self.add_to_build_file('BUILD', dedent(
      '''
      fake(name="base",
           dependencies=[
             ':foo',
           ])
      '''))

    self.add_to_build_file('BUILD.foo', dedent(
      '''
      fake(name="foo",
           dependencies=[
             ':bat',
           ])
      '''))

    self.add_to_build_file('./BUILD.bar', dedent(
      '''
      fake(name="bat")
      '''))

    bar_build_file = FilesystemBuildFile(self.build_root, 'BUILD.bar')
    base_build_file = FilesystemBuildFile(self.build_root, 'BUILD')
    foo_build_file = FilesystemBuildFile(self.build_root, 'BUILD.foo')

    address_map = self.build_file_parser.address_map_from_build_file(bar_build_file)
    addresses = address_map.keys()
    self.assertEqual(set([bar_build_file, base_build_file, foo_build_file]),
                     set([address.build_file for address in addresses]))
    self.assertEqual(set([':base', ':foo', ':bat']),
                     set([address.spec for address in addresses]))

  def test_build_file_duplicates(self):
    # This workspace has two targets in the same file with the same name.
    self.add_to_build_file('BUILD', 'fake(name="foo")\n')
    self.add_to_build_file('BUILD', 'fake(name="foo")\n')

    with pytest.raises(BuildFileParser.AddressableConflictException):
      base_build_file = FilesystemBuildFile(self.build_root, 'BUILD')
      self.build_file_parser.parse_build_file(base_build_file)

  def test_sibling_build_files_duplicates(self):
    # This workspace is malformed, you can't shadow a name in a sibling BUILD file
    self.add_to_build_file('BUILD', dedent(
      '''
      fake(name="base",
           dependencies=[
             ':foo',
           ])
      '''))

    self.add_to_build_file('BUILD.foo', dedent(
      '''
      fake(name="foo",
           dependencies=[
             ':bat',
           ])
      '''))

    self.add_to_build_file('./BUILD.bar', dedent(
      '''
      fake(name="base")
      '''))

    with pytest.raises(BuildFileParser.SiblingConflictException):
      base_build_file = FilesystemBuildFile(self.build_root, 'BUILD')
      bf_address = BuildFileAddress(base_build_file, 'base')
      self.build_file_parser.address_map_from_build_file(base_build_file)


class BuildFileParserExposedObjectTest(BaseTest):

  @property
  def alias_groups(self):
    return BuildFileAliases.create(objects={'fake_object': object()})

  def test_exposed_object(self):
    self.add_to_build_file('BUILD', '''fake_object''')
    build_file = FilesystemBuildFile(self.build_root, 'BUILD')
    address_map = self.build_file_parser.parse_build_file(build_file)
    self.assertEqual(len(address_map), 0)


class BuildFileParserExposedContextAwareObjectFactoryTest(BaseTest):

  @staticmethod
  def make_lib(parse_context):
    def real_make_lib(org, name, rev):
      dep = parse_context.create_object('jar', org=org, name=name, rev=rev)
      parse_context.create_object('jar_library', name=name, jars=[dep])
    return real_make_lib

  @staticmethod
  def create_java_libraries(parse_context):

    def real_create_java_libraries(base_name,
                                   org='com.twitter',
                                   provides_java_name=None,
                                   provides_scala_name=None):

      def provides_artifact(provides_name):
        if provides_name is None:
          return None
        jvm_repo = Repository(
          name='maven-central',
          url='http://maven.example.com',
          push_db_basedir=os.path.join('build-support', 'ivy', 'pushdb'),
        )
        return parse_context.create_object('artifact',
                                           org=org,
                                           name=provides_name,
                                           repo=jvm_repo)

      parse_context.create_object('java_library',
                                  name='%s-java' % base_name,
                                  sources=[],
                                  dependencies=[],
                                  provides=provides_artifact(provides_java_name))

      parse_context.create_object('scala_library',
                                  name='%s-scala' % base_name,
                                  sources=[],
                                  dependencies=[],
                                  provides=provides_artifact(provides_scala_name))

    return real_create_java_libraries

  def setUp(self):
    super(BuildFileParserExposedContextAwareObjectFactoryTest, self).setUp()
    self._paths = set()

  def path_relative_util(self, parse_context):
    def real_path_relative_util(path):
      self._paths.add(os.path.join(parse_context.rel_path, path))
    return real_path_relative_util

  @property
  def alias_groups(self):
    return BuildFileAliases.create(
      targets={
        'jar_library': JarLibrary,
        'java_library': JavaLibrary,
        'scala_library': ScalaLibrary,
      },
      context_aware_object_factories={
        'make_lib': self.make_lib,
        'create_java_libraries': self.create_java_libraries,
        'path_util': self.path_relative_util,
      },
      objects={
        'artifact': Artifact,
        'jar': JarDependency,
      }
    )

  def test_context_aware_object_factories(self):
    contents = dedent('''
                 create_java_libraries(base_name="create-java-libraries",
                                       provides_java_name="test-java",
                                       provides_scala_name="test-scala")
                 make_lib("com.foo.test", "does_not_exists", "1.0")
                 path_util("baz")
               ''')
    self.create_file('3rdparty/BUILD', contents)

    build_file = FilesystemBuildFile(self.build_root, '3rdparty/BUILD')
    address_map = self.build_file_parser.parse_build_file(build_file)
    registered_proxies = set(address_map.values())

    self.assertEqual(len(registered_proxies), 3)
    targets_created = {}
    for target_proxy in registered_proxies:
      targets_created[target_proxy.name] = target_proxy.target_type

    self.assertEqual(set(['does_not_exists',
                          'create-java-libraries-scala',
                          'create-java-libraries-java']),
                     set(targets_created.keys()))
    self.assertEqual(targets_created['does_not_exists'], JarLibrary)
    self.assertEqual(targets_created['create-java-libraries-java'], JavaLibrary)
    self.assertEqual(targets_created['create-java-libraries-scala'], ScalaLibrary)

    self.assertEqual(set(['3rdparty/baz']), self._paths)

  def test_raises_parse_error(self):
    self.add_to_build_file('BUILD', 'foo(name = = "baz")')
    build_file = FilesystemBuildFile(self.build_root, 'BUILD')
    with self.assertRaises(BuildFileParser.ParseError):
      self.build_file_parser.parse_build_file(build_file)

    # Test some corner cases for the context printing

    # Error at beginning of BUILD file
    build_file = self.add_to_build_file('begin/BUILD', dedent('''
      *?&INVALID! = 'foo'
      target(
        name='bar',
        dependencies= [
          ':baz',
        ],
      )
      '''))
    with self.assertRaises(BuildFileParser.ParseError):
      self.build_file_parser.parse_build_file(build_file)

    # Error at end of BUILD file
    build_file = self.add_to_build_file('end/BUILD', dedent('''
      target(
        name='bar',
        dependencies= [
          ':baz',
        ],
      )
      *?&INVALID! = 'foo'
      '''))
    with self.assertRaises(BuildFileParser.ParseError):
      self.build_file_parser.parse_build_file(build_file)

    # Error in the middle of BUILD file > 6 lines
    build_file = self.add_to_build_file('middle/BUILD', dedent('''
      target(
        name='bar',

              *?&INVALID! = 'foo'

        dependencies = [
          ':baz',
        ],
      )
      '''))
    with self.assertRaises(BuildFileParser.ParseError):
      self.build_file_parser.parse_build_file(build_file)

    # Error in very short build file.
    build_file = self.add_to_build_file('short/BUILD', dedent('''
      target(name='bar', dependencies = [':baz'],) *?&INVALID! = 'foo'
      '''))
    with self.assertRaises(BuildFileParser.ParseError):
      self.build_file_parser.parse_build_file(build_file)

  def test_raises_execute_error(self):
    self.add_to_build_file('BUILD', 'undefined_alias(name="baz")')
    build_file = FilesystemBuildFile(self.build_root, 'BUILD')
    with self.assertRaises(BuildFileParser.ExecuteError):
      self.build_file_parser.parse_build_file(build_file)

  def test_build_file_parser_error_hierarcy(self):
    """Exception handling code depends on the fact that all explicit exceptions from BuildFileParser are
   subclassed from the BuildFileParserError base class.
   """
    self.assertIsInstance(BuildFileParser.BuildFileScanError(), BuildFileParser.BuildFileParserError)
    self.assertIsInstance(BuildFileParser.AddressableConflictException(), BuildFileParser.BuildFileParserError)
    self.assertIsInstance(BuildFileParser.SiblingConflictException(), BuildFileParser.BuildFileParserError)
    self.assertIsInstance(BuildFileParser.ParseError(), BuildFileParser.BuildFileParserError)
    self.assertIsInstance(BuildFileParser.ExecuteError(), BuildFileParser.BuildFileParserError)
