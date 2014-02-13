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

from twitter.pants.base import BuildFile, Target
from twitter.pants.base.build_environment import get_buildroot

from .console_task import ConsoleTask


class Filemap(ConsoleTask):
  """Outputs a mapping from source file to the target that owns the source file."""

  def console_output(self, _):
    visited = set()
    for target in self._find_targets():
      if target not in visited:
        visited.add(target)
        if hasattr(target, 'sources') and target.sources is not None:
          for sourcefile in target.sources:
            path = os.path.join(target.target_base, sourcefile)
            yield '%s %s' % (path, target.address)

  def _find_targets(self):
    if len(self.context.target_roots) > 0:
      for target in self.context.target_roots:
        yield target
    else:
      for buildfile in BuildFile.scan_buildfiles(get_buildroot()):
        target_addresses = Target.get_all_addresses(buildfile)
        for target_address in target_addresses:
          yield Target.get(target_address)
