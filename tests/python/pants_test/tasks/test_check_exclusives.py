# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import shutil
import tempfile

from pants.backend.core.tasks.check_exclusives import CheckExclusives
from pants.base.exceptions import TaskError

from pants_test.base_test import BaseTest


class CheckExclusivesTest(BaseTest):
  """Test of the CheckExclusives task."""

  def setUp(self):
    super(CheckExclusivesTest, self).setUp()
    self.workdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.workdir, ignore_errors=True)
    super(CheckExclusivesTest, self).tearDown()

  def test_check_exclusives(self):
    a = self.make_target(':a', exclusives={'a': '1', 'b': '1'})
    b = self.make_target(':b', exclusives={'a': '1'})
    c = self.make_target(':c', exclusives={'a': '2'})
    d = self.make_target(':d', dependencies=[a, b])
    e = self.make_target(':e', dependencies=[a, c], exclusives={'c': '1'})

    context = self.context(target_roots=[d, e])
    check_exclusives_task = CheckExclusives(context, self.workdir, signal_error=True)
    try:
      check_exclusives_task.execute()
      self.fail("Expected a conflicting exclusives exception to be thrown.")
    except TaskError:
      pass

  def test_classpath_compatibility(self):
    # test the compatibility checks for different exclusive groups.
    a = self.make_target(':a', exclusives={'a': '1', 'b': '1'})
    b = self.make_target(':b', exclusives={'a': '1', 'b': '<none>'})
    c = self.make_target(':c', exclusives={'a': '2', 'b': '2'})
    d = self.make_target(':d')

    context = self.context(target_roots=[a, b, c, d])
    context.products.require_data('exclusives_groups')
    check_exclusives_task = CheckExclusives(context, self.workdir, signal_error=True)
    check_exclusives_task.execute()
    egroups = context.products.get_data('exclusives_groups')
    # Expected compatibility:
    # a is compatible with nothing but itself.
    self.assertTrue(egroups._is_compatible(egroups.target_to_key[a], egroups.target_to_key[a]))
    self.assertFalse(egroups._is_compatible(egroups.target_to_key[a], egroups.target_to_key[b]))
    self.assertFalse(egroups._is_compatible(egroups.target_to_key[a], egroups.target_to_key[d]))
    self.assertFalse(egroups._is_compatible(egroups.target_to_key[a], egroups.target_to_key[c]))

    # b is compatible with itself and a.
    self.assertTrue(egroups._is_compatible(egroups.target_to_key[b], egroups.target_to_key[a]))
    self.assertTrue(egroups._is_compatible(egroups.target_to_key[b], egroups.target_to_key[b]))
    self.assertFalse(egroups._is_compatible(egroups.target_to_key[b], egroups.target_to_key[c]))
    self.assertFalse(egroups._is_compatible(egroups.target_to_key[b], egroups.target_to_key[d]))

    # c is compatible with nothing but itself
    self.assertTrue(egroups._is_compatible(egroups.target_to_key[c], egroups.target_to_key[c]))
    self.assertFalse(egroups._is_compatible(egroups.target_to_key[c], egroups.target_to_key[a]))
    self.assertFalse(egroups._is_compatible(egroups.target_to_key[c], egroups.target_to_key[b]))
    self.assertFalse(egroups._is_compatible(egroups.target_to_key[c], egroups.target_to_key[d]))

    # d is compatible with everything.
    self.assertTrue(egroups._is_compatible(egroups.target_to_key[d], egroups.target_to_key[a]))
    self.assertTrue(egroups._is_compatible(egroups.target_to_key[d], egroups.target_to_key[b]))
    self.assertTrue(egroups._is_compatible(egroups.target_to_key[d], egroups.target_to_key[c]))
    self.assertTrue(egroups._is_compatible(egroups.target_to_key[d], egroups.target_to_key[d]))

  def test_classpath_updates(self):
    # Check that exclusive groups classpaths accumulate properly.
    a = self.make_target(':a', exclusives={'a': '1', 'b': '1'})
    b = self.make_target(':b', exclusives={'a': '1', 'b': '<none>'})
    c = self.make_target(':c', exclusives={'a': '2', 'b': '2'})
    d = self.make_target(':d')

    context = self.context(target_roots=[a, b, c, d])
    context.products.require_data('exclusives_groups')
    check_exclusives_task = CheckExclusives(context, self.workdir, signal_error=True)
    check_exclusives_task.execute()
    egroups = context.products.get_data('exclusives_groups')

    egroups.set_base_classpath_for_group("a=1,b=1", ["a1", "b1"])
    egroups.set_base_classpath_for_group("a=1,b=<none>", ["a1"])
    egroups.set_base_classpath_for_group("a=2,b=2", ["a2", "b2"])
    egroups.set_base_classpath_for_group("a=<none>,b=<none>", ["none"])
    egroups.update_compatible_classpaths(None, ["update_without_group"])
    egroups.update_compatible_classpaths("a=<none>,b=<none>", ["update_all"])
    egroups.update_compatible_classpaths("a=1,b=<none>", ["update_a1bn"])
    egroups.update_compatible_classpaths("a=2,b=2", ["update_only_a2b2"])
    self.assertEquals(egroups.get_classpath_for_group("a=2,b=2"),
                      ["update_only_a2b2", "update_all", "update_without_group", "a2", "b2"])
    self.assertEquals(egroups.get_classpath_for_group("a=1,b=1"),
                      ["update_a1bn", "update_all", "update_without_group", "a1", "b1"])
    self.assertEquals(egroups.get_classpath_for_group("a=1,b=<none>"),
                      ["update_a1bn", "update_all", "update_without_group", "a1"])
    self.assertEquals(egroups.get_classpath_for_group("a=<none>,b=<none>"),
                      ["update_all", "update_without_group", "none"])

    # make sure repeated additions of the same thing are idempotent.
    egroups.update_compatible_classpaths("a=1,b=1", ["a1", "b1", "xxx"])
    self.assertEquals(egroups.get_classpath_for_group("a=1,b=1"),
                      ["xxx", "update_a1bn", "update_all", "update_without_group", "a1", "b1"])
