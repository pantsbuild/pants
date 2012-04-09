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

import itertools
import os

from twitter.pants.targets import TargetWithSources
from twitter.pants.targets.jvm_binary import JvmApp
from twitter.pants.tasks.console_task import ConsoleTask

__author__ = 'Dave Buchfuhrer'

class FileDeps(ConsoleTask):
  def console_output(self, targets):
    files = set()
    for target in targets:
      if isinstance(target, TargetWithSources):
        files.update(target.expand_files(recursive=False))
      if isinstance(target, JvmApp):
        files.update(itertools.chain(*[bundle.filemap.keys() for bundle in target.bundles]))
    return files
