# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.common import Nit, PythonFile
from pants.backend.python.tasks.missing_contextmanager import MissingContextManager


def test_missing_contextmanager():
  mcm = MissingContextManager(PythonFile.from_statement("""
    with open("derp.txt"):
      pass
    
    with open("herp.txt") as fp:
      fp.read()
  """))
  nits = list(mcm.nits())
  assert len(nits) == 0

  mcm = MissingContextManager(PythonFile.from_statement("""
    foo = open("derp.txt")
  """))
  nits = list(mcm.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T802'
  assert nits[0].severity == Nit.WARNING

  # TODO(wickman) In these cases suggest using contextlib.closing
  mcm = MissingContextManager(PythonFile.from_statement("""
    from urllib2 import urlopen
    the_googs = urlopen("http://www.google.com").read()
  """))
  nits = list(mcm.nits())
  assert len(nits) == 0
