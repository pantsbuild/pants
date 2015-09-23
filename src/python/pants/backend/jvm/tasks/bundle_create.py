# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from twitter.common.collections import OrderedSet

from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.jvm_binary_task import JvmBinaryTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.fs import archive
from pants.util.dirutil import safe_mkdir


class BundleCreate(JvmBinaryTask):

  @classmethod
  def register_options(cls, register):
    super(BundleCreate, cls).register_options(register)
    register('--deployjar', action='store_true', default=False,
             fingerprint=True,
             help="Expand 3rdparty jars into loose classfiles in the bundle's root dir. "
                  "If unset, the root will contain internal classfiles only, and 3rdparty jars "
                  "will go into the bundle's libs dir.")
    register('--archive', choices=list(archive.TYPE_NAMES),
             fingerprint=True,
             help='Create an archive of this type from the bundle.')
    register('--archive-prefix', action='store_true', default=False,
             fingerprint=True,
             help='If --archive is specified, use the target basename as the path prefix.')

  @classmethod
  def product_types(cls):
    return ['jvm_bundles']

  def __init__(self, *args, **kwargs):
    super(BundleCreate, self).__init__(*args, **kwargs)
    self._outdir = self.get_options().pants_distdir
    self._prefix = self.get_options().archive_prefix
    self._archiver_type = self.get_options().archive
    self._create_deployjar = self.get_options().deployjar

  class App(object):
    """A uniform interface to an app."""

    @staticmethod
    def is_app(target):
      return isinstance(target, (JvmApp, JvmBinary))

    def __init__(self, target):
      assert self.is_app(target), '{} is not a valid app target'.format(target)

      self.address = target.address
      self.binary = target if isinstance(target, JvmBinary) else target.binary
      self.bundles = [] if isinstance(target, JvmBinary) else target.payload.bundles
      self.basename = target.basename

  def execute(self):
    archiver = archive.archiver(self._archiver_type) if self._archiver_type else None
    for target in self.context.target_roots:
      for app in map(self.App, filter(self.App.is_app, [target])):
        basedir = self.bundle(app)
        # NB(Eric Ayers): Note that this product is not housed/controlled under .pants.d/  Since
        # the bundle is re-created every time, this shouldn't cause a problem, but if we ever
        # expect the product to be cached, a user running an 'rm' on the dist/ directory could
        # cause inconsistencies.
        jvm_bundles_product = self.context.products.get('jvm_bundles')
        jvm_bundles_product.add(target, os.path.dirname(basedir)).append(os.path.basename(basedir))
        if archiver:
          archivepath = archiver.create(
            basedir,
            self._outdir,
            app.basename,
            prefix=app.basename if self._prefix else None
          )
          self.context.log.info('created {}'.format(os.path.relpath(archivepath, get_buildroot())))

  class MissingJarError(TaskError):
    """Indicates an unexpected problem finding a jar that a bundle depends on."""

  def bundle(self, app):
    """Create a self-contained application bundle.

    The bundle will contain the target classes, dependencies and resources.
    """
    assert(isinstance(app, BundleCreate.App))

    def verbose_symlink(src, dst):
      if not os.path.exists(src):
        raise self.MissingJarError('Could not find {src} when attempting to link it into the '
                                   'bundle for {app_spec} at {dst}'
                                   .format(src=src,
                                           app_spec=app.address.reference(),
                                           dst=os.path.relpath(dst, get_buildroot())))
      try:
        os.symlink(src, dst)
      except OSError as e:
        self.context.log.error('Unable to create symlink: {0} -> {1}'.format(src, dst))
        raise e

    bundle_dir = os.path.join(self._outdir, '{}-bundle'.format(app.basename))
    self.context.log.info('creating {}'.format(os.path.relpath(bundle_dir, get_buildroot())))

    safe_mkdir(bundle_dir, clean=True)

    classpath = OrderedSet()
    # If creating a deployjar, we add the external dependencies to the bundle as
    # loose classes, and have no classpath. Otherwise we add the external dependencies
    # to the bundle as jars in a libs directory.
    if not self._create_deployjar:
      lib_dir = os.path.join(bundle_dir, 'libs')
      os.mkdir(lib_dir)

      jarmap = self.context.products.get('jars')

      def add_jars(target):
        generated = jarmap.get(target)
        if generated:
          for base_dir, internal_jars in generated.items():
            for internal_jar in internal_jars:
              verbose_symlink(os.path.join(base_dir, internal_jar),
                              os.path.join(lib_dir, internal_jar))
              classpath.add(internal_jar)

      app.binary.walk(add_jars, lambda t: t != app.binary)

      # Add external dependencies to the bundle.
      for path, coordinate in self.list_external_jar_dependencies(app.binary):
        external_jar = coordinate.artifact_filename
        destination = os.path.join(lib_dir, external_jar)
        verbose_symlink(path, destination)
        if app.binary.shading_rules:
          self.shade_jar(binary=app.binary, jar_id=coordinate, jar_path=destination)
        classpath.add(external_jar)

    bundle_jar = os.path.join(bundle_dir, '{}.jar'.format(app.binary.basename))

    with self.monolithic_jar(app.binary, bundle_jar,
                             with_external_deps=self._create_deployjar) as jar:
      self.add_main_manifest_entry(jar, app.binary)
      if classpath:
        jar.classpath([os.path.join('libs', jar) for jar in classpath])

    for bundle in app.bundles:
      for path, relpath in bundle.filemap.items():
        bundle_path = os.path.join(bundle_dir, relpath)
        if not os.path.exists(path):
          raise TaskError('Given path: {} does not exist in target {}'.format(
            path, app.address.spec))
        safe_mkdir(os.path.dirname(bundle_path))
        verbose_symlink(path, bundle_path)

    return bundle_dir
