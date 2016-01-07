# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from twitter.common.collections import OrderedSet

from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.jvm_binary_task import JvmBinaryTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.build_graph import BuildGraph
from pants.fs import archive
from pants.fs.archive import JAR
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir


class BundleCreate(JvmBinaryTask):

  # Directory for 3rdparty libraries.
  LIBS_DIR = 'libs'
  # Directory for internal libraries.
  INTERNAL_LIBS_DIR = 'internal-libs'

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

    # NB(peiyu): performance hack to convert loose directories in classpath into jars. This is
    # more efficient than loading them as individual files.
    runtime_classpath = self.context.products.get_data('runtime_classpath')
    self.consolidate_classpath(self.context.targets(), runtime_classpath)

    for target in self.context.targets():
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
      lib_dir = os.path.join(bundle_dir, self.LIBS_DIR)
      os.mkdir(lib_dir)

      # Add external dependencies to the bundle.
      for path, coordinate in self.list_external_jar_dependencies(app.binary):
        external_jar = coordinate.artifact_filename
        destination = os.path.join(lib_dir, external_jar)
        verbose_symlink(path, destination)
        classpath.add(destination)

    bundle_jar = os.path.join(bundle_dir, '{}.jar'.format(app.binary.basename))

    canonical_classpath_base_dir = None
    if not self._create_deployjar:
      canonical_classpath_base_dir = os.path.join(bundle_dir, self.INTERNAL_LIBS_DIR)
    with self.monolithic_jar(app.binary, bundle_jar,
                             canonical_classpath_base_dir=canonical_classpath_base_dir) as jar:
      self.add_main_manifest_entry(jar, app.binary)
      if classpath:
        # append external dependencies to monolithic jar's classpath,
        # eventually will be saved in the Class-Path entry of its Manifest.
        jar.append_classpath(classpath)

      # Make classpath complete by adding internal classpath and monolithic jar.
      classpath.update(jar.classpath + [jar.path])

    if app.binary.shading_rules:
      for jar_path in classpath:
        # In case `jar_path` is a symlink, this is still safe, shaded jar will overwrite jar_path,
        # original file `jar_path` linked to remains untouched.
        # TODO run in parallel to speed up
        self.shade_jar(shading_rules=app.binary.shading_rules, jar_path=jar_path)

    for bundle in app.bundles:
      for path, relpath in bundle.filemap.items():
        bundle_path = os.path.join(bundle_dir, relpath)
        if not os.path.exists(path):
          raise TaskError('Given path: {} does not exist in target {}'.format(
            path, app.address.spec))
        safe_mkdir(os.path.dirname(bundle_path))
        verbose_symlink(path, bundle_path)

    return bundle_dir

  def consolidate_classpath(self, targets, classpath_products):
    """Convert loose directories in classpath_products into jars.

    TODO(peiyu): enable artifact caching to take advantage of caching as well saving to
    the provided target-specific directories.
    """
    def jardir(entry):
      """Jar up the contents of the given ClasspathEntry and return a unique jar path."""
      root = entry.path
      with temporary_dir(root_dir=self.workdir, cleanup=False) as destdir:
        jarpath = JAR.create(root, destdir, 'output')
      return jarpath

    safe_mkdir(self.workdir)
    for target in targets:
      entries = classpath_products.get_internal_classpath_entries_for_targets([target])
      for conf, entry in entries:
        if ClasspathUtil.is_dir(entry.path):
          classpath_products.remove_for_target(target, [(conf, entry.path)])
          classpath_products.add_for_target(target, [(conf, jardir(entry))])
