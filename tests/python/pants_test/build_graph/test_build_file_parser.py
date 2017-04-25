# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import namedtuple
from textwrap import dedent

from pants.base.build_file import BuildFile
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.build_graph.address import BuildFileAddress
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.build_file_parser import BuildFileParser
from pants.build_graph.target import Target
from pants.util.strutil import ensure_binary
from pants_test.base_test import BaseTest


# TODO(Eric Ayers) Explicit unit tests are missing for registered_alises, parse_spec,
# parse_build_file_family
class ErrorTarget(Target):

  def __init__(self, *args, **kwargs):
    assert False, "This fake target should never be initialized in this test!"


class BuildFileParserBasicsTest(BaseTest):

  @property
  def alias_groups(self):
    return BuildFileAliases(targets={'jvm_binary': ErrorTarget,
                                     'java_library': ErrorTarget})

  def create_buildfile(self, path):
    return BuildFile(FileSystemProjectTree(self.build_root), path)

  def assert_parser_error(self, build_file, err_string):
    with self.assertRaises(BuildFileParser.BuildFileParserError) as ctx:
      self.build_file_parser.parse_build_file(build_file)
    self.assertIn(err_string, str(ctx.exception))

  def test_name_injection(self):
    # Target with no name is fine: target gets name of directory.
    self.add_to_build_file('foo/bar/BUILD', '\njava_library()\n')
    build_file = self.create_buildfile('foo/bar/BUILD')
    addresses = list(self.build_file_parser.parse_build_file(build_file).keys())
    self.assertEqual(1, len(addresses))
    self.assertEqual('bar', addresses[0].target_name)

    # Two targets with no name in the same BUILD file cause an error.
    self.add_to_build_file('foo/bar/BUILD', '\njvm_binary()\n')
    self.assert_parser_error(build_file, "defines address 'bar' more than once")

    # Test that omitting the name in a target at the build root is disallowed.
    self.add_to_build_file('BUILD', '\njava_library()\n')
    build_file = self.create_buildfile('BUILD')
    self.assert_parser_error(build_file,
                             "Targets in root-level BUILD files must be named explicitly")

  def test_addressable_exceptions(self):
    self.add_to_build_file('b/BUILD', 'java_library(name="foo", "bad_arg")')
    build_file_b = self.create_buildfile('b/BUILD')
    self.assert_parser_error(build_file_b,
                             'non-keyword arg after keyword arg')

    self.add_to_build_file('d/BUILD', dedent(
      """
      java_library(
        name="foo",
        dependencies=[
          object(),
        ]
      )
      """
    ))
    build_file_d = self.create_buildfile('d/BUILD')
    self.assert_parser_error(build_file_d,
                             'dependencies passed to Target constructors must be strings')

  def test_noop_parse(self):
    self.add_to_build_file('BUILD', '')
    build_file = self.create_buildfile('BUILD')
    address_map = set(self.build_file_parser.parse_build_file(build_file))
    self.assertEqual(len(address_map), 0)

  def test_invalid_unicode_in_build_file(self):
    """Demonstrate that unicode characters causing parse errors raise real parse errors."""
    self.add_to_build_file('BUILD', ensure_binary(dedent(
      """
      jvm_binary(name = ‘hello’,  # Parse error due to smart quotes (non ascii characters)
        source = 'HelloWorld.java'
        main = 'foo.HelloWorld',
      )
      """
    )))
    build_file = self.create_buildfile('BUILD')
    self.assert_parser_error(build_file, 'invalid syntax')

  def test_unicode_string_in_build_file(self):
    """Demonstrates that a string containing unicode should work in a BUILD file."""
    self.add_to_build_file('BUILD', ensure_binary(dedent(
        """
        java_library(
          name='foo',
          sources=['א.java']
        )
        """
    )))
    build_file = self.create_buildfile('BUILD')
    self.build_file_parser.parse_build_file(build_file)


class BuildFileParserTargetTest(BaseTest):
  @property
  def alias_groups(self):
    return BuildFileAliases(targets={'fake': ErrorTarget})

  def create_buildfile(self, path):
    return BuildFile(FileSystemProjectTree(self.build_root), path)

  def test_trivial_target(self):
    self.add_to_build_file('BUILD', 'fake(name="foozle")')
    build_file = self.create_buildfile('BUILD')
    address_map = self.build_file_parser.parse_build_file(build_file)

    self.assertEqual(len(address_map), 1)
    address, proxy = address_map.popitem()
    self.assertEqual(address, BuildFileAddress(build_file=build_file, target_name='foozle'))
    self.assertEqual(proxy.addressed_name, 'foozle')
    self.assertEqual(proxy.addressed_type, ErrorTarget)

  def test_sibling_build_files(self):
    self.add_to_build_file('BUILD', dedent(
      """
      fake(name="base",
           dependencies=[
             ':foo',
           ])
      """))

    self.add_to_build_file('BUILD.foo', dedent(
      """
      fake(name="foo",
           dependencies=[
             ':bat',
           ])
      """))

    self.add_to_build_file('./BUILD.bar', dedent(
      """
      fake(name="bat")
      """))

    bar_build_file = self.create_buildfile('BUILD.bar')
    base_build_file = self.create_buildfile('BUILD')
    foo_build_file = self.create_buildfile('BUILD.foo')

    address_map = self.build_file_parser.address_map_from_build_files(
      BuildFile.get_build_files_family(FileSystemProjectTree(self.build_root), "."))
    addresses = address_map.keys()
    self.assertEqual({bar_build_file.relpath, base_build_file.relpath, foo_build_file.relpath},
                     set([address.rel_path for address in addresses]))
    self.assertEqual({'//:base', '//:foo', '//:bat'},
                     set([address.spec for address in addresses]))

  def test_build_file_duplicates(self):
    # This workspace has two targets in the same file with the same name.
    self.add_to_build_file('BUILD', 'fake(name="foo")\n')
    self.add_to_build_file('BUILD', 'fake(name="foo")\n')

    with self.assertRaises(BuildFileParser.AddressableConflictException):
      base_build_file = self.create_buildfile('BUILD')
      self.build_file_parser.parse_build_file(base_build_file)

  def test_sibling_build_files_duplicates(self):
    # This workspace is malformed, you can't shadow a name in a sibling BUILD file
    self.add_to_build_file('BUILD', dedent(
      """
      fake(name="base",
           dependencies=[
             ':foo',
           ])
      """))

    self.add_to_build_file('BUILD.foo', dedent(
      """
      fake(name="foo",
           dependencies=[
             ':bat',
           ])
      """))

    self.add_to_build_file('./BUILD.bar', dedent(
      """
      fake(name="base")
      """))

    with self.assertRaises(BuildFileParser.SiblingConflictException):
      self.build_file_parser.address_map_from_build_files(
        BuildFile.get_build_files_family(FileSystemProjectTree(self.build_root), '.'))


class BuildFileParserExposedObjectTest(BaseTest):

  @property
  def alias_groups(self):
    return BuildFileAliases(objects={'fake_object': object()})

  def test_exposed_object(self):
    self.add_to_build_file('BUILD', """fake_object""")
    build_file = BuildFile(FileSystemProjectTree(self.build_root), 'BUILD')
    address_map = self.build_file_parser.parse_build_file(build_file)
    self.assertEqual(len(address_map), 0)


class BuildFileParserExposedContextAwareObjectFactoryTest(BaseTest):

  Jar = namedtuple('Jar', ['org', 'name', 'rev'])
  Repository = namedtuple('Repository', ['name', 'url', 'push_db_basedir'])
  Artifact = namedtuple('Artifact', ['org', 'name', 'repo'])

  class JarLibrary(Target):
    def __init__(self, jars=None, **kwargs):
      super(BuildFileParserExposedContextAwareObjectFactoryTest.JarLibrary, self).__init__(**kwargs)
      self.jars = jars or []

  class JvmLibrary(Target):
    def __init__(self, provides=None, **kwargs):
      super(BuildFileParserExposedContextAwareObjectFactoryTest.JvmLibrary, self).__init__(**kwargs)
      self.provides = provides

  class JavaLibrary(JvmLibrary):
    pass

  class ScalaLibrary(JvmLibrary):
    pass

  @classmethod
  def make_lib(cls, parse_context):
    def real_make_lib(org, name, rev):
      dep = parse_context.create_object('jar', org=org, name=name, rev=rev)
      parse_context.create_object('jar_library', name=name, jars=[dep])
    return real_make_lib

  @classmethod
  def create_java_libraries(cls, parse_context):

    def real_create_java_libraries(base_name,
                                   org='com.twitter',
                                   provides_java_name=None,
                                   provides_scala_name=None):

      def provides_artifact(provides_name):
        if provides_name is None:
          return None
        jvm_repo = cls.Repository(
          name='maven-central',
          url='http://maven.example.com',
          push_db_basedir=os.path.join('build-support', 'ivy', 'pushdb'),
        )
        return parse_context.create_object('artifact',
                                           org=org,
                                           name=provides_name,
                                           repo=jvm_repo)

      parse_context.create_object('java_library',
                                  name='{}-java'.format(base_name),
                                  provides=provides_artifact(provides_java_name))

      parse_context.create_object('scala_library',
                                  name='{}-scala'.format(base_name),
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
    return BuildFileAliases(
      targets={
        'jar_library': self.JarLibrary,
        'java_library': self.JavaLibrary,
        'scala_library': self.ScalaLibrary,
      },
      context_aware_object_factories={
        'make_lib': self.make_lib,
        'create_java_libraries': self.create_java_libraries,
        'path_util': self.path_relative_util,
      },
      objects={
        'artifact': self.Artifact,
        'jar': self.Jar,
      }
    )

  def test_context_aware_object_factories(self):
    contents = dedent("""
                 create_java_libraries(base_name="create-java-libraries",
                                       provides_java_name="test-java",
                                       provides_scala_name="test-scala")
                 make_lib("com.foo.test", "does_not_exists", "1.0")
                 path_util("baz")
               """)
    self.create_file('3rdparty/BUILD', contents)

    build_file = BuildFile(FileSystemProjectTree(self.build_root), '3rdparty/BUILD')
    address_map = self.build_file_parser.parse_build_file(build_file)
    registered_proxies = set(address_map.values())

    self.assertEqual(len(registered_proxies), 3)
    targets_created = {}
    for target_proxy in registered_proxies:
      targets_created[target_proxy.addressed_name] = target_proxy.addressed_type

    self.assertEqual({'does_not_exists',
                      'create-java-libraries-scala',
                      'create-java-libraries-java'},
                     set(targets_created.keys()))
    self.assertEqual(targets_created['does_not_exists'], self.JarLibrary)
    self.assertEqual(targets_created['create-java-libraries-java'], self.JavaLibrary)
    self.assertEqual(targets_created['create-java-libraries-scala'], self.ScalaLibrary)

    self.assertEqual({'3rdparty/baz'}, self._paths)

  def test_raises_parse_error(self):
    self.add_to_build_file('BUILD', 'foo(name = = "baz")')
    build_file = BuildFile(FileSystemProjectTree(self.build_root), 'BUILD')
    with self.assertRaises(BuildFileParser.ParseError):
      self.build_file_parser.parse_build_file(build_file)

    # Test some corner cases for the context printing

    # Error at beginning of BUILD file
    build_file = self.add_to_build_file('begin/BUILD', dedent("""
      *?&INVALID! = 'foo'
      target(
        name='bar',
        dependencies= [
          ':baz',
        ],
      )
      """))
    with self.assertRaises(BuildFileParser.ParseError):
      self.build_file_parser.parse_build_file(build_file)

    # Error at end of BUILD file
    build_file = self.add_to_build_file('end/BUILD', dedent("""
      target(
        name='bar',
        dependencies= [
          ':baz',
        ],
      )
      *?&INVALID! = 'foo'
      """))
    with self.assertRaises(BuildFileParser.ParseError):
      self.build_file_parser.parse_build_file(build_file)

    # Error in the middle of BUILD file > 6 lines
    build_file = self.add_to_build_file('middle/BUILD', dedent("""
      target(
        name='bar',

              *?&INVALID! = 'foo'

        dependencies = [
          ':baz',
        ],
      )
      """))
    with self.assertRaises(BuildFileParser.ParseError):
      self.build_file_parser.parse_build_file(build_file)

    # Error in very short build file.
    build_file = self.add_to_build_file('short/BUILD', dedent("""
      target(name='bar', dependencies = [':baz'],) *?&INVALID! = 'foo'
      """))
    with self.assertRaises(BuildFileParser.ParseError):
      self.build_file_parser.parse_build_file(build_file)

  def test_raises_execute_error(self):
    self.add_to_build_file('BUILD', 'undefined_alias(name="baz")')
    build_file = BuildFile(FileSystemProjectTree(self.build_root), 'BUILD')
    with self.assertRaises(BuildFileParser.ExecuteError):
      self.build_file_parser.parse_build_file(build_file)

  def test_build_file_parser_error_hierarcy(self):
    """Exception handling code depends on the fact that all explicit exceptions from BuildFileParser
    are subclassed from the BuildFileParserError base class.
    """
    def assert_build_file_parser_error(e):
      self.assertIsInstance(e, BuildFileParser.BuildFileParserError)

    assert_build_file_parser_error(BuildFileParser.BuildFileScanError())
    assert_build_file_parser_error(BuildFileParser.AddressableConflictException())
    assert_build_file_parser_error(BuildFileParser.SiblingConflictException())
    assert_build_file_parser_error(BuildFileParser.ParseError())
    assert_build_file_parser_error(BuildFileParser.ExecuteError())
