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

__author__ = 'John Sirois'

import os

from zipfile import ZIP_DEFLATED

from twitter.common.collections import OrderedDict, OrderedSet
from twitter.common.contextutil import open_tar, open_zip
from twitter.common.dirutil import safe_mkdir

from twitter.pants import get_buildroot
from twitter.pants.java import Manifest
from twitter.pants.targets import JvmApp
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.jvm_binary_task import JvmBinaryTask


class Archiver(object):
  def archive(self, basedir, outdir, name):
    """
      Archivers should archive all files found under basedir to a file at outdir of the given name.
    """


class TarArchiver(Archiver):
  def __init__(self, mode, extension):
    Archiver.__init__(self)
    self.mode = mode
    self.extension = extension

  def archive(self, basedir, outdir, name):
    tarpath = os.path.join(outdir, '%s.%s' % (name, self.extension))
    with open_tar(tarpath, self.mode, dereference=True) as tar:
      tar.add(basedir, arcname='')
    return tarpath


class ZipArchiver(Archiver):
  def __init__(self, compression):
    Archiver.__init__(self)
    self.compression = compression

  def archive(self, basedir, outdir, name):
    zippath = os.path.join(outdir, '%s.zip' % name)
    with open_zip(zippath, 'w', compression=ZIP_DEFLATED) as zip:
      for root, _, files in os.walk(basedir):
        for file in files:
          full_path = os.path.join(root, file)
          relpath = os.path.relpath(full_path, basedir)
          zip.write(full_path, relpath)
    return zippath


ARCHIVER_BY_TYPE = OrderedDict(
  tar=TarArchiver('w:', 'tar'),
  tbz2=TarArchiver('w:bz2', 'tar.bz2'),
  tgz=TarArchiver('w:gz', 'tar.gz'),
  zip=ZipArchiver(ZIP_DEFLATED)
)


class BundleCreate(JvmBinaryTask):

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    JvmBinaryTask.setup_parser(option_group, args, mkflag)
    option_group.add_option(mkflag("archive"), dest="bundle_create_archive",
                            type="choice", choices=list(ARCHIVER_BY_TYPE.keys()),
                            help="[%%default] Create an archive from the bundle. "
                                 "Choose from %s" % ARCHIVER_BY_TYPE.keys())

  def __init__(self, context):
    JvmBinaryTask.__init__(self, context)

    self.outdir = (
      context.options.jvm_binary_create_outdir
      or context.config.get('bundle-create', 'outdir')
    )
    self.archiver = context.options.bundle_create_archive

    self.deployjar = context.options.jvm_binary_create_deployjar
    if not self.deployjar:
      self.context.products.require('jars', predicate=self.is_binary)
    self.require_jar_dependencies()

  def execute(self, targets):
    def is_app(target):
      return isinstance(target, JvmApp)

    archiver = ARCHIVER_BY_TYPE[self.archiver] if self.archiver else None
    for app in filter(is_app, targets):
      basedir = self.bundle(app)
      if archiver:
        archivepath = archiver.archive(basedir, self.outdir, app.basename)
        self.context.log.info('created %s' % os.path.relpath(archivepath, get_buildroot()))

  def bundle(self, app):
    bundledir = os.path.join(self.outdir, '%s-bundle' % app.basename)
    self.context.log.info('creating %s' % os.path.relpath(bundledir, get_buildroot()))

    safe_mkdir(bundledir, clean=True)

    classpath = OrderedSet()
    if not self.deployjar:
      libdir = os.path.join(bundledir, 'libs')
      os.mkdir(libdir)

      for basedir, externaljar in self.list_jar_dependencies(app.binary):
        path = os.path.join(basedir, externaljar)
        os.symlink(path, os.path.join(libdir, externaljar))
        classpath.add(externaljar)

    for basedir, jars in self.context.products.get('jars').get(app.binary).items():
      if len(jars) != 1:
        raise TaskError('Expected 1 mapped binary but found: %s' % jars)

      binary = jars.pop()
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
