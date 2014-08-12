# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.wrapped_globs import Globs
from pants.backend.jvm.targets.java_library import JavaLibrary
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
        },
      )

  def setUp(self):
    super(FilesetRelPathWrapperTest, self).setUp()

  def test_no_dir_glob(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("*"))')
    self.context().scan(self.build_root)

  def test_no_dir_glob_question(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("?"))')
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
    with self.assertRaises(ValueError):
      self.context().scan(self.build_root)

  def test_parent_dir_glob_question(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("../?.scala"))')
    with self.assertRaises(ValueError):
      self.context().scan(self.build_root)

  def test_parent_dir_bracket_glob_question(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("../[dir1, dir2]/?.scala"))')
    with self.assertRaises(ValueError):
      self.context().scan(self.build_root)

  def test_parent_dir_bracket(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("../[dir1, dir2]/File.scala"))')
    with self.assertRaises(ValueError):
      self.context().scan(self.build_root)

  def test_absolute_dir_glob(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("/root/*.scala"))')
    with self.assertRaises(ValueError):
      self.context().scan(self.build_root)

  def test_absolute_dir_glob_question(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("/root/?.scala"))')
    with self.assertRaises(ValueError):
      self.context().scan(self.build_root)
