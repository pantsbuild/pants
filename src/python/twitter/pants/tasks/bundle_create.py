# ==================================================================================================
# Copyright 2012 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import os

from zipfile import ZIP_DEFLATED

from twitter.common.collections import OrderedSet
from twitter.common.contextutil import open_zip
from twitter.common.dirutil import safe_mkdir

from twitter.pants.base.build_environment import get_buildroot
from twitter.pants.fs import archive
from twitter.pants.java.jar import Manifest
from twitter.pants.targets import JvmApp, JvmBinary
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.jvm_binary_task import JvmBinaryTask


class BundleCreate(JvmBinaryTask):

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    JvmBinaryTask.setup_parser(option_group, args, mkflag)

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

  def __init__(self, context):
    JvmBinaryTask.__init__(self, context)

    self.outdir = (
      context.options.jvm_binary_create_outdir or
      context.config.get('bundle-create', 'outdir',
                         default=context.config.getdefault('pants_distdir'))
    )

    self.prefix = context.options.bundle_create_prefix

    def fill_archiver_type():
      self.archiver_type = context.options.bundle_create_archive
      # If no option specified, check if anyone is requiring it
      if not self.archiver_type:
        for archive_type in archive.TYPE_NAMES:
          if context.products.isrequired(archive_type):
            self.archiver_type = archive_type

    fill_archiver_type()
    self.deployjar = context.options.jvm_binary_create_deployjar
    if not self.deployjar:
      self.context.products.require('jars', predicate=self.is_binary)
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
    archiver = archive.archiver(self.archiver_type) if self.archiver_type else None
    for target in self.context.target_roots:
      for app in map(self.App, filter(self.App.is_app, target.resolve())):
        basedir = self.bundle(app)
        if archiver:
          archivemap = self.context.products.get(self.archiver_type)
          archivepath = archiver.create(
            basedir,
            self.outdir,
            app.basename,
            prefix=app.basename if self.prefix else None
          )
          archivemap.add(app, self.outdir, [archivepath])
          self.context.log.info('created %s' % os.path.relpath(archivepath, get_buildroot()))

  def bundle(self, app):
    """Create a self-contained application bundle containing the target
    classes, dependencies and resources.
    """
    assert(isinstance(app, BundleCreate.App))

    bundledir = os.path.join(self.outdir, '%s-bundle' % app.basename)
    self.context.log.info('creating %s' % os.path.relpath(bundledir, get_buildroot()))

    safe_mkdir(bundledir, clean=True)

    classpath = OrderedSet()
    if not self.deployjar:
      libdir = os.path.join(bundledir, 'libs')
      os.mkdir(libdir)

      # Add internal dependencies to the bundle.
      def add_jars(target):
        target_jars = self.context.products.get('jars').get(target)
        if target_jars is not None:
          for basedir, jars in target_jars.items():
            for internaljar in jars:
              os.symlink(os.path.join(basedir, internaljar),
                         os.path.join(libdir, internaljar))
              classpath.add(internaljar)
      app.binary.walk(add_jars, lambda t: t.is_internal)

      # Add external dependencies to the bundle.
      for basedir, externaljar in self.list_jar_dependencies(app.binary):
        path = os.path.join(basedir, externaljar)
        os.symlink(path, os.path.join(libdir, externaljar))
        classpath.add(externaljar)

    for basedir, jars in self.context.products.get('jars').get(app.binary).items():
      if len(jars) != 1:
        raise TaskError('Expected 1 mapped binary for %s but found: %s' % (app.binary, jars))

      binary = jars[0]
      binary_jar = os.path.join(basedir, binary)
      bundle_jar = os.path.join(bundledir, binary)
      if not classpath:
        os.symlink(binary_jar, bundle_jar)
      else:
        with open_zip(binary_jar, 'r') as src:
          with open_zip(bundle_jar, 'w', compression=ZIP_DEFLATED) as dest:
            for item in src.infolist():
              buffer = src.read(item.filename)
              if Manifest.PATH == item.filename:
                manifest = Manifest(buffer)
                manifest.addentry(Manifest.CLASS_PATH,
                                  ' '.join(os.path.join('libs', jar) for jar in classpath))
                buffer = manifest.contents()
              dest.writestr(item, buffer)

    for bundle in app.bundles:
      for path, relpath in bundle.filemap.items():
        bundlepath = os.path.join(bundledir, relpath)
        safe_mkdir(os.path.dirname(bundlepath))
        os.symlink(path, bundlepath)

    return bundledir
