# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
from contextlib import contextmanager

from pants.util.process_handler import subprocess
from pants_test.testutils.git_util import get_repo_root


@contextmanager
def setup_pexrc_with_pex_python_path(pexrc_path, interpreter_paths):
  """A helper function for writing interpreter paths to a PEX_PYTHON_PATH variable
  in a .pexrc file. This function raise an error if a .pexrc file already exists at
  `pexrc_path`.

  :param pexrc_path (str): a path to a temporary .pexrc to write for testing purposes.
  :param interpreter_paths (list): a list of paths to interpreter binaries to include on 
  PEX_PYTHON_PATH.
  """
  pexrc_path = os.path.expanduser(pexrc_path)
  if os.path.exists(pexrc_path):
    raise RuntimeError("A pexrc file already exists in {}".format(pexrc_path))

  # Write a temp .pexrc in pexrc_dir.
  with open(pexrc_path, 'w') as pexrc:
    pexrc.write("PEX_PYTHON_PATH=%s" % ':'.join(interpreter_paths))
  
  try:
    yield
  finally:
    # Cleanup temporary .pexrc.
    os.remove(pexrc_path)


# TODO: Refactor similar helper methods in the pex codebase and remove from Pants.
# https://github.com/pantsbuild/pex/issues/438
def bootstrap_python_installer(location):
  install_location = os.path.join(location, '.pyenv_test')
  if os.path.exists(install_location):
    if os.listdir(install_location) == []:
      shutil.rmtree(install_location)
  if not os.path.exists(install_location):
    for _ in range(5):
      try:
        subprocess.call(['git', 'clone', 'https://github.com/pyenv/pyenv.git', install_location])
      except StandardError:
        continue
      else:
        break
    else:
      raise RuntimeError("Helper method could not clone pyenv from git")
  return os.path.join(location, '.pyenv_test/versions')


def ensure_python_interpreter(version, location=None):
  if not location:
    location = get_repo_root()
  install_location = os.path.join(bootstrap_python_installer(location), version)
  if not os.path.exists(install_location):
    os.environ['PYENV_ROOT'] = os.path.join(location, '.pyenv_test')
    subprocess.call([os.path.join(location, '.pyenv_test/bin/pyenv'), 'install', version])
  return os.path.join(install_location, 'bin', 'python' + version[0:3])
