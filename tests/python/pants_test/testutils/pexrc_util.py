# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import sys
from contextlib import contextmanager

from pants.util.contextutil import temporary_dir


@contextmanager
def setup_pexrc_with_pex_python_path(pexrc_dir, interpreter_paths):
  """A helper function for writing interpreter paths to a PEX_PYTHON_PATH variable
  in a .pexrc file. This function will preserve a .pexrc file if it already exists in 
  the pexrc_dir.

  :param pexrc_dir (str): a directory to write a .pexrc to.
  :param interpreter_paths (list): a list of paths to interpreter binaries to include on 
  PEX_PYTHON_PATH.
  """
  if not os.path.exists(pexrc_dir):
    raise IOError('Directory for pexrc %s does not exist. Please create it. Note that this '
                  'directory must be either /etc, your home directory, or '
                  'os.path.dirname(sys.argv[0]) to ensure a valid pexrc location.', pexrc_dir)
  if pexrc_dir == '/etc':
    pexrc_filename = 'pexrc'
  else:
    pexrc_filename = '.pexrc'
  pexrc_path = os.path.join(pexrc_dir, pexrc_filename)

  temp_pexrc = ''
  # preserve .pexrc if it already exists in pexrc_dir.
  if os.path.exists(pexrc_path):
    temp_pexrc = os.path.join(pexrc_dir, '.pexrc.bak')
    shutil.copyfile(pexrc_path, temp_pexrc)

  # write a temp .pexrc in pexrc_dir
  with open(pexrc_path, 'w') as pexrc:
    pexrc.write("PEX_PYTHON_PATH=%s" % ':'.join(interpreter_paths))
  yield 

  # cleanup temporary .pexrc
  os.remove(pexrc_path)
  # replace .pexrc if it was there before
  if os.path.exists(temp_pexrc):
    shutil.copyfile(temp_pexrc, pexrc_path)
    os.remove(temp_pexrc)
