# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.backend.core.wrapped_globs import Globs, RGlobs
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.base_test import BaseTest


class FilesetRelPathWrapperTest(BaseTest):

  @property
  def alias_groups(self):
    return BuildFileAliases(
      targets={
        'java_library': JavaLibrary,
      },
      context_aware_object_factories={
        'globs': Globs.factory,
        'rglobs': RGlobs.factory,
      },
    )

  def setUp(self):
    super(FilesetRelPathWrapperTest, self).setUp()
    self.create_file('y/morx.java')
    self.create_file('y/fleem.java')
    self.create_file('z/w/foo.java')
    os.symlink('../../y', os.path.join(self.build_root, 'z/w/y'))

  def test_no_dir_glob(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("*"))')
    self.context().scan()

  def test_no_dir_glob_question(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("?"))')
    self.context().scan()

  def _spec_test(self, spec, expected):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources={})'.format(spec))
    graph = self.context().scan()
    globs = graph.get_target_from_spec('y').globs_relative_to_buildroot()
    self.assertEquals(expected, globs)

  def test_glob_to_spec(self):
    self._spec_test('globs("*.java")',
                    {'globs': ['y/*.java']})

  def test_glob_to_spec_exclude(self):
    self._spec_test('globs("*.java", exclude=["fleem.java"])',
                    {'globs': ['y/*.java'],
                     'exclude': [{'globs': ['y/fleem.java']}]})

  def test_glob_to_spec_list(self):
    self._spec_test('["fleem.java", "morx.java"]',
                    {'globs': ['y/fleem.java', 'y/morx.java']})

  def test_rglob_to_spec_one(self):
    self._spec_test('rglobs("fleem.java")',
                    {'globs': ['y/fleem.java']})

  def test_rglob_to_spec_simple(self):
    self._spec_test('rglobs("*.java")',
                    {'globs': ['y/**/*.java', 'y/*.java']})

  def test_rglob_to_spec_multi(self):
    self._spec_test('rglobs("a/**/b/*.java")',
                    {'globs': ['y/a/**/b/**/*.java',
                               'y/a/**/b/*.java',
                               'y/a/b/**/*.java',
                               'y/a/b/*.java']})

  def test_rglob_to_spec_multi_more(self):
    self._spec_test('rglobs("a/**/b/**/c/*.java")',
                    {'globs': ['y/a/**/b/**/c/**/*.java',
                               'y/a/**/b/**/c/*.java',
                               'y/a/**/b/c/**/*.java',
                               'y/a/**/b/c/*.java',

                               'y/a/b/**/c/**/*.java',
                               'y/a/b/**/c/*.java',
                               'y/a/b/c/**/*.java',
                               'y/a/b/c/*.java']})

  def test_rglob_to_spec_mid(self):
    self._spec_test('rglobs("a/**/b/Fleem.java")',
                    {'globs': ['y/a/**/b/Fleem.java',
                               'y/a/b/Fleem.java']})

  def test_rglob_to_spec_explicit(self):
    self._spec_test('rglobs("a/**/*.java")',
                    {'globs': ['y/a/**/*.java',
                               'y/a/*.java']})

  def test_glob_exclude(self):
    self.add_to_build_file('y/BUILD', dedent("""
      java_library(name="y", sources=globs("*.java", exclude=[["fleem.java"]]))
      """))
    graph = self.context().scan()
    assert ['morx.java'] == list(graph.get_target_from_spec('y').sources_relative_to_source_root())

  def test_glob_exclude_not_string(self):
    self.add_to_build_file('y/BUILD', dedent("""
      java_library(name="y", sources=globs("*.java", exclude="fleem.java"))
      """))
    with self.assertRaisesRegexp(AddressLookupError, 'Expected exclude parameter.*'):
      self.context().scan()

  def test_glob_exclude_string_in_list(self):
    self.add_to_build_file('y/BUILD', dedent("""
      java_library(name="y", sources=globs("*.java", exclude=["fleem.java"]))
      """))
    self.context().scan()

  def test_glob_exclude_doesnt_modify_exclude_array(self):
    self.add_to_build_file('y/BUILD', dedent("""
      list_of_files = ["fleem.java"]
      java_library(name="y", sources=globs("*.java", exclude=list_of_files))
      java_library(name="z", sources=list_of_files)
      """))

    graph = self.context().scan()

    self.assertEqual(['fleem.java'],
                     list(graph.get_target_from_spec('y:z').sources_relative_to_source_root()))

  def test_glob_invalid_keyword(self):
    self.add_to_build_file('y/BUILD', dedent("""
      java_library(name="y", sources=globs("*.java", invalid_keyword=["fleem.java"]))
      """))
    with self.assertRaises(AddressLookupError):
      self.context().scan()

  def test_glob_invalid_keyword_along_with_valid_ones(self):
    self.add_to_build_file('y/BUILD', dedent("""
      java_library(
        name="y",
        sources=globs("*.java", follow_links=True, invalid_keyword=["fleem.java"])
      )
      """))
    with self.assertRaises(AddressLookupError):
      self.context().scan()

  def test_subdir_glob(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("dir/*.scala"))')
    self.context().scan()

  def test_subdir_glob_question(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("dir/?.scala"))')
    self.context().scan()

  def test_subdir_bracket_glob(self):
    self.add_to_build_file('y/BUILD', dedent("""
      java_library(name="y", sources=globs("dir/[dir1, dir2]/*.scala"))
      """))
    self.context().scan()

  def test_subdir_with_dir_glob(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("dir/**/*.scala"))')
    self.context().scan()

  # This is no longer allowed.
  def test_parent_dir_glob(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("../*.scala"))')
    with self.assertRaises(AddressLookupError):
      self.context().scan()

  def test_parent_dir_glob_question(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("../?.scala"))')
    with self.assertRaises(AddressLookupError):
      self.context().scan()

  def test_parent_dir_bracket_glob_question(self):
    self.add_to_build_file('y/BUILD', dedent("""
      java_library(name="y", sources=globs("../[dir1, dir2]/?.scala"))
      """))
    with self.assertRaises(AddressLookupError):
      self.context().scan()

  def test_parent_dir_bracket(self):
    self.add_to_build_file('y/BUILD', dedent("""
      java_library(name="y", sources=globs("../[dir1, dir2]/File.scala"))
      """))
    with self.assertRaises(AddressLookupError):
      self.context().scan()

  def test_absolute_dir_glob(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("/root/*.scala"))')
    with self.assertRaises(AddressLookupError):
      self.context().scan()

  def test_absolute_dir_glob_question(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("/root/?.scala"))')
    with self.assertRaises(AddressLookupError):
      self.context().scan()

  def test_rglob_follows_symlinked_dirs_by_default(self):
    self.add_to_build_file('z/w/BUILD', 'java_library(name="w", sources=rglobs("*.java"))')
    graph = self.context().scan()
    relative_sources = list(graph.get_target_from_spec('z/w').sources_relative_to_source_root())
    assert ['y/fleem.java', 'y/morx.java', 'foo.java'] == relative_sources

  def test_rglob_respects_follow_links_override(self):
    self.add_to_build_file('z/w/BUILD',
                           'java_library(name="w", sources=rglobs("*.java", follow_links=False))')
    graph = self.context().scan()
    assert ['foo.java'] == list(graph.get_target_from_spec('z/w').sources_relative_to_source_root())
