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
import shutil
import errno
import tempfile

def _safe_mkdir(dir):
  try:
    os.makedirs(dir)
  except OSError, e:
    if e.errno != errno.EEXIST:
      raise

class Chroot(object):
  """
    A chroot of files overlayed from one directory to another directory.

    Files may be tagged when added in order to keep track of multiple overlays in
    the chroot.
  """
  class ChrootException(Exception): pass

  class ChrootTaggingException(Exception):
    def __init__(self, filename, orig_tag, new_tag):
      Exception.__init__(self,
        "Trying to add %s to fileset(%s) but already in fileset(%s)!" % (
          filename, new_tag, orig_tag))

  def __init__(self, root, chroot_base, name="chroot"):
    """
      root = source directory for files
      chroot_base = base directory for the creation of the target chroot (e.g. 'dist')
      name = prefix of the temporary directory used in the creation of this chroot
    """
    self.root = root
    try:
      _safe_mkdir(chroot_base)
    except:
      raise Chroot.ChrootException('Unable to create chroot in %s' % chroot_base)
    self.chroot = tempfile.mkdtemp(dir=chroot_base, prefix='%s.' % name)
    self.name = name
    self.filesets = {}

  def path(self):
    """The path of the chroot."""
    return self.chroot

  def _check_tag(self, fn, label):
    for fs_label, fs in self.filesets.iteritems():
      if fn in fs and fs_label != label:
        raise Chroot.ChrootTaggingException(fn, fs_label, label)

  def _tag(self, fn, label):
    self._check_tag(fn, label)
    if label not in self.filesets:
      self.filesets[label] = set()
    self.filesets[label].add(fn)

  def _mkdir_for(self, path):
    dirname = os.path.dirname(os.path.join(self.chroot, path))
    _safe_mkdir(dirname)

  def copy(self, src, dst, label=None):
    """
      Copy file from {root}/source to {chroot}/dest with optional label.

      May raise anything shutil.copyfile can raise, e.g.
        IOError(Errno 21 'EISDIR')

      May raise ChrootTaggingException if dst is already in a fileset
      but with a different label.
    """
    self._tag(dst, label)
    self._mkdir_for(dst)
    shutil.copyfile(os.path.join(self.root, src),
                    os.path.join(self.chroot, dst))

  def write(self, data, dst, label=None, mode='w'):
    """
      Write data to {chroot}/dest with optional label.

      Has similar exceptional cases as Chroot.copy
    """

    self._tag(dst, label)
    self._mkdir_for(dst)
    with open(os.path.join(self.chroot, dst), mode) as wp:
      wp.write(data)

  def touch(self, dst, label=None):
    """
      Perform 'touch' on {chroot}/dest with optional label.

      Has similar exceptional cases as Chroot.copy
    """
    self.write('', dst, label, mode='a')

  def get(self, label):
    """Get all files labeled with 'label'"""
    return self.filesets.get(label, set())

  def files(self):
    """Get all files in the chroot."""
    all_files = set()
    for label in self.filesets:
      all_files.update(self.filesets[label])
    return all_files

  def __str__(self):
    return 'Chroot(%s => %s:%s {fs:%s})' % (self.root, self.name, self.chroot,
      ' '.join('%s' % foo for foo in self.filesets.keys()))
