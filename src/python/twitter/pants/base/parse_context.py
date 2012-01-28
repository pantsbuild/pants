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

import collections
import copy
import os

class ContextError(Exception):
  """Inidicates an action that requires a BUILD file parse context was attempted outside any."""


class ParseContext(object):
  """Defines the context of a parseable BUILD file target and provides a mechanism for targets to
  discover their context when invoked via eval."""

  _contexts = collections.deque([])
  _parsed = set()

  @staticmethod
  def locate():
    """Attempts to find the current root directory and buildfile.  If there is an active parse
    context (see do_in_context), then it is returned."""

    if not ParseContext._contexts:
      raise ContextError('No parse context active.')
    return ParseContext._contexts[-1]

  def __init__(self, buildfile):
    self.buildfile = buildfile
    self._parsed = False

  def parse(self, **globals):
    """The entrypoint to parsing of a BUILD file.  Changes the working directory to the BUILD file
    directory and then evaluates the BUILD file with the ROOT_DIR and __file__ globals set in
    addition to any globals specified as kwargs.  As target methods are parsed they can examine the
    stack to find these globals and thus locate themselves for the purposes of finding files
    (see locate() and bind())."""

    if self.buildfile not in ParseContext._parsed:
      buildfile_family = tuple(self.buildfile.family())
      ParseContext._parsed.update(buildfile_family)

      pants_context = {}
      ast = compile("from twitter.pants import *", "<string>", "exec")
      exec ast in pants_context

      def _parse():
        start = os.path.abspath(os.curdir)
        try:
          os.chdir(self.buildfile.parent_path)
          for buildfile in buildfile_family:
            self.buildfile = buildfile
            eval_globals = copy.copy(pants_context)
            eval_globals.update({
              'ROOT_DIR': buildfile.root_dir,
              '__file__': buildfile.full_path,

              # TODO(John Sirois): kill PANTS_NEW and its usages when pants.new is rolled out
              'PANTS_NEW': False
            })
            eval_globals.update(globals)
            eval(buildfile.code(), eval_globals)
        finally:
          os.chdir(start)

      self.do_in_context(_parse)

  def on_context_exit(self, func, *args, **kwargs):
    """ Registers a command to invoke just before this parse context is exited. It is an error to
    attempt to register an on_context_exit action outside an active parse context."""

    if not hasattr(self, '_on_context_exit'):
      raise ContextError('Can only register context exit actions when a parse context is active')

    if not callable(func):
      raise TypeError('func must be a callable object')

    self._on_context_exit.append((func, args, kwargs))

  def do_in_context(self, work):
    """Executes the callable work in this parse context."""

    if hasattr(self, '_on_context_exit'):
      raise ContextError('Context actions registered outside this parse context being active')

    if not callable(work):
      raise TypeError('work must be a callable object')

    try:
      ParseContext._contexts.append(self)
      self._on_context_exit = []
      return work()
    finally:
      for func, args, kwargs in self._on_context_exit:
        func(*args, **kwargs)
      del self._on_context_exit
      ParseContext._contexts.pop()

  def __str__(self):
    return 'ParseContext(BUILD:%s)' % self.buildfile
