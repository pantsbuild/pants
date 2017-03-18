# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from twitter.common.collections import OrderedSet

from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.jvm_binary_task import JvmBinaryTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.target_scopes import Scopes
from pants.fs import archive
from pants.util.dirutil import absolute_symlink, safe_mkdir, safe_mkdir_for
from pants.util.fileutil import atomic_copy
from pants.util.objects import datatype


class BundleCreate(JvmBinaryTask):
  """
  :API: public
  """

  # Directory for both internal and external libraries.
  LIBS_DIR = 'libs'
  _target_closure_kwargs = dict(include_scopes=Scopes.JVM_RUNTIME_SCOPES, respect_intransitive=True)

  @classmethod
  def register_options(cls, register):
    super(BundleCreate, cls).register_options(register)
    register('--deployjar', advanced=True, type=bool,
             fingerprint=True,
             help="Pack all 3rdparty and internal jar classfiles into a single deployjar in "
                  "the bundle's root dir. If unset, all jars will go into the bundle's libs "
                  "directory, the root will only contain a synthetic jar with its manifest's "
                  "Class-Path set to those jars. This option is also defined in jvm_app target. "
                  "Precedence is CLI option > target option > pants.ini option.")
    register('--archive', advanced=True, choices=list(archive.TYPE_NAMES),
             fingerprint=True,
             help='Create an archive of this type from the bundle. '
                  'This option is also defined in jvm_app target. '
                  'Precedence is CLI option > target option > pants.ini option.')
    # `target.id` ensures global uniqueness, this flag is provided primarily for
    # backward compatibility.
    register('--use-basename-prefix', advanced=True, type=bool,
             help='Use target basename to prefix bundle folder or archive; otherwise a unique '
                  'identifier derived from target will be used.')

  @classmethod
  def implementation_version(cls):
    return super(BundleCreate, cls).implementation_version() + [('BundleCreate', 1)]

  @classmethod
  def prepare(cls, options, round_manager):
    super(BundleCreate, cls).prepare(options, round_manager)
    round_manager.require_data('consolidated_classpath')

  @classmethod
  def product_types(cls):
    return ['jvm_archives', 'jvm_bundles', 'deployable_archives']

  class App(datatype('App', ['address', 'binary', 'bundles', 'id', 'deployjar', 'archive', 'target'])):
    """A uniform interface to an app."""

    @staticmethod
    def is_app(target):
      return isinstance(target, (JvmApp, JvmBinary))

    @classmethod
    def create_app(cls, target, deployjar, archive):
      return cls(target.address,
                 target if isinstance(target, JvmBinary) else target.binary,
                 [] if isinstance(target, JvmBinary) else target.payload.bundles,
                 target.id,
                 deployjar,
                 archive,
                 target)

  @property
  def cache_target_dirs(self):
    return True

  # TODO (Benjy): The following CLI > target > config logic
  # should be implemented in the options system.
  # https://github.com/pantsbuild/pants/issues/3538
  def _resolved_option(self, target, key):
    """Get value for option "key".

    Resolution precedence is CLI option > target option > pants.ini option.
    """
    option_value = self.get_options().get(key)
    if not isinstance(target, JvmApp) or self.get_options().is_flagged(key):
      return option_value
    v = target.payload.get_field_value(key, None)
    return option_value if v is None else v

  def _store_results(self, vt, bundle_dir, archivepath, app):
    """Store a copy of the bundle and archive from the results dir in dist."""
    # TODO (from mateor) move distdir management somewhere more general purpose.
    dist_dir = self.get_options().pants_distdir
    name = vt.target.basename if self.get_options().use_basename_prefix else app.id
    bundle_copy = os.path.join(dist_dir, '{}-bundle'.format(name))
    absolute_symlink(bundle_dir, bundle_copy)
    self.context.log.info(
      'created bundle copy {}'.format(os.path.relpath(bundle_copy, get_buildroot())))

    if archivepath:
      ext = archive.archive_extensions.get(app.archive, app.archive)
      archive_copy = os.path.join(dist_dir,'{}.{}'.format(name, ext))
      safe_mkdir_for(archive_copy)  # Ensure parent dir exists
      atomic_copy(archivepath, archive_copy)
      self.context.log.info(
        'created archive copy {}'.format(os.path.relpath(archive_copy, get_buildroot())))

  def _add_product(self, deployable_archive, app, path):
    deployable_archive.add(
      app.target, os.path.dirname(path)).append(os.path.basename(path))
    self.context.log.debug('created {}'.format(os.path.relpath(path, get_buildroot())))

  def execute(self):
    targets_to_bundle = self.context.targets(self.App.is_app)

    if self.get_options().use_basename_prefix:
      self.check_basename_conflicts([t for t in self.context.target_roots if t in targets_to_bundle])

    with self.invalidated(targets_to_bundle, invalidate_dependents=True) as invalidation_check:
      jvm_bundles_product = self.context.products.get('jvm_bundles')
      bundle_archive_product = self.context.products.get('deployable_archives')
      jvm_archive_product = self.context.products.get('jvm_archives')

      for vt in invalidation_check.all_vts:
        app = self.App.create_app(vt.target,
                                  self._resolved_option(vt.target, 'deployjar'),
                                  self._resolved_option(vt.target, 'archive'))
        archiver = archive.archiver(app.archive) if app.archive else None

        bundle_dir = self._get_bundle_dir(app, vt.results_dir)
        ext = archive.archive_extensions.get(app.archive, app.archive)
        filename = '{}.{}'.format(app.id, ext)
        archive_path = os.path.join(vt.results_dir, filename) if app.archive else ''
        if not vt.valid:
          self.bundle(app, vt.results_dir)
          if app.archive:
            archiver.create(bundle_dir, vt.results_dir, app.id)

        self._add_product(jvm_bundles_product, app, bundle_dir)
        if archiver:
          self._add_product(bundle_archive_product, app, archive_path)
          self._add_product(jvm_archive_product, app, archive_path)

        # For root targets, create symlink.
        if vt.target in self.context.target_roots:
          self._store_results(vt, bundle_dir, archive_path, app)

  class BasenameConflictError(TaskError):
    """Indicates the same basename is used by two targets."""

  def _get_bundle_dir(self, app, results_dir):
    return os.path.join(results_dir, '{}-bundle'.format(app.id))

  def bundle(self, app, results_dir):
    """Create a self-contained application bundle.

    The bundle will contain the target classes, dependencies and resources.
    """
    assert(isinstance(app, BundleCreate.App))

    bundle_dir = self._get_bundle_dir(app, results_dir)
    self.context.log.debug('creating {}'.format(os.path.relpath(bundle_dir, get_buildroot())))

    safe_mkdir(bundle_dir, clean=True)

    classpath = OrderedSet()

    # Create symlinks for both internal and external dependencies under `lib_dir`. This is
    # only needed when not creating a deployjar
    lib_dir = os.path.join(bundle_dir, self.LIBS_DIR)
    if not app.deployjar:
      os.mkdir(lib_dir)
      consolidated_classpath = self.context.products.get_data('consolidated_classpath')
      classpath.update(ClasspathProducts.create_canonical_classpath(
        consolidated_classpath,
        app.target.closure(bfs=True, **self._target_closure_kwargs),
        lib_dir,
        internal_classpath_only=False,
        excludes=app.binary.deploy_excludes,
      ))

    bundle_jar = os.path.join(bundle_dir, '{}.jar'.format(app.binary.basename))
    with self.monolithic_jar(app.binary, bundle_jar,
                             manifest_classpath=classpath) as jar:
      self.add_main_manifest_entry(jar, app.binary)

      # Make classpath complete by adding the monolithic jar.
      classpath.update([jar.path])

    if app.binary.shading_rules:
      for jar_path in classpath:
        # In case `jar_path` is a symlink, this is still safe, shaded jar will overwrite jar_path,
        # original file `jar_path` linked to remains untouched.
        # TODO run in parallel to speed up
        self.shade_jar(shading_rules=app.binary.shading_rules, jar_path=jar_path)

    for bundle_counter, bundle in enumerate(app.bundles):
      fileset_empty = True
      for path, relpath in bundle.filemap.items():
        bundle_path = os.path.join(bundle_dir, relpath)
        if os.path.exists(path):
          safe_mkdir(os.path.dirname(bundle_path))
          os.symlink(path, bundle_path)
          fileset_empty = False

      if fileset_empty:
        raise TaskError('In target {}, bundle index {} of "bundles" field does not match any files.'.format(
          app.address.spec, bundle_counter))

    return bundle_dir

  def check_basename_conflicts(self, targets):
    """Apps' basenames are used as bundle directory names. Ensure they are all unique."""

    basename_seen = {}
    for target in targets:
      if target.basename in basename_seen:
        raise self.BasenameConflictError('Basename must be unique, found two targets use '
                                         "the same basename: {}'\n\t{} and \n\t{}"
                                         .format(target.basename,
                                                 basename_seen[target.basename].address.spec,
                                                 target.address.spec))
      basename_seen[target.basename] = target
