# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

import pytest

from pants.backend.core.register import build_file_aliases as register_core
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.jvm.targets.jvm_app import DirectoryReMapper
from pants.base.address import BuildFileAddress
from pants.base.address_lookup_error import AddressLookupError
from pants.base.exceptions import TargetDefinitionException
from pants_test.base_test import BaseTest


class JvmAppTest(BaseTest):
  @property
  def alias_groups(self):
    return register_jvm()

  def setUp(self):
    super(JvmAppTest, self).setUp()
    self.create_dir('src/java/org/archimedes/buoyancy/config')
    self.create_file('src/java/org/archimedes/buoyancy/config/densities.xml')
    self.add_to_build_file('src/java/org/archimedes/buoyancy/BUILD', dedent('''
      jvm_binary(name='bin')
    '''))
    self.add_to_build_file('src/java/org/archimedes/buoyancy/BUILD', dedent('''
      jvm_binary(name='bin2')
    '''))

  def test_simple(self):
    self.add_to_build_file('BUILD', dedent('''
    jvm_app(name='foo',
      basename='foo-app',
      binary = ':foo-binary',
    )
    jvm_binary(name='foo-binary',
      main='com.example.Foo',
    )
    '''))

    app_target = self.target('//:foo')
    binary_target = self.target('//:foo-binary')
    self.assertEquals('foo-app', app_target.payload.basename)
    self.assertEquals('foo-app', app_target.basename)
    self.assertEquals(binary_target, app_target.binary)
    self.assertEquals([':foo-binary'], list(app_target.traversable_dependency_specs))

  def test_bad_basename(self):
    build_file = self.add_to_build_file('BUILD', dedent('''
    jvm_app(name='foo',
      basename='foo',
    )
    '''))
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'Invalid target JvmApp.* foo.*basename must not equal name.'):
      self.build_graph.inject_address_closure(BuildFileAddress(build_file, 'foo'))

  def test_binary_via_binary(self):
    self.add_to_build_file('src/java/org/archimedes/buoyancy/BUILD', dedent('''
      jvm_app(name='buoyancy',
        binary=':bin',
        bundles=[
          bundle(fileset='config/densities.xml')
        ]
      )
    '''))
    app = self.target('src/java/org/archimedes/buoyancy')
    binary = self.target('src/java/org/archimedes/buoyancy:bin')
    self.assertEquals(app.binary, binary)

  def test_binary_via_dependencies(self):
    self.add_to_build_file('src/java/org/archimedes/buoyancy/BUILD', dedent('''
      jvm_app(name='buoyancy',
        dependencies=[':bin'],
        bundles=[
          bundle(fileset='config/densities.xml')
        ]
      )
    '''))
    app = self.target('src/java/org/archimedes/buoyancy')
    binary = self.target('src/java/org/archimedes/buoyancy:bin')
    self.assertEquals(app.binary, binary)

  def test_degenerate_binaries(self):
    self.add_to_build_file('src/java/org/archimedes/buoyancy/BUILD', dedent('''
      jvm_app(name='buoyancy',
        binary=':bin',
        dependencies=[':bin'],
        bundles=[
          bundle(fileset='config/densities.xml')
        ]
      )
    '''))
    app = self.target('src/java/org/archimedes/buoyancy')
    binary = self.target('src/java/org/archimedes/buoyancy:bin')
    self.assertEquals(app.binary, binary)

  def test_no_binary(self):
    self.add_to_build_file('src/java/org/archimedes/buoyancy/BUILD', dedent('''
      jvm_app(name='buoyancy',
        bundles=[
          bundle(fileset='config/densities.xml')
        ]
      )
    '''))
    app = self.target('src/java/org/archimedes/buoyancy')
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'Invalid target JvmApp.*src/java/org/archimedes/buoyancy/BUILD, '
                                 r'buoyancy.*A JvmApp must define exactly one'):
      app.binary

  def test_too_many_binaries_mixed(self):
    self.add_to_build_file('src/java/org/archimedes/buoyancy/BUILD', dedent('''
      jvm_app(name='buoyancy',
        binary=':bin',
        dependencies=[':bin2'],
        bundles=[
          bundle(fileset='config/densities.xml')
        ]
      )
    '''))
    app = self.target('src/java/org/archimedes/buoyancy')
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'Invalid target JvmApp.*src/java/org/archimedes/buoyancy/BUILD, '
                                 r'buoyancy.*A JvmApp must define exactly one'):
      app.binary

  def test_too_many_binaries_via_deps(self):
    self.add_to_build_file('src/java/org/archimedes/buoyancy/BUILD', dedent('''
      jvm_app(name='buoyancy',
        dependencies=[':bin', ':bin2'],
        bundles=[
          bundle(fileset='config/densities.xml')
        ]
      )
    '''))
    app = self.target('src/java/org/archimedes/buoyancy')
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'Invalid target JvmApp.*src/java/org/archimedes/buoyancy/BUILD, '
                                 r'buoyancy.*A JvmApp must define exactly one'):

      app.binary

  def test_not_a_binary(self):
    self.add_to_build_file('src/java/org/archimedes/buoyancy/BUILD', dedent('''
      jvm_app(name='buoyancy',
        binary=':bin',
        bundles=[
          bundle(fileset='config/densities.xml')
        ]
      )
    '''))

    self.add_to_build_file('src/java/org/archimedes/buoyancy/BUILD', dedent('''
      jvm_app(name='buoyancy2',
        binary=':buoyancy',
        bundles=[
          bundle(fileset='config/densities.xml')
        ]
      )
    '''))
    app = self.target('src/java/org/archimedes/buoyancy:buoyancy2')
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'Invalid target JvmApp.*src/java/org/archimedes/buoyancy/BUILD, '
                                r'buoyancy2.* Expected JvmApp binary dependency'):
      app.binary


class BundleTest(BaseTest):
  @property
  def alias_groups(self):
    return register_core().merge(register_jvm())

  def test_bundle_filemap_dest_bypath(self):
    self.create_dir('src/java/org/archimedes/buoyancy/config')
    self.create_file('src/java/org/archimedes/buoyancy/config/densities.xml')
    self.add_to_build_file('src/java/org/archimedes/buoyancy/BUILD', dedent('''
      jvm_binary(name='unused')
    '''))
    self.add_to_build_file('src/java/org/archimedes/buoyancy/BUILD', dedent('''
      jvm_app(name='buoyancy',
        dependencies=[':unused'],
        bundles=[
          bundle(fileset='config/densities.xml')
        ]
      )
    '''))
    app = self.target('src/java/org/archimedes/buoyancy')
    # after one big refactor, ../../../../../ snuck into this path:
    self.assertEquals(app.bundles[0].filemap.values()[0],
                      'config/densities.xml')

  def test_bundle_filemap_dest_byglobs(self):
    self.create_dir('src/java/org/archimedes/tub/config')
    self.create_file('src/java/org/archimedes/tub/config/one.xml')
    self.create_file('src/java/org/archimedes/tub/config/two.xml')
    self.add_to_build_file('src/java/org/archimedes/tub/BUILD', dedent('''
      jvm_binary(name='unused')
    '''))
    self.add_to_build_file('src/java/org/archimedes/tub/BUILD', dedent('''
      jvm_app(name='tub',
        dependencies=[':unused'],
        bundles=[
          bundle(fileset=globs('config/*.xml'))
        ]
      )
    '''))
    app = self.target('src/java/org/archimedes/tub')
    for k in app.bundles[0].filemap.keys():
      if k.endswith('archimedes/tub/config/one.xml'):
        onexml_key = k
    self.assertEquals(app.bundles[0].filemap[onexml_key],
                      'config/one.xml')

  def test_bundle_filemap_dest_relative(self):
    self.create_dir('src/java/org/archimedes/crown/gold/config')
    self.create_file('src/java/org/archimedes/crown/gold/config/five.xml')
    self.add_to_build_file('src/java/org/archimedes/crown/BUILD', dedent('''
      jvm_binary(name='unused')
    '''))
    self.add_to_build_file('src/java/org/archimedes/crown/BUILD', dedent('''
      jvm_app(name='crown',
        dependencies=[':unused'],
        bundles=[
          bundle(relative_to='gold', fileset='gold/config/five.xml')
        ]
      )
    '''))
    app = self.target('src/java/org/archimedes/crown')
    for k in app.bundles[0].filemap.keys():
      if k.endswith('archimedes/crown/gold/config/five.xml'):
        fivexml_key = k
    self.assertEquals(app.bundles[0].filemap[fivexml_key],
                      'config/five.xml')

  def test_bundle_filemap_dest_remap(self):
    self.create_dir('src/java/org/archimedes/crown/config')
    self.create_file('src/java/org/archimedes/crown/config/one.xml')
    self.add_to_build_file('src/java/org/archimedes/crown/BUILD', dedent('''
      jvm_binary(name='unused')
    '''))
    self.add_to_build_file('src/java/org/archimedes/crown/BUILD', dedent('''
      jvm_app(name='crown',
        dependencies=[':unused'],
        bundles=[
          bundle(mapper=DirectoryReMapper('src/java/org/archimedes/crown/config', 'gold/config'), fileset='config/one.xml')
        ]
      )
    '''))
    app = self.target('src/java/org/archimedes/crown')
    for k in app.bundles[0].filemap.keys():
      if k.endswith('archimedes/crown/config/one.xml'):
        onexml_key = k
    self.assertEquals(app.bundles[0].filemap[onexml_key],
                      'gold/config/one.xml')

  def test_bundle_filemap_remap_base_not_exists(self):
    # Create directly
    with pytest.raises(DirectoryReMapper.BaseNotExistsError):
      DirectoryReMapper("dummy/src/java/org/archimedes/crown/missing", "dummy")

    # Used in the BUILD
    self.create_dir('src/java/org/archimedes/crown/config')
    self.create_file('src/java/org/archimedes/crown/config/one.xml')
    self.add_to_build_file('src/java/org/archimedes/crown/BUILD', dedent('''
      jvm_binary(name='unused')
    '''))
    self.add_to_build_file('src/java/org/archimedes/crown/BUILD', dedent('''
      jvm_app(name='crown',
        dependencies=[':unused'],
        bundles=[
          bundle(mapper=DirectoryReMapper('src/java/org/archimedes/crown/missing', 'gold/config'), fileset='config/one.xml')
        ]
      )
    '''))

    with pytest.raises(AddressLookupError):
      self.target('src/java/org/archimedes/crown')

  def test_bundle_add(self):
    self.create_dir('src/java/org/archimedes/volume/config/stone')
    self.create_file('src/java/org/archimedes/volume/config/stone/dense.xml')
    self.create_dir('src/java/org/archimedes/volume/config')
    self.create_file('src/java/org/archimedes/volume/config/metal/dense.xml')
    self.add_to_build_file('src/java/org/archimedes/volume/BUILD', dedent('''
      jvm_binary(name='unused')
    '''))
    self.add_to_build_file('src/java/org/archimedes/volume/BUILD', dedent('''
      jvm_app(name='volume',
        dependencies=[':unused'],
        bundles=[
          bundle(relative_to='config', fileset=['config/stone/dense.xml', 'config/metal/dense.xml'])
        ]
      )
    '''))
    app = self.target('src/java/org/archimedes/volume')
    for k in app.bundles[0].filemap.keys():
      if k.endswith('archimedes/volume/config/stone/dense.xml'):
        stonexml_key = k
    self.assertEquals(app.bundles[0].filemap[stonexml_key],
                      'stone/dense.xml')

  def test_multiple_bundles(self):
    self.create_dir('src/java/org/archimedes/volume/config/stone')
    self.create_file('src/java/org/archimedes/volume/config/stone/dense.xml')
    self.create_dir('src/java/org/archimedes/volume/config')
    self.create_file('src/java/org/archimedes/volume/config/metal/dense.xml')
    self.add_to_build_file('src/java/org/archimedes/volume/BUILD', dedent('''
      jvm_binary(name='unused')
    '''))
    self.add_to_build_file('src/java/org/archimedes/volume/BUILD', dedent('''
      jvm_app(name='volume',
        dependencies=[':unused'],
        bundles=[
          bundle(relative_to='config', fileset='config/stone/dense.xml')
        ]
      )

      jvm_app(name='bathtub',
        dependencies=[':unused'],
        bundles=[
          bundle(fileset='config/metal/dense.xml')
        ]
      )
    '''))

    app1 = self.target('src/java/org/archimedes/volume')
    self.assertEquals(1, len(app1.bundles))
    for k in app1.bundles[0].filemap.keys():
      if k.endswith('archimedes/volume/config/stone/dense.xml'):
        stonexml_key = k
    self.assertEquals(app1.bundles[0].filemap[stonexml_key], 'stone/dense.xml')

    app2 = self.target('src/java/org/archimedes/volume:bathtub')
    self.assertEquals(1, len(app2.bundles))
    for k in app2.bundles[0].filemap.keys():
      if k.endswith('archimedes/volume/config/metal/dense.xml'):
        stonexml_key = k
    self.assertEquals(app2.bundles[0].filemap[stonexml_key], 'config/metal/dense.xml')
