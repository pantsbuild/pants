# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from textwrap import dedent

from pants.backend.jvm.tasks.ivy_imports import IvyImports
from pants.base.address import BuildFileAddress
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase

class IvyImportsTest(NailgunTaskTestBase):
  """Tests for the IvyImports task"""

  @classmethod
  def task_type(cls):
    return IvyImports

  def _create_ivyimports_task(self, context=None, config=None, options=None):
    context = context or self._create_context(config, options)
    return self.create_task(context, self.build_root)

  def test_ivy_imports(self):
    # I chose these two imports randomly, feel free to change them if they pose an issue.
    links = [
      '.pants.d/ivy/mapped-imports/a.foo/com.google.guava/guava/default/com.google.guava-guava-12.0.jar',
      '.pants.d/ivy/mapped-imports/a.foo/junit/junit/default/junit-junit-4.11.jar'
    ]
    for link in links:
      if os.path.exists(link):
        os.remove(link)
        self.assertFalse(os.path.exists(link))
    context = self.context()
    build_file = self.add_to_build_file('a/BUILD', dedent('''
      java_protobuf_library(
        name='foo',
        imports=[
          ':bar',
          ':baz',
        ],
      )
      jar_library(
        name='bar',
        jars=[
          jar(org='junit', name='junit-dep', rev='4.11'),
        ],
      )
      jar_library(
        name='baz',
        jars=[
          jar(org='com.google.guava', name='guava', rev='12.0'),
        ],
      )
    '''))
    target_address = BuildFileAddress(build_file, 'foo')
    context.build_graph.inject_address_closure(target_address)
    protobuf_library_target = context.build_graph.get_target(target_address)
    context.replace_targets([protobuf_library_target])

    self.execute(context)
    for link in links:
      self.assertTrue(os.path.exists(link), msg='Could not find {0}'.format(link))
      self.assertTrue(os.path.islink(link), msg='Not a link {0}'.format(link))
      self.assertTrue(os.path.lexists(link), msg='Not linked to a real file {0}'.format(link))


