# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import tempfile
import unittest

from pants.backend.jvm.subsystems.shader import RelocateRule, Shader, Shading
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.util.contextutil import open_zip
from pants.util.dirutil import safe_delete
from pants_test.subsystem.subsystem_util import init_subsystem


class ShaderTest(unittest.TestCase):
  def setUp(self):
    self.jarjar = '/not/really/jarjar.jar'
    init_subsystem(DistributionLocator)
    executor = SubprocessExecutor(DistributionLocator.cached())
    self.shader = Shader(jarjar_classpath=[self.jarjar], executor=executor)
    self.output_jar = '/not/really/shaded.jar'

  def populate_input_jar(self, *entries):
    fd, input_jar_path = tempfile.mkstemp(suffix='.jar')
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
                         .format(Shading.SHADE_PREFIX), lines[-1])  # Shade the rest.

      self.assertEqual(input_jar, command.pop(0))
      self.assertEqual(self.output_jar, command.pop(0))

  def test_infer_shaded_pattern(self):
    def assert_inference(from_pattern, prefix, to_pattern):
      result = ''.join(RelocateRule._infer_shaded_pattern_iter(from_pattern, prefix))
      self.assertEqual(to_pattern, result)

    assert_inference('com.foo.bar.Main', None, 'com.foo.bar.Main')
    assert_inference('com.foo.bar.', None, 'com.foo.bar.')
    assert_inference('com.foo.bar.', '__prefix__.', '__prefix__.com.foo.bar.')
    assert_inference('com.*.bar.', None, 'com.@1.bar.')
    assert_inference('com.*.bar.*.', None, 'com.@1.bar.@2.')
    assert_inference('com.*.bar.**', None, 'com.@1.bar.@2')
    assert_inference('*', None, '@1')
    assert_inference('**', None, '@1')
    assert_inference('**', '__prefix__.', '__prefix__.@1')

  def test_shading_exclude(self):
    def assert_exclude(from_pattern, to_pattern):
      self.assertEqual((from_pattern, to_pattern), Shading.create_exclude(from_pattern))

    assert_exclude('com.foo.bar.Main', 'com.foo.bar.Main')
    assert_exclude('com.foo.bar.**', 'com.foo.bar.@1')
    assert_exclude('com.*.bar.**', 'com.@1.bar.@2')

  def test_shading_exclude_package(self):
    self.assertEqual(('com.foo.bar.**', 'com.foo.bar.@1'),
                     Shading.create_exclude_package('com.foo.bar'))
    self.assertEqual(('com.foo.bar.*', 'com.foo.bar.@1'),
                     Shading.create_exclude_package('com.foo.bar', recursive=False))

  def test_relocate(self):
    self.assertEqual(('com.foo.bar.**', '{}com.foo.bar.@1'.format(Shading.SHADE_PREFIX)),
                     Shading.create_relocate(from_pattern='com.foo.bar.**'))

    self.assertEqual(('com.foo.bar.**', '{}com.foo.bar.@1'.format('__my_prefix__.')),
                     Shading.create_relocate(from_pattern='com.foo.bar.**',
                                      shade_prefix='__my_prefix__.'))

    self.assertEqual(('com.foo.bar.**', 'org.biz.baz.@1'.format('__my_prefix__.')),
                     Shading.create_relocate(from_pattern='com.foo.bar.**',
                                      shade_prefix='__my_prefix__.',
                                      shade_pattern='org.biz.baz.@1'))

  def test_relocate_package(self):
    self.assertEqual(('com.foo.bar.**', '{}com.foo.bar.@1'.format(Shading.SHADE_PREFIX)),
                     Shading.create_relocate_package('com.foo.bar'))
    self.assertEqual(('com.foo.bar.*', '{}com.foo.bar.@1'.format(Shading.SHADE_PREFIX)),
                     Shading.create_relocate_package('com.foo.bar', recursive=False))
    self.assertEqual(('com.foo.bar.**', '__p__.com.foo.bar.@1'),
                     Shading.create_relocate_package('com.foo.bar', shade_prefix='__p__.'))

  def test_zap_package(self):
    self.assertEqual(('zap', 'com.foo.bar.**'), Shading.create_zap_package('com.foo.bar', True))
    self.assertEqual(('zap', 'com.foo.bar.*'), Shading.create_zap_package('com.foo.bar', False))

  def test_keep_package(self):
    self.assertEqual(('keep', 'com.foo.bar.**'), Shading.create_keep_package('com.foo.bar', True))
    self.assertEqual(('keep', 'com.foo.bar.*'), Shading.create_keep_package('com.foo.bar', False))

  def test_rules_file(self):
    expected = [
      'rule a.b.c.** d.e.f.@1\n',
      'rule a.*.b shaded.a.@1.b\n',
      'rule x.y.z.** shaded.x.y.z.@1\n',
      'zap com.foo.bar.Main\n',
      'zap com.baz.*\n',
      'keep org.foobar.vegetable.Potato\n',
      'keep org.foobar.fruit.**\n',
    ]
    rules = [
      Shading.create_relocate('a.b.c.**', 'd.e.f.@1'),
      Shading.create_relocate('a.*.b', shade_prefix='shaded.'),
      Shading.create_relocate_package('x.y.z', shade_prefix='shaded.'),
      Shading.create_zap('com.foo.bar.Main'),
      Shading.create_zap_package('com.baz', recursive=False),
      Shading.create_keep('org.foobar.vegetable.Potato'),
      Shading.create_keep_package('org.foobar.fruit'),
    ]
    with self.shader.temporary_rules_file(rules) as fname:
      with open(fname, 'r') as f:
        received = f.readlines()
        self.assertEqual(received, expected)
