# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import tempfile
import unittest

from pants.java.jar.shader import Shader
from pants.util.contextutil import open_zip
from pants.util.dirutil import safe_delete


class ShaderTest(unittest.TestCase):
  def setUp(self):
    self.jarjar = '/not/really/jarjar.jar'
    self.shader = Shader(jarjar=self.jarjar)
    self.output_jar = '/not/really/shaded.jar'

  def populate_input_jar(self, *entries):
    fd, input_jar_path = tempfile.mkstemp()
    os.close(fd)
    self.addCleanup(safe_delete, input_jar_path)
    with open_zip(input_jar_path, 'w') as jar:
      for entry in entries:
        jar.writestr(entry, '0xCAFEBABE')
    return input_jar_path

  def test_assemble_default_rules(self):
    input_jar = self.populate_input_jar('org/pantsbuild/tools/fake/Main.class',
                                        'com/google/common/base/Function.class')

    rules = self.shader.assemble_binary_rules('org.pantsbuild.tools.fake.Main', input_jar)

    self.assertEqual(Shader.exclude_package('org.pantsbuild.tools.fake'), rules[0])
    self.assertIn(Shader.exclude_package('javax.annotation'), rules[1:-1])
    self.assertEqual(Shader.shade_package('com.google.common.base'), rules[-1])

  def test_assemble_default_rules_default_package(self):
    input_jar = self.populate_input_jar('main.class', 'com/google/common/base/Function.class')

    rules = self.shader.assemble_binary_rules('main', input_jar)

    self.assertEqual(Shader.exclude_package(), rules[0])
    self.assertIn(Shader.exclude_package('javax.annotation'), rules[1:-1])
    self.assertEqual(Shader.shade_package('com.google.common.base'), rules[-1])

  def test_assemble_custom_rules(self):
    input_jar = self.populate_input_jar('main.class')

    rules = self.shader.assemble_binary_rules('main', input_jar,
                                              custom_rules=[Shader.shade_class('bob'),
                                                            Shader.exclude_class('fred')])

    self.assertEqual(Shader.shade_class('bob'), rules[0])
    self.assertEqual(Shader.exclude_class('fred'), rules[1])
    self.assertEqual(Shader.exclude_package(), rules[2])
    self.assertIn(Shader.exclude_package('javax.annotation'), rules[3:])

  def test_runner_command(self):
    input_jar = self.populate_input_jar('main.class', 'com/google/common/base/Function.class')
    custom_rules = [Shader.exclude_package('log4j', recursive=True)]

    with self.shader.binary_shader(self.output_jar, 'main', input_jar,
                                   custom_rules=custom_rules) as shader:
      command = shader.command

      self.assertTrue(command.pop(0).endswith('java'))

      jar_or_cp = command.pop(0)
      self.assertIn(jar_or_cp, {'-cp', 'classpath', '-jar'})
      self.assertEqual(self.jarjar, os.path.abspath(command.pop(0)))

      if jar_or_cp != '-jar':
        # We don't really care what the name of the jarjar main class is - shader.command[2]
        command.pop(0)

      self.assertEqual('process', command.pop(0))

      rules_file = command.pop(0)
      self.assertTrue(os.path.exists(rules_file))
      with open(rules_file) as fp:
        lines = fp.read().splitlines()
        self.assertEqual('rule log4j.** log4j.@1', lines[0])  # The custom rule.
        self.assertEqual('rule * @1', lines[1])  # Exclude main's package.
        self.assertIn('rule javax.annotation.* javax.annotation.@1', lines)  # Exclude system.
        self.assertEqual('rule com.google.common.base.* {}com.google.common.base.@1'
                         .format(Shader.SHADE_PREFIX), lines[-1])  # Shade the rest.

      self.assertEqual(input_jar, command.pop(0))
      self.assertEqual(self.output_jar, command.pop(0))
