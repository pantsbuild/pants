# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import os
from collections import defaultdict
from textwrap import dedent

from pants.backend.core.targets.resources import Resources
from pants.backend.core.tasks.prepare_resources import PrepareResources
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.build_file_aliases import BuildFileAliases
from pants.goal.products import MultipleRootedProducts, Products, UnionProducts
from pants.util.contextutil import open_zip
from pants.util.dirutil import relativize_path
from pants_test.tasks.task_test_base import TaskTestBase


class PrepareResourcesTest(TaskTestBase):
  @property
  def alias_groups(self):
    return BuildFileAliases.create(
      targets={
        'java_library': JavaLibrary,
        'resources': Resources,
      }
    )

  @classmethod
  def task_type(cls):
    return PrepareResources

  def setUp(self):
    super(PrepareResourcesTest, self).setUp()

  def tearDown(self):
    super(PrepareResourcesTest, self).tearDown()

  def _create_prep_task(self, use_jar=True, short_path=True, targets=[]):
    context = self.context(
      options={
        self.options_scope: {
          'use_jar': use_jar,
          'short_path': short_path,
          }
      },
      target_roots=targets
    )
    if not context.products:
      context.products = Products()
    context.products.safe_create_data(
      'resources_by_target', lambda: defaultdict(MultipleRootedProducts))
    context.products.require_data('resources_by_target')
    context.products.safe_create_data('compile_classpath', lambda: UnionProducts())
    context.products.require_data('compile_classpath', )
    return self.create_task(context)

  def _verify_prepared_resources_structure(self, res_task, res_target, expected_rel_res_files):
    resources_files_on_disk = list()
    resources_by_target = res_task.context.products.get_data('resources_by_target')
    for _, abs_paths in resources_by_target[res_target].abs_paths():
      resources_files_on_disk += abs_paths

    # make sure no duplicates.
    self.assertEquals(len(resources_files_on_disk), len(set(resources_files_on_disk)))

    # make sure all of the files are rooted in the prepare_resources workdir.
    rel_workdir = relativize_path(res_task.workdir, self.build_root)
    self.assertEquals(
      len(resources_files_on_disk),
      len(filter(lambda rf: rf.startswith(rel_workdir), resources_files_on_disk)))

    # strip the leading relative workdir + '/' so leaving only res_target/res_file
    actual_rel_res_files = set([f[len(rel_workdir) + 1:] for f in resources_files_on_disk])
    # last make sure files are expected ones.
    self.assertEquals(expected_rel_res_files, actual_rel_res_files)

  def _test_jarring_resources_helper(self, use_long_name, short_path):
    # In PrepareSources, we use SHA1 (which is 40 hex char long) to replace target name
    # if --short-path option is specified. So if 'use_long_name' is true, let's
    # make the target name really long (100) to test the SHA1 replacement logic.
    resource_target_name = 'r' * 100 if use_long_name else 'short'
    resource_target_spec = 'res:{}'.format(resource_target_name)
    resources_target = self.create_resources(
      'res', resource_target_name, 'a.txt', 'b.txt', 'c.txt')
    java_target = self.create_library(
      'java', 'java_library', 'java', resources=resource_target_spec)

    # Create the task to do jarring and use short jar name.
    task = self._create_prep_task(
      use_jar=True,
      short_path=short_path,
      targets=[resources_target, java_target])

    task.execute()

    if short_path and use_long_name:
      sha = hashlib.sha1()
      sha.update(resources_target.id)
      resource_jar_name = sha.hexdigest() + '.jar'
    else:
      resource_jar_name = resources_target.id + '.jar'

    self._verify_prepared_resources_structure(
      task, resources_target,
      {
        resource_jar_name + '/a.txt',
        resource_jar_name + '/b.txt',
        resource_jar_name + '/c.txt'
      }
    )

    # finally make sure all prepared resource files in the jar have the expected content.
    with open_zip(os.path.join(task.workdir, resource_jar_name)) as jar:
      self.assertEquals({'a.txt', 'b.txt', 'c.txt'}, set(jar.namelist()))
      self.assertEquals('a.txt', jar.read('a.txt'))
      self.assertEquals('b.txt', jar.read('b.txt'))
      self.assertEquals('c.txt', jar.read('c.txt'))

  def test_jarring_resources_with_short_target_name(self):
    self._test_jarring_resources_helper(use_long_name=False, short_path=True)

  def test_jarring_resources_with_long_target_name(self):
    self._test_jarring_resources_helper(use_long_name=True, short_path=True)

  def test_dir_copying_resources(self):
    resources_target = self.create_resources('res', 'some_res', 'a.txt', 'b.txt', 'c.txt')
    java_target = self.create_library('java', 'java_library', 'java', resources='res:some_res')

    task = self._create_prep_task(
      use_jar=False,
      short_path=False,
      targets=[resources_target, java_target])

    task.execute()

    self._verify_prepared_resources_structure(
      task, resources_target,
      {'res.some_res/a.txt', 'res.some_res/b.txt', 'res.some_res/c.txt'})

    # finally make sure all prepared resource files have the expected content.
    self.assert_file_content(os.path.join(task.workdir, 'res.some_res/a.txt'), 'a.txt')
    self.assert_file_content(os.path.join(task.workdir, 'res.some_res/b.txt'), 'b.txt')
    self.assert_file_content(os.path.join(task.workdir, 'res.some_res/c.txt'), 'c.txt')

  def test_dir_copying_with_global_use_jar_on_but_resources_use_jar_off(self):
    # Manually create a Resources target with use_jar turned off.
    self.create_files('res', ['a.txt', 'b.txt', 'c.txt'])
    self.add_to_build_file('res', dedent('''
        resources(name='some_res',
          sources=['a.txt', 'b.txt', 'c.txt'],
          use_jar=False,
        )'''))
    resources_target = self.target('res:some_res')
    java_target = self.create_library('java', 'java_library', 'java', resources='res:some_res')

    # Create a PrepareResources task with global usr_jar option turned on.
    task = self._create_prep_task(
      use_jar=True,
      short_path=True,
      targets=[resources_target, java_target])

    task.execute()

    self._verify_prepared_resources_structure(
      task, resources_target,
      {'res.some_res/a.txt', 'res.some_res/b.txt', 'res.some_res/c.txt'})

    # finally make sure all prepared resource files have the expected content.
    self.assert_file_content(os.path.join(task.workdir, 'res.some_res/a.txt'), 'a.txt')
    self.assert_file_content(os.path.join(task.workdir, 'res.some_res/b.txt'), 'b.txt')
    self.assert_file_content(os.path.join(task.workdir, 'res.some_res/c.txt'), 'c.txt')
