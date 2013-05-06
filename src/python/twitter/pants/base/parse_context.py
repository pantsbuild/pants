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

from twitter.pants.targets import SourceRoot

from .build_environment import get_buildroot
from .fileset import Fileset

from . import BuildFile, Config


class ParseContext(object):
  """Defines the context of a parseable BUILD file target and provides a mechanism for targets to
  discover their context when invoked via eval.
  """

  class ContextError(Exception):
    """Indicates an action that requires a BUILD file parse context was attempted outside any."""

  _active = collections.deque([])
  _parsed = set()

  _strs_to_exec = [
    "from twitter.pants.base.build_file_context import *",
    "from twitter.common.quantity import Amount, Time",
  ]

  @classmethod
  def add_to_exec_context(cls, str_to_exec):
    """This hook allows for adding symbols to the execution context in which BUILD files are
    parsed. This should only be used for importing symbols that are used fairly ubiquitously in
    BUILD files, and possibly for appending to sys.path to get local python code on the python
    path.

    This will be phased out in favor of a more robust plugin architecture that supports import
    injection and path amendment."""
    cls._strs_to_exec.append(str_to_exec)

  @classmethod
  def locate(cls):
    """Attempts to find the current root directory and buildfile.

    If there is an active parse context (see do_in_context), then it is returned.
    """
    if not ParseContext._active:
      raise cls.ContextError('No parse context active.')
    return ParseContext._active[-1]

  @staticmethod
  @contextmanager
  def temp(basedir=None):
    """Activates a temporary parse context in the given basedir relative to the build root or else
    in the build root dir itself if no basedir is specified.
    """
    context = ParseContext(BuildFile(get_buildroot(), basedir or 'BUILD.temp', must_exist=False))
    with ParseContext.activate(context):
      yield

  @classmethod
  @contextmanager
  def activate(cls, ctx):
    """Activates the given ParseContext."""
    if hasattr(ctx, '_on_context_exit'):
      raise cls.ContextError('Context actions registered outside this parse context arg active')

    try:
      ParseContext._active.append(ctx)
      ctx._on_context_exit = []
      yield
    finally:
      for func, args, kwargs in ctx._on_context_exit:
        func(*args, **kwargs)
      del ctx._on_context_exit
      ParseContext._active.pop()

  def __init__(self, buildfile):
    self.buildfile = buildfile
    self._active_buildfile = buildfile
    self._parsed = False

  @classmethod
  def default_globals(cls, config=None):
    """
    Has twitter.pants.*, but not file-specfic things like __file__
    If you want to add new imports to be available to all BUILD files, add a section to the config
    similar to:

      [parse]
      headers: ['from test import get_jar',]

    You may also need to add new roots to the sys.path. see _run in pants_exe.py
    """
    to_exec = list(cls._strs_to_exec)
    if config:
      # TODO: This can be replaced once extensions are enabled with
      # https://github.com/pantsbuild/pants/issues/5
      to_exec.extend(config.getlist('parse', 'headers', default=[]))

    pants_context = {}
    for str_to_exec in to_exec:
      ast = compile(str_to_exec, '<string>', 'exec')
      Compatibility.exec_function(ast, pants_context)

    return pants_context

  def parse(self, **globalargs):
    """The entry point to parsing of a BUILD file.

    from twitter.pants.targets.sources import SourceRoot

    See locate().
    """
    if self.buildfile not in ParseContext._parsed:
      buildfile_family = tuple(self.buildfile.family())

      pants_context = self.default_globals(Config.load())

      with ParseContext.activate(self):
        for buildfile in buildfile_family:
          # We may have traversed a sibling already, guard against re-parsing it.
          if buildfile not in ParseContext._parsed:
            ParseContext._parsed.add(buildfile)

            buildfile_dir = os.path.dirname(buildfile.full_path)

            # TODO(John Sirois): This is not build-dictionary friendly - rework SourceRoot to allow
            # allow for doc of both register (as source_root) and source_root.here(*types).
            class RelativeSourceRoot(object):
              @staticmethod
              def here(*allowed_target_types):
                """Registers the cwd as a source root for the given target types."""
                SourceRoot.register(buildfile_dir, *allowed_target_types)

              def __init__(self, basedir, *allowed_target_types):
                SourceRoot.register(os.path.join(buildfile_dir, basedir), *allowed_target_types)

            eval_globals = copy.copy(pants_context)
            eval_globals.update({
              'ROOT_DIR': buildfile.root_dir,
              '__file__': buildfile.full_path,
              'globs': Fileset.lazy_rel_globs(buildfile_dir),
              'rglobs': Fileset.lazy_rel_rglobs(buildfile_dir),
              'source_root': RelativeSourceRoot,
            })
            eval_globals.update(globalargs)
            Compatibility.exec_function(buildfile.code(), eval_globals)

  def on_context_exit(self, func, *args, **kwargs):
    """ Registers a command to invoke just before this parse context is exited.

    It is an error to attempt to register an on_context_exit action outside an active parse
    context.
    """
    if not hasattr(self, '_on_context_exit'):
      raise self.ContextError('Can only register context exit actions when a parse context '
                              'is active')

    if not callable(func):
      raise TypeError('func must be a callable object')

    self._on_context_exit.append((func, args, kwargs))

  def do_in_context(self, work):
    """Executes the callable work in this parse context."""
    if not callable(work):
      raise TypeError('work must be a callable object')

    with ParseContext.activate(self):
      return work()

  def __repr__(self):
    return '%s(%s)' % (type(self).__name__, self.buildfile)
