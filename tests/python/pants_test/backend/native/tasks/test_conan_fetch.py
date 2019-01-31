# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.backend.native.tasks.conan_fetch import ConanFetch
from pants.backend.native.tasks.conan_prep import ConanPrep
from pants_test.task_test_base import TaskTestBase


class ConanFetchTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return ConanFetch

  def test_rewrites_remotes_according_to_options(self):
    self.set_options(conan_remotes={'pants-conan': 'https://conan.bintray.com'})
    conan_prep_task_type = self.synthesize_task_subtype(ConanPrep, 'conan_prep_scope')
    context = self.context(for_task_types=[conan_prep_task_type])
    conan_prep = conan_prep_task_type(context, os.path.join(self.pants_workdir, 'conan_prep'))
    conan_fetch = self.create_task(context, os.path.join(self.pants_workdir, 'conan_fetch'))
    conan_prep.execute()
    conan_fetch.execute()
    conan_pex = context.products.get_data(ConanPrep.tool_instance_cls)
    user_home = conan_fetch._conan_user_home(conan_pex, in_workdir=True)

    (stdout, stderr, exit_code, _) = conan_pex.output(['remote', 'list'], env={
      'CONAN_USER_HOME': user_home,
    })
    self.assertEqual(0, exit_code)
    self.assertEqual(b'', stderr)
    self.assertEqual(stdout.decode('utf-8'),
                     'pants-conan: https://conan.bintray.com [Verify SSL: True]\n')
