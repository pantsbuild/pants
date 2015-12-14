# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.build_graph.address_lookup_error import AddressLookupError
from pants_test.base_test import BaseTest

from pants.contrib.go.register import build_file_aliases
from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary


class GoRemoteLibraryTest(BaseTest):
  # NB: We use  aliases and BUILD files to test proper registration of anonymous targets and macros.

  def setUp(self):
    super(GoRemoteLibraryTest, self).setUp()
    # Force setup of SourceRootConfig subsystem, as go targets do computation on source roots.
    self.context()

  @property
  def alias_groups(self):
    return build_file_aliases()

  def test_default_package(self):
    self.add_to_build_file('3rdparty/go/github.com/foo/bar', dedent("""
        go_remote_library()
      """))

    go_remote_library = self.target('3rdparty/go/github.com/foo/bar')
    self.assertIsNotNone(go_remote_library)
    self.assertEqual('github.com/foo/bar', go_remote_library.import_path)
    self.assertEqual('github.com/foo/bar', go_remote_library.remote_root)
    self.assertEqual('', go_remote_library.pkg)

  def test_sub_package(self):
    self.add_to_build_file('3rdparty/go/github.com/foo/bar', dedent("""
        go_remote_library(pkg='baz')
      """))

    go_remote_library = self.target('3rdparty/go/github.com/foo/bar:baz')
    self.assertIsNotNone(go_remote_library)
    self.assertEqual('github.com/foo/bar/baz', go_remote_library.import_path)
    self.assertEqual('github.com/foo/bar', go_remote_library.remote_root)
    self.assertEqual('baz', go_remote_library.pkg)

  def test_multiple_packages(self):
    self.add_to_build_file('3rdparty/go/github.com/foo/bar', dedent("""
        go_remote_libraries(
          rev='v42',
          packages=[
            '',
            'baz',
            'baz/bip',
            'bee/bop'
          ])
      """))

    default = self.target('3rdparty/go/github.com/foo/bar')
    self.assertIsInstance(default, GoRemoteLibrary)
    self.assertEqual('v42', default.rev)
    self.assertEqual('github.com/foo/bar', default.import_path)
    self.assertEqual('github.com/foo/bar', default.remote_root)
    self.assertEqual('', default.pkg)

    baz = self.target('3rdparty/go/github.com/foo/bar:baz')
    self.assertIsInstance(baz, GoRemoteLibrary)
    self.assertEqual('v42', baz.rev)
    self.assertEqual('github.com/foo/bar/baz', baz.import_path)
    self.assertEqual('github.com/foo/bar', baz.remote_root)
    self.assertEqual('baz', baz.pkg)

    baz_bip = self.target('3rdparty/go/github.com/foo/bar:baz/bip')
    self.assertIsInstance(baz_bip, GoRemoteLibrary)
    self.assertEqual('v42', baz_bip.rev)
    self.assertEqual('github.com/foo/bar/baz/bip', baz_bip.import_path)
    self.assertEqual('github.com/foo/bar', baz_bip.remote_root)
    self.assertEqual('baz/bip', baz_bip.pkg)

    bee_bop = self.target('3rdparty/go/github.com/foo/bar:bee/bop')
    self.assertIsInstance(bee_bop, GoRemoteLibrary)
    self.assertEqual('v42', bee_bop.rev)
    self.assertEqual('github.com/foo/bar/bee/bop', bee_bop.import_path)
    self.assertEqual('github.com/foo/bar', bee_bop.remote_root)
    self.assertEqual('bee/bop', bee_bop.pkg)

  def test_cannot_name(self):
    self.add_to_build_file('3rdparty/go/github.com/foo/bar', dedent("""
        go_remote_library(name='bob')
      """))

    with self.assertRaises(AddressLookupError):
      self.target('3rdparty/go/github.com/foo/bar')

  def test_cannot_sources(self):
    self.add_to_build_file('3rdparty/go/github.com/foo/bar', dedent("""
        go_remote_library(dependencies=[])
      """))

    with self.assertRaises(AddressLookupError):
      self.target('3rdparty/go/github.com/foo/bar')
