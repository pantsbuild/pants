# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
from textwrap import dedent

from pants.base.source_root import SourceRoot
from pants.base.target import Target
from pants_test.tasks.task_test_base import TaskTestBase

from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.targets.node_remote_module import NodeRemoteModule
from pants.contrib.node.tasks.node_paths import NodePaths
from pants.contrib.node.tasks.npm_resolve import NpmResolve


class NpmResolveTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return NpmResolve

  def test_noop(self):
    task = self.create_task(self.context())
    task.execute()

  def test_noop_na(self):
    target = self.make_target(spec=':not_a_node_target', target_type=Target)
    task = self.create_task(self.context(target_roots=[target]))
    task.execute()

  def test_resolve_remote(self):
    SourceRoot.register('3rdparty/node', NodeRemoteModule)
    typ = self.make_target(spec='3rdparty/node:typ', target_type=NodeRemoteModule, version='0.6.3')

    context = self.context(target_roots=[typ])
    task = self.create_task(context)
    task.execute()

    node_paths = context.products.get_data(NodePaths)
    node_path = node_paths.node_path(typ)
    self.assertIsNotNone(node_path)

    script = 'var typ = require("typ"); console.log("type of boolean is: " + typ.BOOLEAN)'
    out = task.node_distribution.node_command(args=['--eval', script]).check_output(cwd=node_path)
    self.assertIn('type of boolean is: boolean', out)

  def test_resolve_simple(self):
    SourceRoot.register('3rdparty/node', NodeRemoteModule)
    typ = self.make_target(spec='3rdparty/node:typ', target_type=NodeRemoteModule, version='0.6.3')

    SourceRoot.register('src/node', NodeModule)
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
    SourceRoot.register('3rdparty/node', NodeRemoteModule)
    typ1 = self.make_target(spec='3rdparty/node:typ1',
                            target_type=NodeRemoteModule,
                            package_name='typ',
                            version='0.6.1')
    typ2 = self.make_target(spec='3rdparty/node:typ2',
                            target_type=NodeRemoteModule,
                            package_name='typ',
                            version='0.6.x')

    SourceRoot.register('src/node', NodeModule)
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

    # Verify dependencies are de-duped
    typ_packages = []
    for root, _, files in os.walk(node_path):
      for f in files:
        if 'package.json' == f:
          with open(os.path.join(root, f)) as fp:
            package = json.load(fp)
            if 'typ' == package['name']:
              typ_packages.append(os.path.relpath(os.path.join(root, f), node_path))
    self.assertEqual(1, len(typ_packages),
                     'Expected to find exactly 1 de-duped `typ` package, but found these:\n\t{}'
                     .format('\n\t'.join(sorted(typ_packages))))

    script_path = os.path.join(node_path, 'leaf.js')
    out = task.node_distribution.node_command(args=[script_path]).check_output()
    lines = {line.strip() for line in out.splitlines()}
    self.assertIn('type of boolean is: boolean', lines)
    self.assertIn('type of bool is: boolean', lines)

  def test_resolve_preserves_package_json(self):
    SourceRoot.register('src/node', NodeModule)

    self.create_file('src/node/scripts_project/package.json', contents=dedent("""
      {
        "name": "scripts_project",
        "version": "1.2.3",
        "scripts": {
          "test": "mocha */dist.js"
        }
      }
    """))
    scripts_project = self.make_target(spec='src/node/scripts_project',
                                       target_type=NodeModule,
                                       sources=['package.json'],
                                       dependencies=[])
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
                       'Expected to find package name of `scripts_project`, but found: {}'.format(package['name']))
      self.assertEqual('1.2.3', package['version'],
                       'Expected to find package version of `1.2.3`, but found: {}'.format(package['version']))
      self.assertEqual('mocha */dist.js', package['scripts']['test'],
                       'Expected to find package test script of `mocha */dist.js`, but found: {}'
                       .format(package['scripts']['test']))
