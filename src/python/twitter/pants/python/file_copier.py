# ==================================================================================================
# Copyright 2014 Twitter, Inc.
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

from __future__ import print_function


import atexit
import os
import shutil

from twitter.common.dirutil import safe_mkdir, safe_rmtree
from twitter.pants.targets import SourceRoot


class FileCopier(object):
  """
  Copies the source file from registered SourceRoots for input target types to
  the destination root location at relative position.
  """

  class FileNotFoundInSourceRoot(Exception):
    def __init__(self, file, roots):
      Exception.__init__(self,
                         "Source %s not found in root(s): %s"
                         % (file, roots))

  class FileCopierError(Exception):
    def __init__(self, file, roots, error):
      Exception.__init__(self,
                         "Could not copy the source %s in root(s): %s due to %s"
                         % (file, roots, error))


  def __init__(self, copy_root):
    """
    :param copy_root: The destination at which you want to copy the files.
    """
    self._copy_root = copy_root
    self._sources = []
    atexit.register(self.cleanup, os.getpid())

  def find_and_copy_relative_file(self, source, target_types):
    """
    Finds the source file at relative position in the source root registered for
    the input target_types and copies it into the copy root at the same relative postion.
    :param source: Source file to copy
    :param target_types: The source root to look for source file listed in the order
      of preference.
    """
    safe_mkdir(self._copy_root)
    source_roots = []
    for target in target_types:
      source_roots.extend(list(SourceRoot.roots(target)))
    source_roots_owning = self._find_file(source, source_roots)
    if not source_roots_owning:
      raise self.FileNotFoundInSourceRoot(source, source_roots)
    return self.copy_relative_file(source, source_roots_owning)

  def copy_relative_file(self, source, source_root):
    """
    Copies the source file at relative position from given source_root
    to the copy_root at the relative position
    :param source:  Source file at relative position to source_root
    :param source_root: source root   in which the source file exists
    """
    return self._copyfile(source, source_root)

  def _find_file(self, source, bases):
    for base in bases:
      if os.path.commonprefix([os.path.abspath(base),
                               os.path.abspath(source)]) == os.path.abspath(base):
        return base
    return None

  def _copyfile(self, source, source_root):
    target_source = os.path.relpath(source, source_root)
    dest_file = os.path.join(self._copy_root, target_source)
    safe_mkdir(os.path.dirname(dest_file))
    try:
      shutil.copyfile(source, dest_file)
      self._sources.append(dest_file)
      return dest_file
    except IOError as e:
      raise(self.FileCopierError(source, source_root, e.strerror))
    except OSError as e:
      raise(self.FileCopierError(source, source_root, e.strerror))

  def cleanup(self, pid):
    if os.getpid() == pid:
    # Do cleanup - we're in the original parent process that parsed the BUILD files
    # And not in a forked NailgunTask executed much later.
      for source in self._sources:
        target = os.path.join(self._copy_root, source)
        if os.path.exists(target):
          os.unlink(target)
