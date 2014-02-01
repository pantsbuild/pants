# ==================================================================================================
# Copyright 2011 Twitter, Inc.
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
import stat
import zipfile

from contextlib import contextmanager

from twitter.common.contextutil import open_zip

from twitter.pants.java.manifest import Manifest
from twitter.pants.java.nailgun_client import NailgunClient, NailgunError

@contextmanager
def open_jar(path, *args, **kwargs):
  """Yields a jar in a with context that will be closed when the context exits.

  The yielded jar is a zipfile.ZipFile object with an additional mkdirs(arcpath) method that will
  create a zip directory entry similar to unix `mkdir -p`.  Additionally, the ZipFile.write and
  ZipFile.writestr methods are enhanced to call mkdirs as needed to ensure all jar entries contain
  a full complement of parent paths leading from each leaf to the root of the jar.
  """

  with open_zip(path, *args, **kwargs) as jar:
    real_write = jar.write
    real_writestr = jar.writestr

    made_dirs = set()
    def mkdirs(arcpath):
      if arcpath and arcpath not in made_dirs:
        made_dirs.add(arcpath)

        parent_path = os.path.dirname(arcpath)
        mkdirs(parent_path)

        zipinfo = zipfile.ZipInfo(arcpath if arcpath.endswith('/') else arcpath + '/')

        # We store directories without compression since they have no contents and
        # attempts to store them with compression lead to corrupted zip files as such:
        # $ unzip -t junit-runner-0.0.19.jar
        # Archive:  junit-runner-0.0.19.jar
        # testing: com/
        # error:  invalid compressed data to inflate
        # testing: com/twitter/
        # error:  invalid compressed data to inflate
        # testing: com/twitter/common/
        # error:  invalid compressed data to inflate
        # testing: com/twitter/common/testing/
        # error:  invalid compressed data to inflate
        # testing: com/twitter/common/testing/runner/
        # error:  invalid compressed data to inflate
        # testing: com/twitter/common/testing/runner/StreamSource.class   OK
        zipinfo.compress_type = zipfile.ZIP_STORED

        # PKZIP says external_attr is a 4 byte field that is host system dependant:
        #   http://www.pkware.com/documents/casestudies/APPNOTE.TXT
        # These notes do mention the low order byte will carry DOS file attributes for DOS host
        # system zips.  The DOS file attribute bits are described here:
        #   http://www.xxcopy.com/xxcopy06.htm
        #
        # More details are only found reading source, for example in BSD:
        #   ftp://ftp-archive.freebsd.org/pub/FreeBSD-Archive/old-releases/i386/1.0-RELEASE/ports/info-zip/zipinfo/zipinfo.c
        # These sources reveal the 2 high order bytes contain unix file attribute bits.
        #
        # In summary though the full 32 bit field layout is:
        # TTTTsstrwxrwxrwx0000000000ADVSHR
        # ^^^^____________________________ stat.h file type: S_IFXXX
        #     ^^^_________________________ setuid, setgid, sticky
        #        ^^^^^^^^^________________ permissions
        #                 ^^^^^^^^________ ???
        #                         ^^^^^^^^ DOS attribute bits

        # Setup unix directory perm bits: drwxr-xr-x
        zipinfo.external_attr = (
          stat.S_IFDIR                                  # file type dir
          | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR  # u+rwx
          | stat.S_IRGRP | stat.S_IXGRP                 # g+rx
          | stat.S_IROTH | stat.S_IXOTH                 # o+rx
        ) << 16

        # Add DOS directory bit
        zipinfo.external_attr |= 0x10

        real_writestr(zipinfo, '')

    def write(path, arcname=None, **kwargs):
      if os.path.isdir(path):
        mkdirs(arcname or path)
      else:
        mkdirs(os.path.dirname(arcname or path))
        real_write(path, arcname, **kwargs)

    def writestr(zinfo_or_arcname, *args, **kwargs):
      mkdirs(os.path.dirname(zinfo_or_arcname))
      real_writestr(zinfo_or_arcname, *args, **kwargs)

    jar.mkdirs = mkdirs
    jar.write = write
    jar.writestr = writestr

    yield jar


__all__ = (
  open_jar,
  Manifest,
  NailgunClient,
  NailgunError
)
