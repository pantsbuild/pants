# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import pytest

from pants.backend.core.wrapped_globs import Globs
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.address import BuildFileAddress, SyntheticAddress
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.exceptions import TargetDefinitionException
from pants_test.base_test import BaseTest


class TargetTest(BaseTest):
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

  def test_derived_from_chain(self):
    context = self.context()

    # add concrete target
    build_file = self.add_to_build_file('y/BUILD',
                                        'java_library(name="concrete", sources=["SourceA.scala"])')
    concrete_address = BuildFileAddress(build_file, 'concrete')
    context.build_graph.inject_address_closure(concrete_address)
    concrete = context.build_graph.get_target(concrete_address)

    # add synthetic targets
    syn_one = context.add_new_target(SyntheticAddress('y', 'syn_one'),
                                     JavaLibrary,
                                     derived_from=concrete,
                                     sources=["SourceB.scala"])
    syn_two = context.add_new_target(SyntheticAddress('y', 'syn_two'),
                                     JavaLibrary,
                                     derived_from=syn_one,
                                     sources=["SourceC.scala"])

    # validate
    self.assertEquals(list(syn_two.derived_from_chain), [syn_one, concrete])
    self.assertEquals(list(syn_one.derived_from_chain), [concrete])
    self.assertEquals(list(concrete.derived_from_chain), [])
