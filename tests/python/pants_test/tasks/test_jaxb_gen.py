# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.backend.codegen.tasks.jaxb_gen import JaxbGen
from pants.util.contextutil import temporary_file


class JaxbGenTestBase(unittest.TestCase):
  """Basically copied from test_protobuf_gen.py.

  Contains helper method to check generated temp files.
  """
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

class JaxbGenJavaTest(JaxbGenTestBase):
  """Test the java code generation.

  Mostly just tests that code would be put in the proper package, since that's the easiest point of
  failure.
  """

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

