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


def hash_all(strs, digest=None):
  """Returns a hash of the concatenation of all the strings in strs.

  If a hashlib message digest is not supplied a new sha1 message digest is used.
  """
  digest = digest or hashlib.sha1()
  for s in strs:
    digest.update(s)
  return digest.hexdigest()


def hash_file(path, digest=None):
  """Hashes the contents of the file at the given path and returns the hash digest in hex form.

  If a hashlib message digest is not supplied a new sha1 message digest is used.
  """
  digest = digest or hashlib.sha1()
  with open(path, 'rb') as fd:
    s = fd.read(8192)
    while s:
      digest.update(s)
      s = fd.read(8192)
  return digest.hexdigest()
