# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import pytest

from pants.backend.core.targets.resources import Resources
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TargetDefinitionException
from pants_test.base_test import BaseTest


class JvmTargetTest(BaseTest):

  def test_traversable_dependency_specs(self):
    self.make_target(':resource_target', Resources)
    target = self.make_target(':foo', JvmTarget, resources=[':resource_target'])
    self.assertSequenceEqual([], list(target.traversable_specs))
    self.assertSequenceEqual([':resource_target'], list(target.traversable_dependency_specs))
