# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from twitter.common.collections import OrderedSet

from pants.backend.jvm.targets.jvm_binary import JvmApp, JvmBinary
from pants.backend.jvm.tasks.jvm_binary_task import JvmBinaryTask
from pants.base.build_environment import get_buildroot
from pants.fs import archive
from pants.util.dirutil import safe_mkdir


class BundleCreate(JvmBinaryTask):
  @classmethod
  def register_options(cls, register):
    super(BundleCreate, cls).register_options(register)
    register('--deployjar', action='store_true', default=False,
             help="Expand 3rdparty jars into loose classfiles in the bundle's root dir. "
                  "If unset, the root will contain internal classfiles only, and 3rdparty jars "
                  "will go into the bundle's libs dir.")
    register('--archive', choices=list(archive.TYPE_NAMES),
             help='Create an archive of this type from the bundle.')
    register('--archive-prefix', action='store_true', default=False,
             help='If --archive is specified, use the target basename as the path prefix.')

  def __init__(self, *args, **kwargs):
    super(BundleCreate, self).__init__(*args, **kwargs)
    self._outdir = self.context.config.getdefault('pants_distdir')
    self._prefix = self.get_options().archive_prefix
    self._archiver_type = self.get_options().archive
    self._create_deployjar = self.get_options().deployjar

  class App(object):
    """A uniform interface to an app."""

    @staticmethod
    def is_app(target):
      return isinstance(target, (JvmApp, JvmBinary))

    def __init__(self, target):
      assert self.is_app(target), '%s is not a valid app target' % target

      self.binary = target if isinstance(target, JvmBinary) else target.binary
      self.bundles = [] if isinstance(target, JvmBinary) else target.payload.bundles
      self.basename = target.basename

  def execute(self):
    archiver = archive.archiver(self._archiver_type) if self._archiver_type else None
    for target in self.context.target_roots:
      for app in map(self.App, filter(self.App.is_app, [target])):
        basedir = self.bundle(app)
        if archiver:
          archivepath = archiver.create(
            basedir,
            self._outdir,
            app.basename,
            prefix=app.basename if self._prefix else None
          )
          self.context.log.info('created %s' % os.path.relpath(archivepath, get_buildroot()))

  def bundle(self, app):
    """Create a self-contained application bundle.

    The bundle will contain the target classes, dependencies and resources.
    """
    assert(isinstance(app, BundleCreate.App))

    def verbose_symlink(src, dst):
      try:
        os.symlink(src, dst)
      except OSError as e:
        self.context.log.error("Unable to create symlink: {0} -> {1}".format(src, dst))
        raise e

    bundle_dir = os.path.join(self._outdir, '%s-bundle' % app.basename)
    self.context.log.info('creating %s' % os.path.relpath(bundle_dir, get_buildroot()))

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
              verbose_symlink(os.path.join(base_dir, internal_jar), os.path.join(lib_dir, internal_jar))
              classpath.add(internal_jar)

      app.binary.walk(add_jars, lambda t: t != app.binary)

      # Add external dependencies to the bundle.
      for basedir, external_jar in self.list_external_jar_dependencies(app.binary):
        path = os.path.join(basedir, external_jar)
        verbose_symlink(path, os.path.join(lib_dir, external_jar))
        classpath.add(external_jar)

    bundle_jar = os.path.join(bundle_dir, '%s.jar' % app.binary.basename)

    with self.monolithic_jar(app.binary, bundle_jar,
                             with_external_deps=self._create_deployjar) as jar:
      self.add_main_manifest_entry(jar, app.binary)
      if classpath:
        jar.classpath([os.path.join('libs', jar) for jar in classpath])

    for bundle in app.bundles:
      for path, relpath in bundle.filemap.items():
        bundle_path = os.path.join(bundle_dir, relpath)
        safe_mkdir(os.path.dirname(bundle_path))
        verbose_symlink(path, bundle_path)

    return bundle_dir
