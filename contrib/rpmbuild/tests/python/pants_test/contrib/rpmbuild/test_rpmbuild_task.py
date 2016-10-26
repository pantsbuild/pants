# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.rpmbuild.targets.rpm_package import RpmPackageTarget
from pants.contrib.rpmbuild.tasks.rpmbuild_task import RpmbuildTask


class RpmbuildTaskTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return RpmbuildTask

  @property
  def alias_groups(self):
    return super(RpmbuildTaskTest, self).alias_groups.merge(
      BuildFileAliases(targets={'rpm_package': RpmPackageTarget}))

  def test_extract_build_reqs(self):
    # Create a dummy RPM spec file.
    self.create_file(relpath='rpmbuild-test/testpkg.spec', contents=dedent('''
      Name: testpkg
      Version: 1.0.0
      BuildRequires: foo >= 0.9
      Buildrequires: bar
        buildrequires: xyzzy
      # BuildRequires: nada
    '''))

    context = self.context()
    task = self.create_task(context)
    actual_build_reqs = set(task.extract_build_reqs(os.path.join(self.build_root, 'rpmbuild-test/testpkg.spec')))
    self.assertEquals(set(['foo', 'bar', 'xyzzy']), actual_build_reqs)
