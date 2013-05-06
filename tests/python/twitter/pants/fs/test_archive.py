# ==================================================================================================
# Copyright 2013 Twitter, Inc.
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
import unittest

from twitter.common.contextutil import temporary_dir
from twitter.common.dirutil import safe_mkdir, touch

from twitter.pants.fs.archive import TAR, TGZ, TBZ2, ZIP

class ArchiveTest(unittest.TestCase):
  def round_trip(self, archiver, empty_dirs):
    def listtree(root):
      listing = set()
      for path, dirs, files in os.walk(root):
        relpath = os.path.normpath(os.path.relpath(path, root))
        if empty_dirs:
          listing.update(os.path.normpath(os.path.join(relpath, d)) for d in dirs)
        listing.update(os.path.normpath(os.path.join(relpath, f)) for f in files)
      return listing

    def test_round_trip(prefix=None):
      with temporary_dir() as fromdir:
        safe_mkdir(os.path.join(fromdir, 'a/b/c'))
        touch(os.path.join(fromdir, 'a/b/d/e.txt'))
        with temporary_dir() as archivedir:
          archive = archiver.create(fromdir, archivedir, 'archive', prefix=prefix)
          with temporary_dir() as todir:
            archiver.extract(archive, todir)
            fromlisting = listtree(fromdir)
            if prefix:
              fromlisting = set(os.path.join(prefix, x) for x in fromlisting)
              if empty_dirs:
                fromlisting.add(prefix)
            self.assertEqual(fromlisting, listtree(todir))

    test_round_trip()
    test_round_trip(prefix='jake')

  def test_tar(self):
    self.round_trip(TAR, empty_dirs=True)
    self.round_trip(TGZ, empty_dirs=True)
    self.round_trip(TBZ2, empty_dirs=True)

  def test_zip(self):
    self.round_trip(ZIP, empty_dirs=False)
