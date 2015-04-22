# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.wrapped_globs import Globs, RGlobs
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_file_aliases import BuildFileAliases
from pants_test.base_test import BaseTest


class FilesetRelPathWrapperTest(BaseTest):
  @property
  def alias_groups(self):
    return BuildFileAliases.create(
      targets={
        'java_library': JavaLibrary,
      },
      context_aware_object_factories={
        'globs': Globs,
        'rglobs': RGlobs,
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
    self.context().scan(self.build_root)

  def test_no_dir_glob_question(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("?"))')
    self.context().scan(self.build_root)

  def test_glob_to_spec(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("*.java"))')
    graph = self.context().scan(self.build_root)
    globs = graph.get_target_from_spec('y').globs_relative_to_buildroot()
    self.assertEquals({'globs': ['y/*.java']},
                      globs)

  def test_glob_to_spec_exclude(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("*.java", exclude=["fleem.java"]))')
    graph = self.context().scan(self.build_root)
    globs = graph.get_target_from_spec('y').globs_relative_to_buildroot()
    self.assertEquals({'globs': ['y/*.java'],
                       'exclude': [{'globs': ['y/fleem.java']}]},
                      globs)

  def test_glob_to_spec_list(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=["fleem.java", "morx.java"])')
    graph = self.context().scan(self.build_root)
    globs = graph.get_target_from_spec('y').globs_relative_to_buildroot()
    self.assertEquals({'globs': ['y/fleem.java', 'y/morx.java']},
                      globs)

  def test_glob_exclude(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("*.java", exclude=[["fleem.java"]]))')
    graph = self.context().scan(self.build_root)
    assert ['morx.java'] == list(graph.get_target_from_spec('y').sources_relative_to_source_root())

  def test_glob_exclude_not_string(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("*.java", exclude="fleem.java"))')
    with self.assertRaisesRegexp(AddressLookupError, 'Expected exclude parameter.*'):
      self.context().scan(self.build_root)

  def test_glob_exclude_string_in_list(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("*.java", exclude=["fleem.java"]))')
    self.context().scan(self.build_root)

  def test_subdir_glob(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("dir/*.scala"))')
    self.context().scan(self.build_root)

  def test_subdir_glob_question(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("dir/?.scala"))')
    self.context().scan(self.build_root)

  def test_subdir_bracket_glob(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("dir/[dir1, dir2]/*.scala"))')
    self.context().scan(self.build_root)

  def test_subdir_with_dir_glob(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("dir/**/*.scala"))')
    self.context().scan(self.build_root)

  # This is no longer allowed.
  def test_parent_dir_glob(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("../*.scala"))')
    with self.assertRaises(AddressLookupError):
      self.context().scan(self.build_root)

  def test_parent_dir_glob_question(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("../?.scala"))')
    with self.assertRaises(AddressLookupError):
      self.context().scan(self.build_root)

  def test_parent_dir_bracket_glob_question(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("../[dir1, dir2]/?.scala"))')
    with self.assertRaises(AddressLookupError):
      self.context().scan(self.build_root)

  def test_parent_dir_bracket(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("../[dir1, dir2]/File.scala"))')
    with self.assertRaises(AddressLookupError):
      self.context().scan(self.build_root)

  def test_absolute_dir_glob(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("/root/*.scala"))')
    with self.assertRaises(AddressLookupError):
      self.context().scan(self.build_root)

  def test_absolute_dir_glob_question(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("/root/?.scala"))')
    with self.assertRaises(AddressLookupError):
      self.context().scan(self.build_root)

  def test_rglob_follows_symlinked_dirs_by_default(self):
    self.add_to_build_file('z/w/BUILD', 'java_library(name="w", sources=rglobs("*.java"))')
    graph = self.context().scan(self.build_root)
    relative_sources = list(graph.get_target_from_spec('z/w').sources_relative_to_source_root())
    assert ['y/fleem.java', 'y/morx.java', 'foo.java'] == relative_sources

  def test_rglob_respects_follow_links_override(self):
    self.add_to_build_file('z/w/BUILD',
                           'java_library(name="w", sources=rglobs("*.java", follow_links=False))')
    graph = self.context().scan(self.build_root)
    assert ['foo.java'] == list(graph.get_target_from_spec('z/w').sources_relative_to_source_root())

  # Remove the following tests when operator support is dropped from globs
  def test_globs_add_globs_added_to_spec(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y",'
                                      '             sources=globs("morx.java") + globs("fleem.java"))')
    graph = self.context().scan(self.build_root)
    globs = graph.get_target_from_spec('y').globs_relative_to_buildroot()
    self.assertEquals({'globs': ['y/morx.java', 'y/fleem.java']},
                      globs)

  def test_globs_add_list_added_to_spec(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y",'
                                      '             sources=globs("morx.java") + ["fleem.java"])')
    graph = self.context().scan(self.build_root)
    globs = graph.get_target_from_spec('y').globs_relative_to_buildroot()
    self.assertEquals({'globs': ['y/morx.java', 'y/fleem.java']},
                      globs)

  def test_rglob_add_operator_with_other_rglob(self):
    self.add_to_build_file('y/BUILD',
                           'java_library(name="y",'
                           '             sources=rglobs("fleem.java") + rglobs("morx.java"))'
    )
    graph = self.context().scan(self.build_root)
    self.assertEqual(['fleem.java','morx.java'],
                     list(graph.get_target_from_spec('y').sources_relative_to_source_root()))

  def test_rglob_add_operator_with_list(self):
    self.add_to_build_file('y/BUILD',
                           'java_library(name="y",'
                           '             sources=rglobs("fleem.java") + ["morx.java"])'
    )
    graph = self.context().scan(self.build_root)
    self.assertEqual(['fleem.java', 'morx.java'],
                     list(graph.get_target_from_spec('y').sources_relative_to_source_root()))

  def test_rglob_add_operator_with_overlapping_rglob_has_distinct_list(self):
    self.add_to_build_file('y/BUILD',
                           'java_library(name="y",'
                           '             sources=rglobs("*.java") + rglobs("*.java"))')
    graph = self.context().scan(self.build_root)
    self.assertEqual(['fleem.java', 'morx.java'],
                     list(graph.get_target_from_spec('y').sources_relative_to_source_root()))

  def test_globs_sub_globs_added_to_spec_exclude(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y",'
                                      '             sources=globs("*.java") - globs("fleem.java"))')
    graph = self.context().scan(self.build_root)
    globs = graph.get_target_from_spec('y').globs_relative_to_buildroot()
    self.assertEquals({'globs': ['y/*.java'],
                       'exclude': [{'globs': ['y/fleem.java']}]},
                      globs)

  def test_glob_sub_list_added_to_spec_exclude(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y",'
                                      '             sources=globs("*.java") - ["fleem.java"])')
    graph = self.context().scan(self.build_root)
    globs = graph.get_target_from_spec('y').globs_relative_to_buildroot()
    self.assertEquals({'globs': ['y/*.java'],
                       'exclude': [{'globs': ['y/fleem.java']}]},
                      globs)

  def test_rglob_sub_operator_with_other_rglob(self):
    self.add_to_build_file('y/BUILD',
                           'java_library(name="y",'
                           '             sources=rglobs("*.java") - rglobs("morx.java"))')
    graph = self.context().scan(self.build_root)
    self.assertEqual(['fleem.java'],
                     list(graph.get_target_from_spec('y').sources_relative_to_source_root()))

  def test_rglob_sub_operator_with_list(self):
    self.add_to_build_file('y/BUILD',
                           'java_library(name="y",'
                           '             sources=rglobs("*.java") - ["morx.java"])')
    graph = self.context().scan(self.build_root)
    self.assertEqual(['fleem.java'],
                     list(graph.get_target_from_spec('y').sources_relative_to_source_root()))

  def test_rglob_sub_operator_with_non_overlapping_rglob(self):
    self.add_to_build_file('y/BUILD',
                           'java_library(name="y",'
                           '             sources=rglobs("*.java") - rglobs("*.scala"))')
    graph = self.context().scan(self.build_root)
    self.assertEqual(['fleem.java', 'morx.java'],
                     list(graph.get_target_from_spec('y').sources_relative_to_source_root()))
