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
import tarfile

from contextlib import contextmanager
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

from twitter.common.collections import OrderedDict, OrderedSet
from twitter.common.dirutil import safe_mkdir

from . import Task, TaskError
from twitter.pants import get_buildroot, is_internal
from twitter.pants.java import Manifest
from twitter.pants.targets import JvmApp, JvmBinary


@contextmanager
def open_zip(path, mode, compression=ZIP_STORED):
  zip = ZipFile(path, mode=mode, compression=compression)
  yield zip
  zip.close()


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

  @contextmanager
  def create_tar(self, path):
    tar = tarfile.open(path, self.mode, dereference=True)
    yield tar
    tar.close()

  def archive(self, basedir, outdir, name):
    tarpath = os.path.join(outdir, '%s.%s' % (name, self.extension))
    with self.create_tar(tarpath) as tar:
      tar.add(basedir, arcname='')
    return tarpath


class ZipArchiver(Archiver):
  def __init__(self, compression):
    Archiver.__init__(self)
    self.compression = compression

  def archive(self, basedir, outdir, name):
    zippath = os.path.join(outdir, '%s.zip' % name)
    with open_zip(zippath, 'w', compression=ZIP_DEFLATED) as zip:
      for root, dirs, files in os.walk(basedir):
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


def is_binary(target):
  return isinstance(target, JvmBinary)


class BundleCreate(Task):

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("outdir"), dest="bundle_create_outdir",
                            help="Create bundles and archives in this directory.")

    option_group.add_option(mkflag("archive"), dest="bundle_create_archive",
                            type="choice", choices=list(ARCHIVER_BY_TYPE.keys()),
                            help="[%%default] Create an archive from the bundle. "
                                 "Choose from %s" % ARCHIVER_BY_TYPE.keys())

  def __init__(self, context):
    Task.__init__(self, context)

    self.outdir = (
      context.options.bundle_create_outdir
      or context.config.get('bundle-create', 'outdir')
    )
    self.archiver = context.options.bundle_create_archive

    self.context.products.require('jars', predicate=is_binary)
    self.context.products.require('jar_dependencies', predicate=is_binary)

  def execute(self, targets):
    def is_app(target):
      return isinstance(target, JvmApp)

    archiver = ARCHIVER_BY_TYPE[self.archiver] if self.archiver else None
    for app in filter(is_app, targets):
      basedir = self.bundle(app)
      if archiver:
        archivepath = archiver.archive(basedir, self.outdir, app.name)
        self.context.log.info('created %s' % os.path.relpath(archivepath, get_buildroot()))

  def bundle(self, app):
    bundledir = os.path.join(self.outdir, '%s-bundle' % app.name)
    self.context.log.info('creating %s' % os.path.relpath(bundledir, get_buildroot()))

    safe_mkdir(bundledir, clean=True)

    libdir = os.path.join(bundledir, 'libs')
    os.mkdir(libdir)

    genmap = self.context.products.get('jar_dependencies')
    classpath = OrderedSet()
    def link_jar(target):
      generated = genmap.get(target)
      if generated:
        for basedir, jars in generated.items():
          for jar in jars:
            if jar not in classpath:
              path = os.path.join(basedir, jar)
              os.symlink(path, os.path.join(libdir, jar))
              classpath.add(jar)
    app.walk(link_jar, is_internal)

    for basedir, jars in self.context.products.get('jars').get(app.binary).items():
      if len(jars) != 1:
        raise TaskError('Expected 1 mapped binary but found: %s' % jars)

      binary = jars.pop()
      with open_zip(os.path.join(basedir, binary), 'r') as src:
        with open_zip(os.path.join(bundledir, binary), 'w', compression=ZIP_DEFLATED) as dest:
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
