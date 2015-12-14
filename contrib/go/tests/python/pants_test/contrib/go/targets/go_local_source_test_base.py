# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty
from textwrap import dedent

from pants.build_graph.address_lookup_error import AddressLookupError
from pants.util.meta import AbstractClass
from pants_test.base_test import BaseTest

from pants.contrib.go.register import build_file_aliases


class GoLocalSourceTestBase(AbstractClass):
  # NB: We assume we're mixed into a BaseTest - we can't extend that directly or else unittest tries
  # to run our test methods in the subclass (OK), and against us (not OK).
  # NB: We use aliases and BUILD files to test proper registration of anonymous targets and macros.

  @classmethod
  def setUpClass(cls):
    if not issubclass(cls, BaseTest):
      raise TypeError('Subclasses must mix in BaseTest')
    super(GoLocalSourceTestBase, cls).setUpClass()

  def setUp(self):
    super(GoLocalSourceTestBase, self).setUp()
    # Force setup of SourceRootConfig subsystem, as go targets do computation on source roots.
    self.context()

  @abstractproperty
  def target_type(self):
    """Subclasses should return a GoLocalSource target subclass."""

  @property
  def alias_groups(self):
    return build_file_aliases()

  def test_default_name_and_sources(self):
    self.create_file('src/go/src/foo/jake.go')
    self.create_file('src/go/src/foo/sub/jane.go')
    self.add_to_build_file('src/go/src/foo', dedent("""
        {target_alias}()
      """.format(target_alias=self.target_type.alias())))

    go_local_source_target = self.target('src/go/src/foo')
    self.assertIsNotNone(go_local_source_target)
    self.assertEqual('src/foo', go_local_source_target.import_path)
    self.assertEqual(['src/foo/jake.go'],
                     list(go_local_source_target.sources_relative_to_source_root()))

  def test_cannot_name(self):
    self.add_to_build_file('src/go/src/foo', dedent("""
        {target_alias}(name='bob')
      """.format(target_alias=self.target_type.alias())))

    with self.assertRaises(AddressLookupError):
      self.target('src/go/src/foo')

  def test_cannot_sources(self):
    self.create_file('src/go/src/foo/sub/jane.go')
    self.add_to_build_file('src/go/src/foo', dedent("""
        {target_alias}(sources=['sub/jane.go'])
      """.format(target_alias=self.target_type.alias())))

    with self.assertRaises(AddressLookupError):
      self.target('src/go/src/foo')

  def test_globs_cgo(self):
    # Any of these extensions are handled by `go build`:
    # .c, .s or .S, .cc, .cpp, or .cxx, .h, .hh, .hpp, or .hxx
    # We do not test .S since .s and .S are the same on OSX HFS+
    # case insensitive filesystems - which are common.

    # We shouldn't grab these - no BUILDs, no dirents, no subdir files.
    self.create_file('src/go/src/foo/BUILD')
    self.create_file('src/go/src/foo/subpackage/jane.go')
    self.create_file('src/go/src/foo/subpackage/jane.c')

    # We should grab all of these though.
    self.create_file('src/go/src/foo/jake.go')
    self.create_file('src/go/src/foo/jake.c')
    self.create_file('src/go/src/foo/jake.s')
    self.create_file('src/go/src/foo/jake.cc')
    self.create_file('src/go/src/foo/jake.cpp')
    self.create_file('src/go/src/foo/jake.cxx')
    self.create_file('src/go/src/foo/jake.h')
    self.create_file('src/go/src/foo/jake.hh')
    self.create_file('src/go/src/foo/jake.hpp')
    self.create_file('src/go/src/foo/jake.hxx')
    target = self.make_target(spec='src/go/src/foo', target_type=self.target_type)

    self.assertEqual(sorted(['src/foo/jake.go',
                             'src/foo/jake.c',
                             'src/foo/jake.s',
                             'src/foo/jake.cc',
                             'src/foo/jake.cpp',
                             'src/foo/jake.cxx',
                             'src/foo/jake.h',
                             'src/foo/jake.hh',
                             'src/foo/jake.hpp',
                             'src/foo/jake.hxx']),
                     sorted(target.sources_relative_to_source_root()))

  def test_globs_resources(self):
    # We shouldn't grab these - no BUILDs, no dirents, no subdir files.
    self.create_file('src/go/src/foo/BUILD')
    self.create_file('src/go/src/foo/subpackage/jane.go')
    self.create_file('src/go/src/foo/subpackage/jane.png')

    # We should grab all of these though.
    self.create_file('src/go/src/foo/jake.go')
    self.create_file('src/go/src/foo/jake.png')
    target = self.make_target(spec='src/go/src/foo', target_type=self.target_type)

    self.assertEqual(sorted(['src/foo/jake.go',
                             'src/foo/jake.png']),
                     sorted(target.sources_relative_to_source_root()))
