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
import copy
import collections

class ParseContext(object):
  """Defines the context of a parseable BUILD file target and provides a mechanism for targets to
  discover their context when invoked via eval."""

  _contexts = collections.deque([])

  @classmethod
  def locate(cls):
    """Attempts to find the current root directory and buildfile.  If there is an active parse
    context (see do_in_context), then it is returned."""

    return ParseContext._contexts[-1]

  def __init__(self, buildfile):
    self.buildfile = buildfile

  def parse(self):
    """The entrypoint to parsing of a BUILD file.  Changes the working directory to the BUILD file
    directory and then evaluates the BUILD file with the ROOT_DIR and __file__ globals set.  As
    target methods are parsed they can examine the stack to find these globals and thus locate
    themselves for the purposes of finding files (see locate() and bind())."""

    pants_context = {}
    ast = compile("from twitter.pants import *", "<string>", "exec")
    exec ast in pants_context

    def _parse():
      start = os.path.abspath(os.curdir)
      try:
        os.chdir(self.buildfile.parent_path)
        for buildfile in self.buildfile.family():
          self.buildfile = buildfile
          eval_globals = copy.copy(pants_context)
          eval_globals.update({
            'ROOT_DIR': buildfile.root_dir,
            '__file__': buildfile.full_path })
          execfile(buildfile.full_path, eval_globals, {})
      finally:
        os.chdir(start)

    self.do_in_context(_parse)

  def do_in_context(self, work):
    """Executes the callable work in this parse context."""

    try:
      ParseContext._contexts.append(self)
      return work()
    finally:
      ParseContext._contexts.pop()

  def __str__(self):
    return 'ParseContext(BUILD:%s)' % self.buildfile
