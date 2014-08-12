# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from textwrap import dedent
import unittest2

from pants.backend.core.targets.dependencies import Dependencies
from pants.base.build_file_address_mapper import AddressLookupError
from pants.base.addressable import Addressable

from pants_test.base_test import BaseTest


class BuildFileAddressMapperTest(BaseTest):
  def setUp(self):
    super(BuildFileAddressMapperTest, self).setUp()

  def test_target_addressable(self):
    build_file = self.add_to_build_file('BUILD', dedent(
      '''
      dependencies(
        name = 'foozle'
      )

      dependencies(
        name = 'baz',
      )
      '''
    ))

    with self.assertRaises(AddressLookupError):
      self.address_mapper.resolve_spec('//:bad_spec')

    dependencies_addressable = self.address_mapper.resolve_spec('//:foozle')
    self.assertEqual(dependencies_addressable.target_type, Dependencies)

