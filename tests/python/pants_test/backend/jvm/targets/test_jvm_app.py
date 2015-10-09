# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.backend.core.wrapped_globs import Globs
from pants.backend.jvm.targets.jvm_app import Bundle, DirectoryReMapper, JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.address import Address
from pants_test.base_test import BaseTest


class JvmAppTest(BaseTest):

  def test_simple(self):
    binary_target = self.make_target(':foo-binary', JvmBinary, main='com.example.Foo')
    app_target = self.make_target(':foo', JvmApp, basename='foo-app', binary=':foo-binary')

    self.assertEquals('foo-app', app_target.payload.basename)
    self.assertEquals('foo-app', app_target.basename)
    self.assertEquals(binary_target, app_target.binary)
    self.assertEquals([':foo-binary'], list(app_target.traversable_dependency_specs))

  def test_bad_basename(self):
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'Invalid target JvmApp.* basename must not equal name.'):
      self.make_target(':foo', JvmApp, basename='foo')

  def create_app(self, rel_path, name=None, **kwargs):
    self.create_file(os.path.join(rel_path, 'config/densities.xml'))
    return self.make_target(Address(rel_path, name or 'app').spec,
                            JvmApp,
                            bundles=[Bundle(rel_path, fileset='config/densities.xml')],
                            **kwargs)

  def test_binary_via_binary(self):
    bin = self.make_target('src/java/org/archimedes/buoyancy:bin', JvmBinary)
    app = self.create_app('src/java/org/archimedes/buoyancy', binary=':bin')
    self.assertEquals(app.binary, bin)

  def test_binary_via_dependencies(self):
    bin = self.make_target('src/java/org/archimedes/buoyancy:bin', JvmBinary)
    app = self.create_app('src/java/org/archimedes/buoyancy', dependencies=[bin])
    self.assertEquals(app.binary, bin)

  def test_degenerate_binaries(self):
    bin = self.make_target('src/java/org/archimedes/buoyancy:bin', JvmBinary)
    app = self.create_app('src/java/org/archimedes/buoyancy', binary=':bin', dependencies=[bin])
    self.assertEquals(app.binary, bin)

  def test_no_binary(self):
    app = self.create_app('src/java/org/archimedes/buoyancy')
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'Invalid target JvmApp.*src/java/org/archimedes/buoyancy:app\).*'
                                 r' A JvmApp must define exactly one'):
      app.binary

  def test_too_many_binaries_mixed(self):
    self.make_target('src/java/org/archimedes/buoyancy:bin', JvmBinary)
    bin2 = self.make_target('src/java/org/archimedes/buoyancy:bin2', JvmBinary)
    app = self.create_app('src/java/org/archimedes/buoyancy', binary=':bin', dependencies=[bin2])
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'Invalid target JvmApp.*src/java/org/archimedes/buoyancy:app\).*'
                                 r' A JvmApp must define exactly one'):
      app.binary

  def test_too_many_binaries_via_deps(self):
    bin = self.make_target('src/java/org/archimedes/buoyancy:bin', JvmBinary)
    bin2 = self.make_target('src/java/org/archimedes/buoyancy:bin2', JvmBinary)
    app = self.create_app('src/java/org/archimedes/buoyancy', dependencies=[bin, bin2])
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'Invalid target JvmApp.*src/java/org/archimedes/buoyancy:app\).*'
                                 r' A JvmApp must define exactly one'):
      app.binary

  def test_not_a_binary(self):
    self.make_target('src/java/org/archimedes/buoyancy:bin', JvmBinary)
    self.create_app('src/java/org/archimedes/buoyancy', name='app', binary=':bin')
    app = self.create_app('src/java/org/archimedes/buoyancy', name='app2', binary=':app')
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'Invalid target JvmApp.*src/java/org/archimedes/buoyancy:app2\).*'
                                 r' Expected JvmApp binary dependency'):
      app.binary


class BundleTest(BaseTest):

  def test_bundle_filemap_dest_bypath(self):
    spec_path = 'src/java/org/archimedes/buoyancy'
    densities = self.create_file(os.path.join(spec_path, 'config/densities.xml'))
    unused = self.make_target(Address(spec_path, 'unused').spec, JvmBinary)

    app = self.make_target(spec_path,
                           JvmApp,
                           dependencies=[unused],
                           bundles=[Bundle(spec_path, fileset='config/densities.xml')])

    self.assertEqual(1, len(app.bundles))
    # after one big refactor, ../../../../../ snuck into this path:
    self.assertEqual({densities: 'config/densities.xml'}, app.bundles[0].filemap)

  def test_bundle_filemap_dest_byglobs(self):
    spec_path = 'src/java/org/archimedes/tub'
    one = self.create_file(os.path.join(spec_path, 'config/one.xml'))
    two = self.create_file(os.path.join(spec_path, 'config/two.xml'))
    unused = self.make_target(Address(spec_path, 'unused').spec, JvmBinary)

    globs = Globs(spec_path)
    app = self.make_target(spec_path,
                           JvmApp,
                           dependencies=[unused],
                           bundles=[Bundle(spec_path, fileset=globs('config/*.xml'))])

    self.assertEqual(1, len(app.bundles))
    self.assertEqual({one: 'config/one.xml', two: 'config/two.xml'}, app.bundles[0].filemap)

  def test_bundle_filemap_dest_relative(self):
    spec_path = 'src/java/org/archimedes/crown'
    five = self.create_file(os.path.join(spec_path, 'gold/config/five.xml'))
    unused = self.make_target(Address(spec_path, 'unused').spec, JvmBinary)

    app = self.make_target(spec_path,
                           JvmApp,
                           dependencies=[unused],
                           bundles=[Bundle(spec_path,
                                           relative_to='gold',
                                           fileset='gold/config/five.xml')])

    self.assertEqual(1, len(app.bundles))
    self.assertEqual({five: 'config/five.xml'}, app.bundles[0].filemap)

  def test_bundle_filemap_dest_remap(self):
    spec_path = 'src/java/org/archimedes/crown'
    one = self.create_file(os.path.join(spec_path, 'config/one.xml'))
    unused = self.make_target(Address(spec_path, 'unused').spec, JvmBinary)

    mapper = DirectoryReMapper(os.path.join(spec_path, 'config'), 'gold/config')
    app = self.make_target(spec_path,
                           JvmApp,
                           dependencies=[unused],
                           bundles=[Bundle(spec_path, mapper=mapper, fileset='config/one.xml')])

    self.assertEqual(1, len(app.bundles))
    self.assertEqual({one: 'gold/config/one.xml'}, app.bundles[0].filemap)

  def test_bundle_filemap_remap_base_not_exists(self):
    # Create directly
    with self.assertRaises(DirectoryReMapper.BaseNotExistsError):
      DirectoryReMapper("dummy/src/java/org/archimedes/crown/missing", "dummy")

  def test_bundle_add(self):
    spec_path = 'src/java/org/archimedes/volume'
    stone_dense = self.create_file(os.path.join(spec_path, 'config/stone/dense.xml'))
    metal_dense = self.create_file(os.path.join(spec_path, 'config/metal/dense.xml'))
    unused = self.make_target(Address(spec_path, 'unused').spec, JvmBinary)

    bundle = Bundle(spec_path,
                    relative_to='config',
                    fileset=['config/stone/dense.xml', 'config/metal/dense.xml'])
    app = self.make_target(spec_path, JvmApp, dependencies=[unused], bundles=[bundle])

    self.assertEqual(1, len(app.bundles))
    self.assertEqual({stone_dense: 'stone/dense.xml', metal_dense: 'metal/dense.xml'},
                     app.bundles[0].filemap)

  def test_multiple_bundles(self):
    spec_path = 'src/java/org/archimedes/volume'
    stone_dense = self.create_file(os.path.join(spec_path, 'config/stone/dense.xml'))
    metal_dense = self.create_file(os.path.join(spec_path, 'config/metal/dense.xml'))
    unused = self.make_target(Address(spec_path, 'unused').spec, JvmBinary)

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

    app1 = self.make_target(Address(spec_path, 'app1').spec,
                            JvmApp,
                            dependencies=[unused],
                            bundles=[Bundle(spec_path,
                                            relative_to='config',
                                            fileset='config/stone/dense.xml')])

    app2 = self.make_target(Address(spec_path, 'app2').spec,
                            JvmApp,
                            dependencies=[unused],
                            bundles=[Bundle(spec_path, fileset='config/metal/dense.xml')])

    self.assertEqual(1, len(app1.bundles))
    self.assertEqual({stone_dense: 'stone/dense.xml'}, app1.bundles[0].filemap)

    self.assertEqual(1, len(app2.bundles))
    self.assertEqual({metal_dense: 'config/metal/dense.xml'}, app2.bundles[0].filemap)

  def test_globs_relative_to_build_root(self):
    spec_path = 'y'
    unused = self.make_target(spec_path, JvmBinary)

    globs = Globs(spec_path)
    app = self.make_target('y:app',
                           JvmApp,
                           dependencies=[unused],
                           bundles=[
                             Bundle(spec_path, relative_to="config", fileset=globs("z/*")),
                             Bundle(spec_path, relative_to="config", fileset=['a/b'])
                           ])

    self.assertEquals(['a/b', 'y/z/*'], sorted(app.globs_relative_to_buildroot()['globs']))
