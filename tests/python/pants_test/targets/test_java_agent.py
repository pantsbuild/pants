# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.java_agent import JavaAgent
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.base_test import BaseTest


class JavaAgentTest(BaseTest):
  @property
  def alias_groups(self):
    return BuildFileAliases(
      targets={
        'java_agent': JavaAgent,
      },
    )

  def create_agent(self, name, **kwargs):
    args = {'name': name}
    args.update(**kwargs)
    formatted_args = ', '.join('{name}={value!r}'.format(name=k, value=v) for k, v in args.items())
    target = 'java_agent({args})'.format(args=formatted_args)
    self.add_to_build_file('{path}'.format(path=name), target)
    return self.target('{path}:{name}'.format(path=name, name=name))

  def test_required(self):
    with self.assertRaises(TargetDefinitionException):
      self.create_agent('name', premain=None, agent_class=None)

  def test_minimal(self):
    self.assertEqual('jack', self.create_agent('one', premain='jack').premain)
    self.assertEqual('jill', self.create_agent('two', agent_class='jill').agent_class)

  def test_defaults(self):
    def assert_bool_defaults(tgt):
      self.assertFalse(tgt.can_redefine)
      self.assertFalse(tgt.can_retransform)
      self.assertFalse(tgt.can_set_native_method_prefix)

    agent = self.create_agent('one', premain='jack')
    self.assertEqual('jack', agent.premain)
    self.assertIsNone(agent.agent_class)
    assert_bool_defaults(agent)

    agent = self.create_agent('two', agent_class='jill')
    self.assertEqual('jill', agent.agent_class)
    self.assertIsNone(agent.premain)
    assert_bool_defaults(agent)

  def test_can_redefine(self):
    agent = self.create_agent('one', premain='jack', can_redefine=True)
    self.assertTrue(agent.can_redefine)
    self.assertFalse(agent.can_retransform)
    self.assertFalse(agent.can_set_native_method_prefix)

    agent = self.create_agent('two', premain='jack', can_redefine=False)
    self.assertFalse(agent.can_redefine)
    self.assertFalse(agent.can_retransform)
    self.assertFalse(agent.can_set_native_method_prefix)

  def test_can_retransform(self):
    agent = self.create_agent('one', premain='jack', can_retransform=True)
    self.assertTrue(agent.can_retransform)
    self.assertFalse(agent.can_redefine)
    self.assertFalse(agent.can_set_native_method_prefix)

    agent = self.create_agent('two', premain='jack', can_retransform=False)
    self.assertFalse(agent.can_retransform)
    self.assertFalse(agent.can_redefine)
    self.assertFalse(agent.can_set_native_method_prefix)

  def test_can_set_native_method_prefix(self):
    agent = self.create_agent('one', premain='jack', can_set_native_method_prefix=True)
    self.assertTrue(agent.can_set_native_method_prefix)
    self.assertFalse(agent.can_redefine)
    self.assertFalse(agent.can_retransform)

    agent = self.create_agent('two', premain='jack', can_set_native_method_prefix=False)
    self.assertFalse(agent.can_set_native_method_prefix)
    self.assertFalse(agent.can_redefine)
    self.assertFalse(agent.can_retransform)
