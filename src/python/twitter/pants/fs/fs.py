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

import hashlib
import os


# This is the max filename length for HFS+, extX and NTFS - the most likely filesystems pants will
# be run under.
# TODO(John Sirois): consider a better isolation layer
_MAX_FILENAME_LENGTH = 255


def safe_filename(name, extension=None, digest=None, max_length=_MAX_FILENAME_LENGTH):
  """Creates filename from name and extension ensuring that the final length is within the
  max_length constraint.

  By default the length is capped to work on most filesystems and the fallback to achieve
  shortening is a sha1 hash of the proposed name.

  Raises ValueError if the proposed name is not a simple filename but a file path.
  Also raises ValueError when the name is simple but cannot be satisfactorily shortened with the
  given digest.

  name:       the proposed filename without extension
  extension:  an optional extension to append to the filename
  digest:     the digest to fall back on for too-long name, extension concatenations - should
              support the hashlib digest api of update(string) and hexdigest
  max_length: the maximum desired file name length
  """
  if os.path.basename(name) != name:
    raise ValueError('Name must be a filename, handed a path: %s' % name)

  ext = extension or ''
  filename = name + ext
  if len(filename) <= max_length:
    return filename
  else:
    digest = digest or hashlib.sha1()
    digest.update(name)
    safe_name = digest.hexdigest() + ext
    if len(safe_name) > max_length:
      raise ValueError('Digest %s failed to produce a filename <= %d '
                       'characters for %s - got %s' % (digest, max_length, filename, safe_name))
    return safe_name
