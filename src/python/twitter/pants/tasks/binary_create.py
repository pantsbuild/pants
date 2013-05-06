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

from zipfile import  ZIP_STORED, ZIP_DEFLATED

from twitter.common.contextutil import temporary_dir
from twitter.common.dirutil import safe_mkdir

from twitter.pants import get_buildroot, get_version, is_internal
from twitter.pants.fs.archive import ZIP
from twitter.pants.java import open_jar, Manifest
from twitter.pants.tasks.jvm_binary_task import JvmBinaryTask


class BinaryCreate(JvmBinaryTask):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    JvmBinaryTask.setup_parser(option_group, args, mkflag)
    option_group.add_option(mkflag("compressed"), mkflag("compressed", negate=True),
                            dest="binary_create_compressed", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Create a compressed binary jar.")

    option_group.add_option(mkflag("zip64"), mkflag("zip64", negate=True),
                            dest="binary_create_zip64", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Create the binary jar with zip64 extensions.")

  def __init__(self, context):
    JvmBinaryTask.__init__(self, context)

    self.outdir = (
      context.options.jvm_binary_create_outdir
      or context.config.get('binary-create', 'outdir')
    )
    self.compression = ZIP_DEFLATED if context.options.binary_create_compressed else ZIP_STORED
    self.zip64 = (
      context.options.binary_create_zip64
      or context.config.getbool('binary-create', 'zip64', default=False)
    )
    self.deployjar = context.options.jvm_binary_create_deployjar

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

    with open_jar(binaryjarpath, 'w', compression=self.compression, allowZip64=self.zip64) as jar:
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
      main = binary.main or '*** java -jar not supported, please use -cp and pick a main ***'
      manifest.addentry(Manifest.MAIN_CLASS,  main)
      jar.writestr(Manifest.PATH, manifest.contents())

      jarmap.add(binary, self.outdir, [binary_jarname])

  def dump(self, jarpath, jarfile):
    self.context.log.debug('  dumping %s' % jarpath)

    with temporary_dir() as tmpdir:
      ZIP.extract(jarpath, tmpdir)
      for root, dirs, files in os.walk(tmpdir):
        for file in files:
          path = os.path.join(root, file)
          relpath = os.path.relpath(path, tmpdir)
          if Manifest.PATH != relpath:
            jarfile.write(path, relpath)

