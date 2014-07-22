# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.python.targets.python_target import PythonTarget


class PythonLibrary(PythonTarget):
  """Produces a Python library.

  :param name: Name of library
  :param sources: A list of filenames representing the source code this
     library is compiled from. Paths are relative to the
     BUILD file's directory.
  :param resources: non-Python resources, e.g. templates, keys, other data
     (it is
     recommended that your application uses the pkgutil package to access these
     resources in a .zip-module friendly way.)
  :param dependencies: Other targets that this target depends on.
     These dependencies may
     be other ``python_library``-like targets (``python_library``,
     ``python_thrift_library``, ``python_antlr_library`` and so forth) or
     ``python_requirement_library`` targets.
  :type dependencies: List of target specs
  :param provides:
    The :ref:`setup_py <bdict_setup_py>` to publish that represents this
    target outside the repo.
  :param compatibility: either a string or list of strings that represents
    interpreter compatibility for this target, using the Requirement-style
    format, e.g. ``'CPython>=3', or just ['>=2.7','<3']`` for requirements
    agnostic to interpreter class.
  :param exclusives: An optional dict of exclusives tags. See CheckExclusives
    for details.
  """
  pass
