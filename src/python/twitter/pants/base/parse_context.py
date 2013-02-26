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

from contextlib import contextmanager

from twitter.common.lang import Compatibility
from twitter.pants import get_buildroot
from twitter.pants.base import BuildFile

class ContextError(Exception):
  """Inidicates an action that requires a BUILD file parse context was attempted outside any."""


class ParseContext(object):
  """Defines the context of a parseable BUILD file target and provides a mechanism for targets to
  discover their context when invoked via eval."""

  _active = collections.deque([])
  _parsed = set()

  _strs_to_exec = [
    "from twitter.pants import *",
    "from twitter.common.quantity import Amount, Time",
  ]
  @classmethod
  def add_to_exec_context(cls, str_to_exec):
    cls._strs_to_exec.append(str_to_exec)

  @staticmethod
  def locate():
    """Attempts to find the current root directory and buildfile.  If there is an active parse
    context (see do_in_context), then it is returned."""

    if not ParseContext._active:
      raise ContextError('No parse context active.')
    return ParseContext._active[-1]

  @staticmethod
  @contextmanager
  def temp(basedir=None):
    """Activates a temporary parse context in the given basedir relative to the build root or else
    in the build root dir itself if no basedir is specified."""
    context = ParseContext(BuildFile(get_buildroot(), basedir or 'BUILD.temp', must_exist=False))
    with ParseContext.activate(context):
      yield

  @staticmethod
  @contextmanager
  def activate(ctx):
    """Activates the given ParseContext."""
    if hasattr(ctx, '_on_context_exit'):
      raise ContextError('Context actions registered outside this parse context arg active')

    try:
      ParseContext._active.append(ctx)
      ctx._on_context_exit = []
      yield
    finally:
      for func, args, kwargs in ctx._on_context_exit:
        func(*args, **kwargs)
      del ctx._on_context_exit
      ParseContext._active.pop()

  PANTS_NEW=False

  @staticmethod
  def enable_pantsnew():
    """Enables the PANTS_NEW special global in BUILD files to aid in transition."""
    ParseContext.PANTS_NEW=True

  def __init__(self, buildfile):
    self.buildfile = buildfile
    self._parsed = False

  def parse(self, **globalargs):
    """The entrypoint to parsing of a BUILD file.  Changes the working directory to the BUILD file
    directory and then evaluates the BUILD file with the ROOT_DIR and __file__ globals set in
    addition to any globals specified as kwargs.  As target methods are parsed they can examine the
    stack to find these globals and thus locate themselves for the purposes of finding files
    (see locate() and bind())."""

    if self.buildfile not in ParseContext._parsed:
      buildfile_family = tuple(self.buildfile.family())
      ParseContext._parsed.update(buildfile_family)

      pants_context = {}
      for str_to_exec in self._strs_to_exec:
        ast = compile(str_to_exec, '<string>', 'exec')
        Compatibility.exec_function(ast, pants_context)

      with ParseContext.activate(self):
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
              'PANTS_NEW': ParseContext.PANTS_NEW
            })
            eval_globals.update(globalargs)
            Compatibility.exec_function(buildfile.code(), eval_globals)
        finally:
          os.chdir(start)

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

    if not callable(work):
      raise TypeError('work must be a callable object')

    with ParseContext.activate(self):
      return work()

  def __str__(self):
    return 'ParseContext(BUILD:%s)' % self.buildfile
