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

from zipfile import  ZIP_STORED, ZIP_DEFLATED

from twitter.common.contextutil import open_zip as open_jar, pushd, temporary_dir
from twitter.common.dirutil import safe_mkdir

from twitter.pants import get_buildroot, get_version, is_internal
from twitter.pants.java import Manifest
from twitter.pants.tasks.jvm_binary_task import JvmBinaryTask


class BinaryCreate(JvmBinaryTask):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("outdir"), dest="binary_create_outdir",
                            help="Create binary in this directory.")

    option_group.add_option(mkflag("compressed"), mkflag("compressed", negate=True),
                            dest="binary_create_compressed", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Create a compressed binary jar.")

    option_group.add_option(mkflag("deployjar"), mkflag("deployjar", negate=True),
                            dest="binary_create_deployjar", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Create a monolithic deploy jar containing this "
                                 "binaries classfiles as well as all classfiles it depends on "
                                 "transitively.")

  def __init__(self, context):
    JvmBinaryTask.__init__(self, context)

    self.outdir = (
      context.options.binary_create_outdir
      or context.config.get('binary-create', 'outdir')
    )
    self.compression = ZIP_DEFLATED if context.options.binary_create_compressed else ZIP_STORED
    self.deployjar = context.options.binary_create_deployjar

    context.products.require('jars', predicate=self.is_binary)
    if self.deployjar:
      self.require_jar_dependencies()

  def execute(self, targets):
    for binary in filter(self.is_binary, targets):
      self.create_binary(binary)

  def create_binary(self, binary):
    import platform
    safe_mkdir(self.outdir)

    jarmap = self.context.products.get('jars')

    binary_jarname = '%s.jar' % binary.basename
    binaryjarpath = os.path.join(self.outdir, binary_jarname)
    self.context.log.info('creating %s' % os.path.relpath(binaryjarpath, get_buildroot()))

    with open_jar(binaryjarpath, 'w', compression=self.compression) as jar:
      def add_jars(target):
        generated = jarmap.get(target)
        if generated:
          for basedir, jars in generated.items():
            for internaljar in jars:
              self.dump(os.path.join(basedir, internaljar), jar)

      binary.walk(add_jars, is_internal)

      if self.deployjar:
        for basedir, externaljar in self.list_jar_dependencies(binary):
          self.dump(os.path.join(basedir, externaljar), jar)

      manifest = Manifest()
      manifest.addentry(Manifest.MANIFEST_VERSION, '1.0')
      manifest.addentry(
        Manifest.CREATED_BY,
        'python %s pants %s (Twitter, Inc.)' % (platform.python_version(), get_version())
      )
      manifest.addentry(Manifest.MAIN_CLASS,  binary.main)
      jar.writestr(Manifest.PATH, manifest.contents())

      jarmap.add(binary, self.outdir, [binary_jarname])

  def dump(self, jarpath, jarfile):
    self.context.log.debug('  dumping %s' % jarpath)

    with temporary_dir() as tmpdir:
      with open_jar(jarpath) as sourcejar:
        BinaryCreate.safe_extract(sourcejar, tmpdir)
        for root, dirs, files in os.walk(tmpdir):
          for file in files:
            path = os.path.join(root, file)
            relpath = os.path.relpath(path, tmpdir)
            if Manifest.PATH != relpath:
              jarfile.write(path, relpath)

  @staticmethod
  def safe_extract(jar, dest_dir):
    """OS X's python 2.6.1 has a bug in zipfile that makes it unzip directories as regular files."""
    for path in jar.namelist():
      # While we're at it, we also perform this safety test.
      if path.startswith('/') or path.startswith('..'):
        raise Exception('Jar file contains unsafe path: %s' % path)
      if not path.endswith('/'):  # Ignore directories. extract() will create parent dirs as needed.
        jar.extract(path, dest_dir)
