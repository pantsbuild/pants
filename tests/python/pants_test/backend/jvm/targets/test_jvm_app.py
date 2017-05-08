# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.backend.jvm.targets.jvm_app import Bundle, DirectoryReMapper, JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.base.exceptions import TargetDefinitionException
from pants.base.parse_context import ParseContext
from pants.build_graph.address import Address
from pants.source.wrapped_globs import Globs
from pants_test.base_test import BaseTest


def _bundle(rel_path):
  pc = ParseContext(rel_path=rel_path, type_aliases={})
  return Bundle(pc)


def _globs(rel_path):
  pc = ParseContext(rel_path=rel_path, type_aliases={})
  return Globs(pc)


class JvmAppTest(BaseTest):
  def test_simple(self):
    binary_target = self.make_target(':foo-binary', JvmBinary, main='com.example.Foo')
    app_target = self.make_target(':foo', JvmApp, basename='foo-app', binary=':foo-binary')

    self.assertEquals('foo-app', app_target.payload.basename)
    self.assertEquals('foo-app', app_target.basename)
    self.assertEquals(binary_target, app_target.binary)
    self.assertEquals([':foo-binary'], list(app_target.compute_dependency_specs(payload=app_target.payload)))

  def test_jvmapp_bundle_payload_fields(self):
    app_target = self.make_target(':foo_payload',
                                  JvmApp,
                                  basename='foo-payload-app',
                                  archive='zip')

    self.assertEquals('foo-payload-app', app_target.payload.basename)
    self.assertIsNone(app_target.payload.deployjar)
    self.assertEquals('zip', app_target.payload.archive)

  def test_bad_basename(self):
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'Invalid target JvmApp.* basename must not equal name.'):
      self.make_target(':foo', JvmApp, basename='foo')

  def create_app(self, rel_path, name=None, **kwargs):
    self.create_file(os.path.join(rel_path, 'config/densities.xml'))
    return self.make_target(Address(rel_path, name or 'app').spec,
                            JvmApp,
                            bundles=[_bundle(rel_path)(fileset='config/densities.xml')],
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
                           bundles=[_bundle(spec_path)(fileset='config/densities.xml')])

    self.assertEqual(1, len(app.bundles))
    # after one big refactor, ../../../../../ snuck into this path:
    self.assertEqual({densities: 'config/densities.xml'}, app.bundles[0].filemap)

  def test_bundle_filemap_dest_byglobs(self):
    spec_path = 'src/java/org/archimedes/tub'
    one = self.create_file(os.path.join(spec_path, 'config/one.xml'))
    two = self.create_file(os.path.join(spec_path, 'config/two.xml'))
    unused = self.make_target(Address(spec_path, 'unused').spec, JvmBinary)

    globs = _globs(spec_path)
    app = self.make_target(spec_path,
                           JvmApp,
                           dependencies=[unused],
                           bundles=[_bundle(spec_path)(fileset=globs('config/*.xml'))])

    self.assertEqual(1, len(app.bundles))
    self.assertEqual({one: 'config/one.xml', two: 'config/two.xml'}, app.bundles[0].filemap)

  def test_bundle_filemap_dest_relative(self):
    spec_path = 'src/java/org/archimedes/crown'
    five = self.create_file(os.path.join(spec_path, 'gold/config/five.xml'))
    unused = self.make_target(Address(spec_path, 'unused').spec, JvmBinary)

    app = self.make_target(spec_path,
                           JvmApp,
                           dependencies=[unused],
                           bundles=[_bundle(spec_path)(relative_to='gold',
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
                           bundles=[_bundle(spec_path)(mapper=mapper, fileset='config/one.xml')])

    self.assertEqual(1, len(app.bundles))
    self.assertEqual({one: 'gold/config/one.xml'}, app.bundles[0].filemap)

  def test_bundle_filemap_remap_base_not_exists(self):
    # Create directly
    with self.assertRaises(DirectoryReMapper.NonexistentBaseError):
      DirectoryReMapper("dummy/src/java/org/archimedes/crown/missing", "dummy")

  def test_bundle_add(self):
    spec_path = 'src/java/org/archimedes/volume'
    stone_dense = self.create_file(os.path.join(spec_path, 'config/stone/dense.xml'))
    metal_dense = self.create_file(os.path.join(spec_path, 'config/metal/dense.xml'))
    unused = self.make_target(Address(spec_path, 'unused').spec, JvmBinary)

    bundle = _bundle(spec_path)(relative_to='config',
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

    self.add_to_build_file('src/java/org/archimedes/volume/BUILD', dedent("""
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
    """))

    app1 = self.make_target(Address(spec_path, 'app1').spec,
                            JvmApp,
                            dependencies=[unused],
                            bundles=[_bundle(spec_path)(relative_to='config',
                                                        fileset='config/stone/dense.xml')])

    app2 = self.make_target(Address(spec_path, 'app2').spec,
                            JvmApp,
                            dependencies=[unused],
                            bundles=[_bundle(spec_path)(fileset='config/metal/dense.xml')])

    self.assertEqual(1, len(app1.bundles))
    self.assertEqual({stone_dense: 'stone/dense.xml'}, app1.bundles[0].filemap)

    self.assertEqual(1, len(app2.bundles))
    self.assertEqual({metal_dense: 'config/metal/dense.xml'}, app2.bundles[0].filemap)

  def test_globs_relative_to_build_root(self):
    spec_path = 'y'
    unused = self.make_target(spec_path, JvmBinary)

    globs = _globs(spec_path)
    app = self.make_target('y:app',
                           JvmApp,
                           dependencies=[unused],
                           bundles=[
                             _bundle(spec_path)(fileset=globs("z/*")),
                             _bundle(spec_path)(fileset=['a/b'])
                           ])

    self.assertEquals(['y/a/b', 'y/z/*'], sorted(app.globs_relative_to_buildroot()['globs']))

  def test_list_of_globs_fails(self):
    # It's not allowed according to the docs, and will behave badly.

    spec_path = 'y'
    globs = _globs(spec_path)
    with self.assertRaises(ValueError):
      _bundle(spec_path)(fileset=[globs("z/*")])

  def test_jvmapp_fingerprinting(self):
    spec_path = 'y'
    globs = _globs(spec_path)
    self.create_file(os.path.join(spec_path, 'one.xml'))
    self.create_file(os.path.join(spec_path, 'config/two.xml'))

    def calc_fingerprint():
      # Globs are eagerly, therefore we need to recreate target to recalculate fingerprint.
      self.reset_build_graph()
      app = self.make_target('y:app',
                           JvmApp,
                           dependencies=[],
                           bundles=[
                             _bundle(spec_path)(fileset=globs("*"))
                           ])
      return app.payload.fingerprint()

    fingerprint_before = calc_fingerprint()
    os.mkdir(os.path.join(self.build_root, spec_path, 'folder_one'))
    self.assertEqual(fingerprint_before, calc_fingerprint())
    self.create_file(os.path.join(spec_path, 'three.xml'))
    self.assertNotEqual(fingerprint_before, calc_fingerprint())

  def test_jvmapp_fingerprinting_with_non_existing_files(self):
    spec_path = 'y'
    def calc_fingerprint():
      self.reset_build_graph()
      return self.make_target('y:app',
                              JvmApp,
                              dependencies=[],
                              bundles=[
                                _bundle(spec_path)(fileset=['one.xml'])
                              ]).payload.fingerprint()

    fingerprint_non_existing_file = calc_fingerprint()
    self.create_file(os.path.join(spec_path, 'one.xml'))
    fingerprint_empty_file = calc_fingerprint()
    self.create_file(os.path.join(spec_path, 'one.xml'), contents='some content')
    fingerprint_file_with_content = calc_fingerprint()

    self.assertNotEqual(fingerprint_empty_file, fingerprint_non_existing_file)
    self.assertNotEqual(fingerprint_empty_file, fingerprint_file_with_content)
    self.assertNotEqual(fingerprint_file_with_content, fingerprint_empty_file)

  def test_rel_path_with_glob_fails(self):
    # Globs are treated as eager, so rel_path doesn't affect their meaning.
    # The effect of this is likely to be confusing, so disallow it.

    spec_path = 'y'
    self.create_file(os.path.join(spec_path, 'z', 'somefile'))
    globs = _globs(spec_path)
    with self.assertRaises(ValueError) as cm:
      _bundle(spec_path)(rel_path="config", fileset=globs('z/*'))
    self.assertIn("Must not use a glob for 'fileset' with 'rel_path'.", str(cm.exception))

  def test_allow_globs_when_rel_root_matches_rel_path(self):
    # If a glob has the same rel_root as the rel_path, then
    # it will correctly pick up the right files.
    # We don't allow BUILD files to have declarations with this state.
    # But filesets can be created this way via macros or pants internals.

    self.create_file(os.path.join('y', 'z', 'somefile'))
    bundle = _bundle('y')(rel_path="y/z", fileset=_globs('y/z')('*'))

    self.assertEquals({'globs': [u'y/z/*']}, bundle.fileset.filespec)

  def test_rel_path_overrides_context_rel_path_for_explicit_path(self):
    spec_path = 'y'
    unused = self.make_target(spec_path, JvmBinary)

    app = self.make_target('y:app',
                           JvmApp,
                           dependencies=[unused],
                           bundles=[
                             _bundle(spec_path)(rel_path="config", fileset=['a/b'])
                           ])
    self.assertEqual({os.path.join(self.build_root, 'config/a/b'): 'a/b'}, app.bundles[0].filemap)
    self.assertEquals(['config/a/b'], sorted(app.globs_relative_to_buildroot()['globs']))
