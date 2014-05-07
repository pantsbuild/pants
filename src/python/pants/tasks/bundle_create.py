# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import os
import shutil

from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir

from pants.base.build_environment import get_buildroot
from pants.fs import archive
from pants.java.jar import Manifest, open_jar
from pants.targets.jvm_binary import JvmApp, JvmBinary
from pants.tasks import TaskError
from pants.tasks.jvm_binary_task import JvmBinaryTask


class BundleCreate(JvmBinaryTask):

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("deployjar"), mkflag("deployjar", negate=True),
                            dest="bundle_create_deployjar", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Create a monolithic deploy jar containing the "
                                 "binaries' classfiles as well as all the classfiles they depend "
                                 "on transitively to go inside the bundle.")

    archive_flag = mkflag("archive")
    option_group.add_option(archive_flag, dest="bundle_create_archive",
                            type="choice", choices=list(archive.TYPE_NAMES),
                            help="[%%default] Create an archive from the bundle. "
                                 "Choose from %s" % sorted(archive.TYPE_NAMES))

    option_group.add_option(mkflag("archive-prefix"), mkflag("archive-prefix", negate=True),
                            dest="bundle_create_prefix", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%%default] Used in conjunction with %s this packs the archive "
                                 "with its basename as the path prefix." % archive_flag)

  def __init__(self, context, workdir):
    super(BundleCreate, self).__init__(context, workdir)

    self._outdir = context.config.getdefault('pants_distdir')
    self._prefix = context.options.bundle_create_prefix
    self._archiver_type = context.options.bundle_create_archive
    self._create_deployjar = context.options.bundle_create_deployjar

    self.context.products.require('jars')
    self.require_jar_dependencies()

  class App(object):
    """A uniform interface to an app."""

    @staticmethod
    def is_app(target):
      return isinstance(target, (JvmApp, JvmBinary))

    def __init__(self, target):
      assert self.is_app(target), "%s is not a valid app target" % target

      self.binary = target if isinstance(target, JvmBinary) else target.binary
      self.bundles = [] if isinstance(target, JvmBinary) else target.bundles
      self.basename = target.basename

  def execute(self, _):
    archiver = archive.archiver(self._archiver_type) if self._archiver_type else None
    for target in self.context.target_roots:
      for app in map(self.App, filter(self.App.is_app, target.resolve())):
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
    """Create a self-contained application bundle containing the target
    classes, dependencies and resources.
    """
    assert(isinstance(app, BundleCreate.App))

    bundle_dir = os.path.join(self._outdir, '%s-bundle' % app.basename)
    self.context.log.info('creating %s' % os.path.relpath(bundle_dir, get_buildroot()))

    safe_mkdir(bundle_dir, clean=True)

    classpath = OrderedSet()
    if not self._create_deployjar:
      lib_dir = os.path.join(bundle_dir, 'libs')
      os.mkdir(lib_dir)

      jarmap = self.context.products.get('jars')

      def add_jars(target):
        generated = jarmap.get(target)
        if generated:
          for base_dir, internal_jars in generated.items():
            for internal_jar in internal_jars:
              os.symlink(os.path.join(base_dir, internal_jar), os.path.join(lib_dir, internal_jar))
              classpath.add(internal_jar)

      app.binary.walk(add_jars, lambda t: t.is_internal and not t == app.binary)

      # Add external dependencies to the bundle.
      for basedir, external_jar in self.list_jar_dependencies(app.binary):
        path = os.path.join(basedir, external_jar)
        os.symlink(path, os.path.join(lib_dir, external_jar))
        classpath.add(external_jar)

    # TODO: There should probably be a separate 'binary_jars' product type,
    # so we can more easily distinguish binary jars (that contain all the classes of their
    # transitive deps) and per-target jars.
    for basedir, jars in self.context.products.get('jars').get(app.binary).items():
      if len(jars) != 1:
        raise TaskError('Expected 1 mapped binary for %s but found: %s' % (app.binary, jars))

      binary = jars[0]
      binary_jar = os.path.join(basedir, binary)
      bundle_jar = os.path.join(bundle_dir, '%s.jar' % app.binary.basename)

      with self._binary_jar(app.binary, binary_jar, bundle_jar) as jar:
        manifest = self.create_main_manifest(app.binary)
        if classpath:
          manifest.addentry(Manifest.CLASS_PATH,
                            ' '.join(os.path.join('libs', jar) for jar in classpath))
        jar.writestr(Manifest.PATH, manifest.contents())

    for bundle in app.bundles:
      for path, relpath in bundle.filemap.items():
        bundle_path = os.path.join(bundle_dir, relpath)
        safe_mkdir(os.path.dirname(bundle_path))
        os.symlink(path, bundle_path)

    return bundle_dir

  @contextmanager
  def _binary_jar(self, binary, binary_path, bundled_binary_path):
    if self._create_deployjar:
      with self.deployjar(binary, bundled_binary_path) as jar:
        yield jar
    else:
      shutil.copy(binary_path, bundled_binary_path)
      with open_jar(bundled_binary_path, 'a') as jar:
        yield jar
