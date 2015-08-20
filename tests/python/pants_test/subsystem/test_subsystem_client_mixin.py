# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from mock import MagicMock, call

from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.optionable import Optionable
from pants.subsystem.subsystem import Subsystem
from pants.subsystem.subsystem_client_mixin import SubsystemClientMixin, SubsystemDependency


class MockOptions(object):
  def __init__(self):
    self.scope_to_registration_func = {}

  def registration_function_for_optionable(self, optionable, scope):
    ret = MagicMock()
    self.scope_to_registration_func[scope] = ret
    return ret

  def reg_func_mock(self, scope):
    return self.scope_to_registration_func[scope]


class DummySubsystem1(Subsystem):
  options_scope = 'subsys1'

  @classmethod
  def subsystem_dependencies(cls):
    return (DummySubsystem2,)

  @classmethod
  def register_options(cls, register):
    register('subsys1.opt1')


class DummySubsystem2(Subsystem):
  options_scope = 'subsys2'

  @classmethod
  def register_options(cls, register):
    register('subsys2.opt1')
    register('subsys2.opt2')


class DummyOptionable(SubsystemClientMixin, Optionable):
  options_scope = 'foo'

  @classmethod
  def subsystem_dependencies(cls):
    return (DummySubsystem1, DummySubsystem2.scoped(cls))

  @classmethod
  def register_options(cls, register):
    register('foo.opt1')


class SubsystemClientMixinTest(unittest.TestCase):
  def test_dependencies_iter(self):
    expected_deps = [SubsystemDependency(DummySubsystem1, GLOBAL_SCOPE),
                     SubsystemDependency(DummySubsystem2, 'foo')]
    self.assertEquals(expected_deps, list(DummyOptionable.subsystem_dependencies_iter()))

  def test_register_options_on_scope(self):
    mock_options = MockOptions()
    DummyOptionable.register_options_on_scope(mock_options)
    self.assertSetEqual({'subsys1', 'subsys2', 'foo', 'subsys2.foo'},
                        set(mock_options.scope_to_registration_func.keys()))
    self.assertEquals(mock_options.reg_func_mock('subsys1').mock_calls, [call('subsys1.opt1')])
    self.assertEquals(mock_options.reg_func_mock('subsys2').mock_calls,
                      [call('subsys2.opt1'), call('subsys2.opt2')])
    self.assertEquals(mock_options.reg_func_mock('foo').mock_calls, [call('foo.opt1')])
    # Verify that DummySubsystem2's options are registered twice - once for the global instance
    # and once for DummyOptionable's scoped instance.
    self.assertEquals(mock_options.reg_func_mock('subsys2.foo').mock_calls,
                      [call('subsys2.opt1'), call('subsys2.opt2')])
