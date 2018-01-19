# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager


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
