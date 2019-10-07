# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager

from pants.base.build_environment import get_pants_cachedir
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_mkdir_for


@contextmanager
def setup_pexrc_with_pex_python_path(interpreter_paths):
  """A helper function for writing interpreter paths to a PEX_PYTHON_PATH variable in a .pexrc file.

  NB: Mutates HOME and XDG_CACHE_HOME to ensure a `~/.pexrc` that won't trample any existing file
  and will also be found.

  :param list interpreter_paths: a list of paths to interpreter binaries to include on
                                 PEX_PYTHON_PATH.
  """
  cache_dir = get_pants_cachedir()
  with temporary_dir() as home:
    xdg_cache_home = os.path.join(home, '.cache')
    with environment_as(HOME=home, XDG_CACHE_HOME=xdg_cache_home):
      target = os.path.join(xdg_cache_home, os.path.basename(cache_dir))
      safe_mkdir_for(target)
      os.symlink(cache_dir, target)

      with open(os.path.join(home, '.pexrc'), 'w') as pexrc:
        pexrc.write('PEX_PYTHON_PATH={}'.format(':'.join(interpreter_paths)))

      yield
