# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from textwrap import dedent

import mock
from pants.base.exceptions import TaskError
from pants_test.task_test_base import TaskTestBase

from pants.contrib.node.subsystems.resolvers.node_preinstalled_module_resolver import \
  NodePreinstalledModuleResolver
from pants.contrib.node.subsystems.resolvers.npm_resolver import NpmResolver
from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.targets.node_preinstalled_module import NodePreinstalledModule
from pants.contrib.node.tasks.node_paths import NodePathsLocal
from pants.contrib.node.tasks.node_resolve import NodeResolveLocal


class NodeResolveLocalTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return NodeResolveLocal

  def setUp(self):
    super(NodeResolveLocalTest, self).setUp()
    NodeResolveLocal.register_resolver_for_type(NodePreinstalledModule, NodePreinstalledModuleResolver)
    NodeResolveLocal.register_resolver_for_type(NodeModule, NpmResolver)

  def tearDown(self):
    super(NodeResolveLocalTest, self).tearDown()
    NodeResolveLocal._clear_resolvers()

  def test_register_resolver_for_type(self):
    NodeResolveLocal._clear_resolvers()

    self.assertIsNone(NodeResolveLocal._resolver_for_target(NodePreinstalledModule))
    self.assertIsNone(NodeResolveLocal._resolver_for_target(NodeModule))

    node_preinstalled__module_target = self.make_target(
      spec=':empty_fake_node_preinstalled_module_target',
      target_type=NodePreinstalledModule)
    NodeResolveLocal.register_resolver_for_type(NodePreinstalledModule, NodePreinstalledModuleResolver)
    self.assertEqual(NodePreinstalledModuleResolver,
                     NodeResolveLocal._resolver_for_target(node_preinstalled__module_target))

    node_module_target = self.make_target(spec=':empty_fake_node_module_target',
                                          target_type=NodeModule)
    NodeResolveLocal.register_resolver_for_type(NodeModule, NpmResolver)
    self.assertEqual(NpmResolver,
                     NodeResolveLocal._resolver_for_target(node_module_target))

  def test_product_types(self):
    self.assertEqual([NodePathsLocal], NodeResolveLocal.product_types())

  def _test_resolve_options_helper(
      self, install_optional, force_option_override, production_only, force, frozen_lockfile,
      package_manager, has_lock_file, expected_params):
    self.create_file('src/node/util/package.json', contents=dedent("""
      {
        "name": "util",
        "version": "0.0.1"
      }
    """))
    self.create_file('src/node/util/util.js', contents=dedent("""
      var typ = require('typ');
      console.log("type of boolean is: " + typ.BOOLEAN);
    """))
    # yarn execution path requires yarn.lock

    sources = ['util.js', 'package.json']
    if has_lock_file:
      self.create_file('src/node/util/yarn.lock')
      sources.append('yarn.lock')
    target = self.make_target(spec='src/node/util',
                              target_type=NodeModule,
                              sources=sources,
                              dependencies=[],
                              package_manager=package_manager)

    context = self.context(target_roots=[target], options={
      'npm-resolver': {'install_optional': install_optional,
                       'force_option_override': force_option_override,
                       'production_only': production_only,
                       'force': force,
                       'frozen_lockfile': frozen_lockfile}
    })
    task = self.create_task(context)

    package_manager_obj = task.get_package_manager(target=target)
    with mock.patch.object(package_manager_obj, 'run_command') as exec_call:
      exec_call.return_value.run.return_value.wait.return_value = 0
      task.execute()
      node_paths = context.products.get_data(NodePathsLocal)
      node_path = node_paths.node_path(target)
      self.assertIsNotNone(node_path)
      exec_call.assert_called_once_with(
        args=expected_params,
        node_paths=None)

  def test_resolve_default_no_options_yarn(self):
    self._test_resolve_options_helper(
      install_optional=False,
      force_option_override=False,
      production_only=False,
      force=False,
      frozen_lockfile=True,
      package_manager='yarnpkg',
      has_lock_file=True,
      expected_params=['--non-interactive', '--force'])

  def test_resolve_default_no_options_yarn_no_lock(self):
    self._test_resolve_options_helper(
      install_optional=False,
      force_option_override=False,
      production_only=False,
      force=False,
      frozen_lockfile=True,
      package_manager='yarnpkg',
      has_lock_file=False,
      expected_params=['--non-interactive', '--force'])

  def test_resolve_options_yarn(self):
    self._test_resolve_options_helper(
      install_optional=True,
      force_option_override=False,
      production_only=True,
      force=True,
      frozen_lockfile=False,
      package_manager='yarnpkg',
      has_lock_file=True,
      expected_params=['--non-interactive', '--production=true', '--force'])

  def test_resolve_options_yarn_force_override(self):
    self._test_resolve_options_helper(
      install_optional=False,
      force_option_override=True,
      production_only=True,
      force=False,
      frozen_lockfile=False,
      package_manager='yarnpkg',
      has_lock_file=True,
      expected_params=['--non-interactive', '--ignore-optional', '--production=true'])

  def test_resolve_default_no_options_npm(self):
    unsupported = 'not supported for NPM'
    with self.assertRaisesRegexp(TaskError, unsupported):
      self._test_resolve_options_helper(
        install_optional=False,
        force_option_override=False,
        production_only=False,
        force=False,
        frozen_lockfile=True,
        package_manager='npm',
        has_lock_file=True,
        expected_params=['--non-interactive', '--force'])
