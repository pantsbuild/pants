# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.python.python_requirement import PythonRequirement
from pants.base.address import SyntheticAddress
from pants.base.payload_field import (ExcludesField,
                                      JarsField,
                                      PrimitiveField,
                                      PythonRequirementsField,
                                      SourcesField)
from pants.backend.core.targets.source_set import DefaultSourceSet

from pants_test.base_test import BaseTest


class PayloadTest(BaseTest):
  def test_excludes_field(self):
    empty = ExcludesField()
    empty_fp = empty.fingerprint()
    self.assertEqual(empty_fp, empty.fingerprint())
    normal = ExcludesField([Exclude('com', 'foozle'), Exclude('org')])
    normal_fp = normal.fingerprint()
    self.assertEqual(normal_fp, normal.fingerprint())
    normal_dup = ExcludesField([Exclude('com', 'foozle'), Exclude('org')])
    self.assertEqual(normal_fp, normal_dup.fingerprint())
    self.assertNotEqual(empty_fp, normal_fp)

  def test_jars_field_order(self):
    jar1 = JarDependency('com', 'foo', '1.0.0')
    jar2 = JarDependency('org', 'baz')

    self.assertNotEqual(
      JarsField([jar1, jar2]).fingerprint(),
      JarsField([jar2, jar1]).fingerprint(),
    )

  def test_jars_field_artifacts(self):
    jar1 = JarDependency('com', 'foo', '1.0.0').with_artifact('com', 'baz')
    jar2 = JarDependency('com', 'foo', '1.0.0')

    self.assertNotEqual(
      JarsField([jar1]).fingerprint(),
      JarsField([jar2]).fingerprint(),
    )

  def test_jars_field_artifacts(self):
    jar1 = (JarDependency('com', 'foo', '1.0.0')
              .with_artifact('com', 'baz')
              .with_artifact('org', 'bat'))
    jar2 = (JarDependency('com', 'foo', '1.0.0')
              .with_artifact('org', 'bat')
              .with_artifact('com', 'baz'))
    jar3 = (JarDependency('com', 'foo', '1.0.0')
              .with_artifact('org', 'bat'))

    jar4 = JarDependency('com', 'foo', '1.0.0')

    self.assertEqual(
      JarsField([jar1]).fingerprint(),
      JarsField([jar2]).fingerprint(),
    )
    self.assertNotEqual(
      JarsField([jar1]).fingerprint(),
      JarsField([jar3]).fingerprint(),
    )
    self.assertNotEqual(
      JarsField([jar1]).fingerprint(),
      JarsField([jar4]).fingerprint(),
    )
    self.assertNotEqual(
      JarsField([jar3]).fingerprint(),
      JarsField([jar4]).fingerprint(),
    )

  def test_jars_field_artifacts_ordering(self):
    """JarDependencies throw away ordering information about their artifacts in the cache key.

    But they do not throw it away in their internal representation!  In the future, this should be
    fixed: either they should sort them as they are added and keep a canonical representation, or
    the order information should be preserved.
    """

    jar1 = (JarDependency('com', 'foo', '1.0.0')
              .with_artifact('com', 'baz')
              .with_artifact('org', 'bat'))
    jar2 = (JarDependency('com', 'foo', '1.0.0')
              .with_artifact('org', 'bat')
              .with_artifact('com', 'baz'))

    self.assertEqual(
      JarsField([jar1]).fingerprint(),
      JarsField([jar2]).fingerprint(),
    )

  def test_jars_field_configuration_order(self):
    """Like artifacts, JarDependencies throw away order information about their configurations.

    But only in the hash key, the internal representation is in the order inserted.
    """
    jar1 = (JarDependency('com', 'foo', '1.0.0')
              .with_docs()
              .with_sources())
    jar2 = (JarDependency('com', 'foo', '1.0.0')
              .with_sources()
              .with_docs())

    self.assertEqual(
      JarsField([jar1]).fingerprint(),
      JarsField([jar2]).fingerprint(),
    )

  def test_jars_field_configuration(self):
    jar1 = (JarDependency('com', 'foo', '1.0.0')
              .with_sources())
    jar2 = (JarDependency('com', 'foo', '1.0.0')
              .with_docs())

    self.assertNotEqual(
      JarsField([jar1]).fingerprint(),
      JarsField([jar2]).fingerprint(),
    )

  def test_jars_field_artifact_configuration(self):
    """Like artifacts, JarDependencies throw away order information about their configurations.

    But only in the hash key, the internal representation is in the order inserted.
    """
    jar1 = (JarDependency('com', 'foo', '1.0.0')
              .with_sources())
    jar2 = (JarDependency('com', 'foo', '1.0.0')
              .with_docs())

    self.assertNotEqual(
      JarsField([jar1]).fingerprint(),
      JarsField([jar2]).fingerprint(),
    )

  def test_jars_field_apidocs(self):
    """apidocs are not properly rolled into the cache key right now.  Is this intentional?"""

    jar1 = JarDependency('com', 'foo', '1.0.0', apidocs='pantsbuild.github.io')
    jar2 = JarDependency('com', 'foo', '1.0.0', apidocs='someother.pantsbuild.github.io')

    self.assertEqual(
      JarsField([jar1]).fingerprint(),
      JarsField([jar2]).fingerprint(),
    )

  def test_python_requirements_field(self):
    req1 = PythonRequirement('foo==1.0')
    req2 = PythonRequirement('bar==1.0')

    self.assertNotEqual(
      PythonRequirementsField([req1]).fingerprint(),
      PythonRequirementsField([req2]).fingerprint(),
    )

  def test_python_requirements_field_version_filter(self):
    """version_filter is a lambda and can't be hashed properly.

    Since in practice this is only ever used to differentiate between py3k and py2, it should use
    a tuple of strings or even just a flag instead.
    """
    req1 = PythonRequirement('foo==1.0', version_filter=lambda py, pl: False)
    req2 = PythonRequirement('foo==1.0')

    self.assertEqual(
      PythonRequirementsField([req1]).fingerprint(),
      PythonRequirementsField([req2]).fingerprint(),
    )

  def test_primitive_field(self):
    self.assertEqual(
      PrimitiveField({'foo': 'bar'}).fingerprint(),
      PrimitiveField({'foo': 'bar'}).fingerprint(),
    )
    self.assertEqual(
      PrimitiveField(['foo', 'bar']).fingerprint(),
      PrimitiveField(('foo', 'bar')).fingerprint(),
    )
    self.assertEqual(
      PrimitiveField(['foo', 'bar']).fingerprint(),
      PrimitiveField(('foo', 'bar')).fingerprint(),
    )
    self.assertEqual(
      PrimitiveField('foo').fingerprint(),
      PrimitiveField(b'foo').fingerprint(),
    )
    self.assertNotEqual(
      PrimitiveField('foo').fingerprint(),
      PrimitiveField('bar').fingerprint(),
    )

  def test_excludes_field(self):
    self.assertEqual(
      ExcludesField([Exclude('com', 'foo')]).fingerprint(),
      ExcludesField([Exclude('com', 'foo')]).fingerprint(),
    )
    self.assertEqual(
      ExcludesField([]).fingerprint(),
      ExcludesField().fingerprint(),
    )
    self.assertNotEqual(
      ExcludesField([Exclude('com', 'foo')]).fingerprint(),
      ExcludesField([Exclude('com')]).fingerprint(),
    )
    self.assertNotEqual(
      ExcludesField([Exclude('com', 'foo'), Exclude('org', 'bar')]).fingerprint(),
      ExcludesField([Exclude('org', 'bar'), Exclude('com', 'foo')]).fingerprint(),
    )

  def test_sources_field(self):
    self._counter = 0

    def make_source_set(rel_path, file_list):
      self._counter += 1
      name = 'dummy={0}'.format(self._counter)

      return DefaultSourceSet(
        file_list,
        name=name,
        address=SyntheticAddress.parse(rel_path, 'foo'),
        build_graph=self.build_graph,
        rel_path=rel_path,
      )
    self.create_file('foo/bar/a.txt', 'a_contents')
    self.create_file('foo/bar/b.txt', 'b_contents')

    self.assertNotEqual(
      SourcesField(make_source_set(
        rel_path='foo/bar',
        file_list=['a.txt'])
      ).fingerprint(),
      SourcesField(make_source_set(
        rel_path='foo/bar',
        file_list=['b.txt'])
      ).fingerprint(),
      )

    self.assertEqual(
      SourcesField(make_source_set(
        rel_path='foo/bar',
        file_list=['a.txt']),
      ).fingerprint(),
      SourcesField(make_source_set(
        rel_path='foo/bar',
        file_list=['a.txt']),
      ).fingerprint(),
    )

    self.assertEqual(
      SourcesField(make_source_set(
        rel_path='foo/bar',
        file_list=['a.txt']),
      ).fingerprint(),
      SourcesField(make_source_set(
        rel_path='foo/bar',
        file_list=['a.txt']),
      ).fingerprint(),
    )

    self.assertEqual(
      SourcesField(make_source_set(
        rel_path='foo/bar',
        file_list=['a.txt', 'b.txt']),
      ).fingerprint(),
      SourcesField(make_source_set(
        rel_path='foo/bar',
        file_list=['b.txt', 'a.txt']),
      ).fingerprint(),
    )

    fp1 = SourcesField(make_source_set(
            rel_path='foo/bar',
            file_list=['a.txt']),
          ).fingerprint()
    self.create_file('foo/bar/a.txt', 'a_contents_different')
    fp2 = SourcesField(make_source_set(
            rel_path='foo/bar',
            file_list=['a.txt']),
          ).fingerprint()

    self.assertNotEqual(fp1, fp2)
