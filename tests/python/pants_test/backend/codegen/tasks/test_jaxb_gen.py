# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.codegen.register import build_file_aliases as register_codegen
from pants.backend.codegen.tasks.jaxb_gen import JaxbGen
from pants.backend.core.register import build_file_aliases as register_core
from pants.util.contextutil import temporary_file
from pants_test.tasks.task_test_base import TaskTestBase


class JaxbGenJavaTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return JaxbGen

  @property
  def alias_groups(self):
    return register_core().merge(register_codegen())

  def assert_files(self, package, contents, *expected_files):
    with temporary_file() as fp:
      fp.write(contents)
      fp.close()
      self.assertEqual(set(expected_files), set(JaxbGen._sources_to_be_generated(package, fp.name)))

  def create_schema(self, *component_names):
    return ('<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema">\n'
         + '\n'.join(self.create_complex_type(c) for c in component_names)
         + '\n</xsd:schema>')

  def create_complex_type(self, name):
    return (
         '''<xsd:complexType name="{name}">
              <xsd:sequence>
                <xsd:element name="commonName" type="xsd:string"/>
                <xsd:element name="scientificName" type="xsd:string"/>
                <xsd:element name="colorRGB" type="xsd:integer"/>
                <xsd:element name="tasty" type="xsd:boolean"/>
              </xsd:sequence>
            </xsd:complexType>'''.format(name=name)
    )

  def test_plain(self):
    self.assert_files(
      'com.actual.package',
      self.create_schema('ComplicatedVegetable', 'Orange', 'Apple', 'Aardvark'),
      'com/actual/package/ObjectFactory.java',
      'com/actual/package/ComplicatedVegetable.java',
      'com/actual/package/Orange.java',
      'com/actual/package/Aardvark.java',
      'com/actual/package/Apple.java'
    )

  def test_slashes(self):
    self.assert_files(
      'com/actual/package',
      self.create_schema('ComplicatedVegetable', 'Orange', 'Apple', 'Aardvark'),
      'com/actual/package/ObjectFactory.java',
      'com/actual/package/ComplicatedVegetable.java',
      'com/actual/package/Orange.java',
      'com/actual/package/Aardvark.java',
      'com/actual/package/Apple.java'
    )

  def test_leadtail(self):
    self.assert_files(
      '/com/actual/package/',
      self.create_schema('ComplicatedVegetable', 'Orange', 'Apple', 'Aardvark'),
      'com/actual/package/ObjectFactory.java',
      'com/actual/package/ComplicatedVegetable.java',
      'com/actual/package/Orange.java',
      'com/actual/package/Aardvark.java',
      'com/actual/package/Apple.java'
    )

  def test_correct_package(self):
    fix = JaxbGen._correct_package
    self.assertEqual(fix('com.foo.bar'), 'com.foo.bar', 'Expected no change.')
    self.assertEqual(fix('com/foo/bar'), 'com.foo.bar', 'Expected slashes to dots.')
    self.assertEqual(fix('.com.foo.bar'), 'com.foo.bar', 'Should have trimmed leading dots.')
    self.assertEqual(fix('com.foo.bar.'), 'com.foo.bar', 'Should have trimmed trialing dots.')
    self.assertEqual(fix('org/pantsbuild/example/foo'), 'org.pantsbuild.example.foo',
                     'Should work on packages other than com.foo.bar.')
    with self.assertRaises(ValueError):
      fix('po..ta..to')
    with self.assertRaises(ValueError):
      fix('po.ta..to')
    with self.assertRaises(ValueError):
      fix('..po.ta..to...')
    self.assertEqual(fix('///org.pantsbuild/example...'), 'org.pantsbuild.example')

  def test_guess_package(self):
    guess_history = []
    def guess(path):
      result = JaxbGen._correct_package(JaxbGen._guess_package(path))
      guess_history.append(result)
      return result
    supported_prefixes = ('com', 'org', 'net',)
    for prefix in supported_prefixes:
      self.assertEqual(guess('.pants.d/foo.bar/{0}/pantsbuild/potato/Potato.java'.format(prefix)),
                       '{0}.pantsbuild.potato'.format(prefix),
                       'Failed for prefix {0}: {1}.'.format(prefix, guess_history[-1]))
      self.assertEqual(guess('{0}/pantsbuild/potato/Potato.java'.format(prefix)),
                       '{0}.pantsbuild.potato'.format(prefix),
                       'Failed for prefix {0}: {1}.'.format(prefix, guess_history[-1]))
      self.assertEqual(guess('/User/foo/bar/.pants.d/gen/jaxb/foo/bar/'
                             '{0}/company/project/a/File.java'.format(prefix)),
                             '{0}.company.project.a'.format(prefix),
                             'Failed for prefix {0}: {1}.'.format(prefix, guess_history[-1]))
    self.assertEqual(guess('pantsbuild/potato/Potato.java'),
                     'pantsbuild.potato',
                     'Failed with no prefix: {0}'.format(guess_history[-1]))
