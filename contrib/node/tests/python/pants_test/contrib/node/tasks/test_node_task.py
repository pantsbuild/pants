# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os
import string
from builtins import open, zip
from textwrap import dedent

from future.utils import PY3
from pants.build_graph.target import Target
from pants.util.contextutil import pushd, temporary_dir
from pants_test.task_test_base import TaskTestBase

from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.targets.node_remote_module import NodeRemoteModule
from pants.contrib.node.targets.node_test import NodeTest
from pants.contrib.node.tasks.node_task import NodeTask


class NodeTaskTest(TaskTestBase):

  class TestNodeTask(NodeTask):

    def execute(self):
      # We never execute the task, we just want to exercise the helpers it provides subclasses.
      raise NotImplementedError()

  @classmethod
  def task_type(cls):
    return cls.TestNodeTask

  def test_is_node_package(self):
    expected = {
      NodeRemoteModule: True,
      NodeModule: True,
      NodeTest: False,
      Target: False,
    }
    self.assertEqual(expected, self._type_check(expected.keys(), NodeTask.is_node_package))

  def test_is_node_module(self):
    expected = {
      NodeRemoteModule: False,
      NodeModule: True,
      NodeTest: False,
      Target: False,
    }
    self.assertEqual(expected, self._type_check(expected.keys(), NodeTask.is_node_module))

  def test_is_node_remote_module(self):
    expected = {
      NodeRemoteModule: True,
      NodeModule: False,
      NodeTest: False,
      Target: False,
    }
    self.assertEqual(expected, self._type_check(expected.keys(), NodeTask.is_node_remote_module))

  def test_is_node_test(self):
    expected = {
      NodeRemoteModule: False,
      NodeModule: False,
      NodeTest: True,
      Target: False,
    }
    self.assertEqual(expected, self._type_check(expected.keys(), NodeTask.is_node_test))

  def _type_check(self, types, type_check_function):
    # Make sure the diff display length is long enough for the test_is_* tests.
    # It's a little weird to include this side effect here, but otherwise it would have to
    # be duplicated or go in the setup (in which case it would affect all tests).
    self.maxDiff = None

    target_names = [':' + letter for letter in list(string.ascii_lowercase)]
    types_with_target_names = zip(types, target_names)

    type_check_results = {type: type_check_function(self.make_target(target_name, type))
                          for type, target_name in types_with_target_names}

    return type_check_results

  def test_execute_node(self):
    task = self.create_task(self.context())
    with temporary_dir() as chroot:
      script = os.path.join(chroot, 'test.js')
      proof = os.path.join(chroot, 'path')
      with open(script, 'w') as fp:
        fp.write(dedent("""
          var fs = require('fs');
          fs.writeFile("{proof}", "Hello World!", function(err) {{}});
          """).format(proof=proof))
      self.assertFalse(os.path.exists(proof))
      returncode, command = task.execute_node([script], workunit_name='test')

      self.assertEqual(0, returncode)
      self.assertTrue(os.path.exists(proof))
      with open(proof, 'r') as fp:
        self.assertEqual('Hello World!', fp.read().strip())

  def test_execute_npm(self):
    task = self.create_task(self.context())
    with temporary_dir() as chroot:
      proof = os.path.join(chroot, 'proof')
      self.assertFalse(os.path.exists(proof))
      package = {
        'name': 'pantsbuild.pants.test',
        'version': '0.0.0',
        'scripts': {
          'proof': 'echo "42" > {}'.format(proof)
        }
      }
      mode = 'w' if PY3 else 'wb'
      with open(os.path.join(chroot, 'package.json'), mode) as fp:
        json.dump(package, fp)
      with pushd(chroot):
        returncode, _ = task.run_script(
          'proof',
          package_manager=task.node_distribution.get_package_manager(package_manager='npm'),
          workunit_name='test')

      self.assertEqual(0, returncode)
      self.assertTrue(os.path.exists(proof))
      with open(proof, 'r') as fp:
        self.assertEqual('42', fp.read().strip())

  def test_execute_yarnpkg(self):
    task = self.create_task(self.context())
    with temporary_dir() as chroot:
      proof = os.path.join(chroot, 'proof')
      self.assertFalse(os.path.exists(proof))
      package = {
        'name': 'pantsbuild.pants.test',
        'version': '0.0.0',
        'scripts': {
          'proof': 'echo "42" > {}'.format(proof)
        }
      }
      mode = 'w' if PY3 else 'wb'
      with open(os.path.join(chroot, 'package.json'), mode) as fp:
        json.dump(package, fp)
      with pushd(chroot):
        returncode, _ = task.run_script(
          'proof',
          package_manager=task.node_distribution.get_package_manager(package_manager='yarnpkg'),
          workunit_name='test')

      self.assertEqual(0, returncode)
      self.assertTrue(os.path.exists(proof))
      with open(proof) as fp:
        self.assertEqual('42', fp.read().strip())
