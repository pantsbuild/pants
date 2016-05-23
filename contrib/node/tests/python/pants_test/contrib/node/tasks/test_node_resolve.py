# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
from textwrap import dedent

from pants.build_graph.target import Target
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.node.subsystems.resolvers.node_preinstalled_module_resolver import \
  NodePreinstalledModuleResolver
from pants.contrib.node.subsystems.resolvers.npm_resolver import NpmResolver
from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.targets.node_preinstalled_module import NodePreinstalledModule
from pants.contrib.node.targets.node_remote_module import NodeRemoteModule
from pants.contrib.node.tasks.node_paths import NodePaths
from pants.contrib.node.tasks.node_resolve import NodeResolve


class NodeResolveTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return NodeResolve

  def setUp(self):
    super(NodeResolveTest, self).setUp()
    NodeResolve.register_resolver_for_type(NodePreinstalledModule, NodePreinstalledModuleResolver)
    NodeResolve.register_resolver_for_type(NodeModule, NpmResolver)

  def tearDown(self):
    super(NodeResolveTest, self).tearDown()
    NodeResolve._clear_resolvers()

  def test_register_resolver_for_type(self):
    NodeResolve._clear_resolvers()

    self.assertIsNone(NodeResolve._resolver_for_target(NodePreinstalledModule))
    self.assertIsNone(NodeResolve._resolver_for_target(NodeModule))

    node_preinstalled__module_target = self.make_target(
      spec=':empty_fake_node_preinstalled_module_target',
      target_type=NodePreinstalledModule)
    NodeResolve.register_resolver_for_type(NodePreinstalledModule, NodePreinstalledModuleResolver)
    self.assertEqual(NodePreinstalledModuleResolver,
                     NodeResolve._resolver_for_target(node_preinstalled__module_target))

    node_module_target = self.make_target(spec=':empty_fake_node_module_target',
                                          target_type=NodeModule)
    NodeResolve.register_resolver_for_type(NodeModule, NpmResolver)
    self.assertEqual(NpmResolver,
                     NodeResolve._resolver_for_target(node_module_target))

  def test_product_types(self):
    self.assertEqual([NodePaths], NodeResolve.product_types())

  def test_noop(self):
    task = self.create_task(self.context())
    task.execute()

  def test_noop_na(self):
    target = self.make_target(spec=':not_a_node_target', target_type=Target)
    task = self.create_task(self.context(target_roots=[target]))
    task.execute()

  def test_resolve_simple(self):
    typ = self.make_target(spec='3rdparty/node:typ', target_type=NodeRemoteModule, version='0.6.3')

    self.create_file('src/node/util/util.js', contents=dedent("""
      var typ = require('typ');
      console.log("type of boolean is: " + typ.BOOLEAN);
    """))
    target = self.make_target(spec='src/node/util',
                              target_type=NodeModule,
                              sources=['util.js'],
                              dependencies=[typ])

    context = self.context(target_roots=[target])
    task = self.create_task(context)
    task.execute()

    node_paths = context.products.get_data(NodePaths)
    node_path = node_paths.node_path(target)
    self.assertIsNotNone(node_path)

    script_path = os.path.join(node_path, 'util.js')
    out = task.node_distribution.node_command(args=[script_path]).check_output()
    self.assertIn('type of boolean is: boolean', out)

  def test_resolve_simple_graph(self):
    typ1 = self.make_target(spec='3rdparty/node:typ1',
                            target_type=NodeRemoteModule,
                            package_name='typ',
                            version='0.6.x')
    typ2 = self.make_target(spec='3rdparty/node:typ2',
                            target_type=NodeRemoteModule,
                            package_name='typ',
                            version='0.6.1')

    self.create_file('src/node/util/typ.js', contents=dedent("""
      var typ = require('typ');
      module.exports = {
        BOOL: typ.BOOLEAN
      };
    """))
    util = self.make_target(spec='src/node/util',
                            target_type=NodeModule,
                            sources=['typ.js'],
                            dependencies=[typ1])

    self.create_file('src/node/leaf/leaf.js', contents=dedent("""
      var typ = require('typ');
      var util_typ = require('util/typ');
      console.log("type of boolean is: " + typ.BOOLEAN);
      console.log("type of bool is: " + util_typ.BOOL);
    """))
    leaf = self.make_target(spec='src/node/leaf',
                            target_type=NodeModule,
                            sources=['leaf.js'],
                            dependencies=[util, typ2])
    context = self.context(target_roots=[leaf])
    task = self.create_task(context)
    task.execute()

    node_paths = context.products.get_data(NodePaths)
    self.assertIsNotNone(node_paths.node_path(util))

    node_path = node_paths.node_path(leaf)
    self.assertIsNotNone(node_paths.node_path(leaf))

    # Verify the 'typ' package is not duplicated under leaf. The target dependency tree is:
    # leaf
    #   typ2 (0.6.1)
    #   util
    #     typ1 (0.6.x)
    # If we install leaf normally, NPM will install the typ2 target (typ version 0.6.1) at the top
    # level under leaf, and then not install the typ1 target (typ version 0.6.x) under util
    # because the dependency is already satisfied.
    typ_packages = []
    for root, _, files in os.walk(node_path):
      for f in files:
        if 'package.json' == f:
          with open(os.path.join(root, f)) as fp:
            package = json.load(fp)
            if 'typ' == package['name']:
              typ_packages.append(os.path.relpath(os.path.join(root, f), node_path))
              self.assertEqual(1, len(typ_packages),
                              'Expected to find exactly 1 de-duped `typ` package, but found these:'
                              '\n\t{}'.format('\n\t'.join(sorted(typ_packages))))

    script_path = os.path.join(node_path, 'leaf.js')
    out = task.node_distribution.node_command(args=[script_path]).check_output()
    lines = {line.strip() for line in out.splitlines()}
    self.assertIn('type of boolean is: boolean', lines)
    self.assertIn('type of bool is: boolean', lines)

  def test_resolve_preserves_package_json(self):
    util = self.make_target(spec='src/node/util',
                            target_type=NodeModule,
                            sources=[],
                            dependencies=[])

    self.create_file('src/node/scripts_project/package.json', contents=dedent("""
      {
        "name": "scripts_project",
        "version": "1.2.3",
        "dependencies": { "A": "file://A" },
        "devDependencies": { "B": "file://B" },
        "peerDependencies": { "C": "file://C" },
        "optionalDependencies": { "D": "file://D" },
        "scripts": {
          "test": "mocha */dist.js"
        }
      }
    """))
    scripts_project = self.make_target(spec='src/node/scripts_project',
                                       target_type=NodeModule,
                                       sources=['package.json'],
                                       dependencies=[util])
    context = self.context(target_roots=[scripts_project])
    task = self.create_task(context)
    task.execute()

    node_paths = context.products.get_data(NodePaths)
    node_path = node_paths.node_path(scripts_project)
    self.assertIsNotNone(node_paths.node_path(scripts_project))

    package_json_path = os.path.join(node_path, 'package.json')
    with open(package_json_path) as fp:
      package = json.load(fp)
      self.assertEqual('scripts_project', package['name'],
                       'Expected to find package name of `scripts_project`, but found: {}'
                       .format(package['name']))
      self.assertEqual('1.2.3', package['version'],
                       'Expected to find package version of `1.2.3`, but found: {}'
                       .format(package['version']))
      self.assertEqual('mocha */dist.js', package['scripts']['test'],
                       'Expected to find package test script of `mocha */dist.js`, but found: {}'
                       .format(package['scripts']['test']))
      self.assertEqual(node_paths.node_path(util), package['dependencies']['util'])
      self.assertNotIn('A', package['dependencies'])
      self.assertNotIn('devDependencies', package)
      self.assertNotIn('peerDependencies', package)
      self.assertNotIn('optionalDependencies', package)
