# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.core.register import build_file_aliases as register_core
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.address import BuildFileAddress, SyntheticAddress
from pants.base.build_file_aliases import BuildFileAliases
from pants_test.base_test import BaseTest


class JvmTargetTest(BaseTest):

  @property
  def alias_groups(self):
    return register_core().merge(BuildFileAliases.create(
      targets={
        # We don't usually have an alias for 'jvm_target' in BUILD files. It's being added here
        # to make it easier to write a test.
        'jvm_target': JvmTarget,
        }))

  def test_traversable_dependency_specs(self):
    build_file = self.add_to_build_file('BUILD', dedent('''
    jvm_target(name='foo',
      resources=[':resource_target'],
    )
    resources(name='resource_target',
      sources=['foo.txt'],
    )
    '''))

    self.build_graph.inject_address_closure(BuildFileAddress(build_file, 'foo'))
    target = self.build_graph.get_target(SyntheticAddress.parse('//:foo'))
    self.assertSequenceEqual([], list(target.traversable_specs))
    self.assertSequenceEqual([':resource_target'], list(target.traversable_dependency_specs))
