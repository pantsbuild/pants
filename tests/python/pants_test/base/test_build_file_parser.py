# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from textwrap import dedent

import pytest

from pants.base.address import BuildFileAddress
from pants.base.build_file import BuildFile
from pants.base.build_file_parser import BuildFileParser
from pants.base.exceptions import TargetDefinitionException

from pants_test.base_test import BaseTest


class BuildFileParserTest(BaseTest):
  def setUp(self):
    super(BuildFileParserTest, self).setUp()

  def test_target_proxy_exceptions(self):
    self.add_to_build_file('a/BUILD', 'dependencies()')
    build_file_a = BuildFile(self.build_root, 'a/BUILD')

    with pytest.raises(ValueError):
      self.build_file_parser.parse_build_file(build_file_a)

    self.add_to_build_file('b/BUILD', 'dependencies(name="foo", "bad_arg")')
    build_file_b = BuildFile(self.build_root, 'b/BUILD')
    with pytest.raises(ValueError):
      self.build_file_parser.parse_build_file(build_file_b)

    self.add_to_build_file('c/BUILD', 'dependencies(name="foo", build_file="bad")')
    build_file_c = BuildFile(self.build_root, 'c/BUILD')
    with pytest.raises(ValueError):
      self.build_file_parser.parse_build_file(build_file_c)

    self.add_to_build_file('d/BUILD', dedent(
      '''
      dependencies(name="foo",
        dependencies=[
          object(),
        ]
      )
      '''
    )
    build_file_d = BuildFile(self.build_root, 'd/BUILD')
    with pytest.raises(TargetDefinitionException):
      self.build_file_parser.parse_build_file(build_file_d)


  def test_noop_parse(self):
    with self.workspace('BUILD') as root_dir:
      parser = BuildFileParser(root_dir=root_dir,
                               exposed_objects={},
                               path_relative_utils={},
                               target_alias_map={})
      build_file = BuildFile(root_dir, '')
      parser.parse_build_file(build_file)
      registered_proxies = set(parser._target_proxy_by_address.values())
      self.assertEqual(len(registered_proxies), 0)

  def test_trivial_target(self):
    with self.workspace('BUILD') as root_dir:
      def fake_target(*args, **kwargs):
        assert False, "This fake target should never be called in this test!"

      parser = BuildFileParser(root_dir=root_dir,
                               exposed_objects={},
                               path_relative_utils={},
                               target_alias_map={'fake': fake_target})

      with open(os.path.join(root_dir, 'BUILD'), 'w') as build:
        build.write('''fake(name='foozle')''')

      build_file = BuildFile(root_dir, 'BUILD')
      parser.parse_build_file(build_file)
      registered_proxies = set(parser._target_proxy_by_address.values())

    self.assertEqual(len(registered_proxies), 1)
    proxy = registered_proxies.pop()
    self.assertEqual(proxy.name, 'foozle')
    self.assertEqual(proxy.address, BuildFileAddress(build_file, 'foozle'))
    self.assertEqual(proxy.target_type, fake_target)

  def test_exposed_object(self):
    with self.workspace('BUILD') as root_dir:
      parser = BuildFileParser(root_dir=root_dir,
                               exposed_objects={'fake_object': object()},
                               path_relative_utils={},
                               target_alias_map={})

      with open(os.path.join(root_dir, 'BUILD'), 'w') as build:
        build.write('''fake_object''')

      build_file = BuildFile(root_dir, 'BUILD')
      parser.parse_build_file(build_file)
      registered_proxies = set(parser._target_proxy_by_address.values())

    self.assertEqual(len(registered_proxies), 0)

  def test_path_relative_util(self):
    with self.workspace('a/b/c/BUILD') as root_dir:
      def path_relative_util(foozle, rel_path):
        self.assertEqual(rel_path, 'a/b/c')

      parser = BuildFileParser(root_dir=root_dir,
                               exposed_objects={},
                               path_relative_utils={'fake_util': path_relative_util},
                               target_alias_map={})

      with open(os.path.join(root_dir, 'a/b/c/BUILD'), 'w') as build:
        build.write('''fake_util("baz")''')

      build_file = BuildFile(root_dir, 'a/b/c/BUILD')
      parser.parse_build_file(build_file)
      registered_proxies = set(parser._target_proxy_by_address.values())

    self.assertEqual(len(registered_proxies), 0)

  def test_transitive_closure_spec(self):
    with self.workspace('./BUILD', 'a/BUILD', 'a/b/BUILD') as root_dir:
      with open(os.path.join(root_dir, './BUILD'), 'w') as build:
        build.write(dedent('''
          fake(name="foo",
               dependencies=[
                 'a',
               ])
        '''))

      with open(os.path.join(root_dir, 'a/BUILD'), 'w') as build:
        build.write(dedent('''
          fake(name="a",
               dependencies=[
                 'a/b:bat',
               ])
        '''))

      with open(os.path.join(root_dir, 'a/b/BUILD'), 'w') as build:
        build.write(dedent('''
          fake(name="bat")
        '''))

      parser = BuildFileParser(root_dir=root_dir,
                               exposed_objects={},
                               path_relative_utils={},
                               target_alias_map={'fake': FakeTarget})

      parser.populate_target_proxy_transitive_closure_for_spec(':foo')
      self.assertEqual(len(parser._target_proxy_by_address), 3)

  def test_sibling_build_files(self):
    with self.workspace('./BUILD', './BUILD.foo', './BUILD.bar') as root_dir:
      with open(os.path.join(root_dir, './BUILD'), 'w') as build:
        build.write(dedent('''
          fake(name="base",
               dependencies=[
                 ':foo',
               ])
        '''))

      with open(os.path.join(root_dir, './BUILD.foo'), 'w') as build:
        build.write(dedent('''
          fake(name="foo",
               dependencies=[
                 ':bat',
               ])
        '''))

      with open(os.path.join(root_dir, './BUILD.bar'), 'w') as build:
        build.write(dedent('''
          fake(name="bat")
        '''))

      parser = BuildFileParser(root_dir=root_dir,
                               exposed_objects={},
                               path_relative_utils={},
                               target_alias_map={'fake': FakeTarget})

      bar_build_file = BuildFile(root_dir, 'BUILD.bar')
      base_build_file = BuildFile(root_dir, 'BUILD')
      foo_build_file = BuildFile(root_dir, 'BUILD.foo')
      parser.parse_build_file_family(bar_build_file)
      addresses = parser._target_proxy_by_address.keys()
      self.assertEqual(set([bar_build_file, base_build_file, foo_build_file]),
                       set([address.build_file for address in addresses]))
      self.assertEqual(set([':base', ':foo', ':bat']),
                       set([address.spec for address in addresses]))

    # This workspace is malformed, you can't shadow a name in a sibling BUILD file
    with self.workspace('./BUILD', './BUILD.foo', './BUILD.bar') as root_dir:
      with open(os.path.join(root_dir, './BUILD'), 'w') as build:
        build.write(dedent('''
          fake(name="base",
               dependencies=[
                 ':foo',
               ])
        '''))

      with open(os.path.join(root_dir, './BUILD.foo'), 'w') as build:
        build.write(dedent('''
          fake(name="foo",
               dependencies=[
                 ':bat',
               ])
        '''))

      with open(os.path.join(root_dir, './BUILD.bar'), 'w') as build:
        build.write(dedent('''
          fake(name="base")
        '''))

      parser = BuildFileParser(root_dir=root_dir,
                               exposed_objects={},
                               path_relative_utils={},
                               target_alias_map={'fake': FakeTarget})
      with pytest.raises(AssertionError):
        parser.populate_target_proxy_transitive_closure_for_spec(':base')
