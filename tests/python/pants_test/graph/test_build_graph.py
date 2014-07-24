# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import os
from textwrap import dedent
import unittest

from pants.base.address import SyntheticAddress
from pants.base.build_configuration import BuildConfiguration
from pants.base.build_file_parser import BuildFileParser
from pants.base.build_graph import BuildGraph
from pants.base.build_root import BuildRoot
from pants.base.target import Target
from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import touch


class BuildGraphTest(unittest.TestCase):
  @contextmanager
  def workspace(self, *buildfiles):
    with temporary_dir() as root_dir:
      with BuildRoot().temporary(root_dir):
        with pushd(root_dir):
          for buildfile in buildfiles:
            touch(os.path.join(root_dir, buildfile))
          yield os.path.realpath(root_dir)

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

      build_configuration = BuildConfiguration()
      build_configuration.register_target_alias('fake', Target)
      parser = BuildFileParser(build_configuration, root_dir=root_dir)
      build_graph = BuildGraph()
      parser.inject_spec_closure_into_build_graph(':foo', build_graph)
      self.assertEqual(len(build_graph.dependencies_of(SyntheticAddress.parse(':foo'))), 1)
