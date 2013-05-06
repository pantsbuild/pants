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

__author__ = 'Brian Wickman'

import os

from glob import glob as fsglob
from pkg_resources import Distribution, EggMetadata, PathMetadata
from zipimport import zipimporter

from twitter.pants.base import manual

from .python_requirement import PythonRequirement


@manual.builddict(tags=["python"])
def PythonEgg(glob, name=None):
  """Refers to pre-built Python eggs in the file system. (To instead fetch
  eggs in a ``pip``/``easy_install`` way, use ``python_requirement``)

  E.g., ``egg(name='foo', glob='foo-0.1-py2.6.egg')`` would pick up the
  file ``foo-0.1-py2.6.egg`` from the ``BUILD`` file's directory; targets
  could depend on it by name ``foo``.

  :param string glob: File glob pattern.
  :param string name: Target name; by default uses the egg's project name.
  """
  eggs = fsglob(glob)

  requirements = set()
  for egg in eggs:
    if os.path.isdir(egg):
      metadata = PathMetadata(egg, os.path.join(egg, 'EGG-INFO'))
    else:
      metadata = EggMetadata(zipimporter(egg))
    dist = Distribution.from_filename(egg, metadata=metadata)
    requirements.add(dist.as_requirement())

  if len(requirements) > 1:
    raise ValueError('Got multiple egg versions! => %s' % requirements)

  return PythonRequirement(str(requirements.pop()), name=name)
