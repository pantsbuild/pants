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

__author__ = 'John Sirois'

from twitter.common.lang import Compatibility
StringIO = Compatibility.StringIO

class Manifest(object):
  """
    Implements the basics of the jar manifest specification.

    See: http://docs.oracle.com/javase/1.5.0/docs/guide/jar/jar.html#Manifest Specification
  """
  PATH = 'META-INF/MANIFEST.MF'

  MANIFEST_VERSION = 'Manifest-Version'
  CREATED_BY = 'Created-By'
  MAIN_CLASS = 'Main-Class'
  CLASS_PATH = 'Class-Path'

  def __init__(self, contents=''):
    self._contents = contents.strip()

  def addentry(self, header, value):
    if len(header) > 68:
      raise ValueError('Header name must be 68 characters or less, given %s' % header)
    if self._contents:
      self._contents += '\n'
    self._contents += '\n'.join(self._wrap('%s: %s' % (header, value)))

  def _wrap(self, text):
    input = StringIO(text)
    yield input.read(70)
    while True:
      chunk = input.read(69)
      if not chunk:
        return
      yield ' %s' % chunk

  def contents(self):
    return self._contents + '\n'
