# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from glob import glob as fsglob
from zipimport import zipimporter

from pkg_resources import Distribution, EggMetadata, PathMetadata

from pants.backend.python.python_requirement import PythonRequirement


# XXX(pl): This code is 100% broken.  I'm surprised it's even importable.
# Delete, reimplement, or fix?
def PythonEgg(glob, name=None):
  """Refers to pre-built Python eggs in the file system. (To instead fetch
  eggs in a ``pip``/``easy_install`` way, use ``python_requirement``)

  E.g., ``egg(name='foo', glob='foo-0.1-py2.6.egg')`` would pick up the
  file ``foo-0.1-py2.6.egg`` from the ``BUILD`` file's directory; targets
  could depend on it by name ``foo``.

  :param string glob: File glob pattern.
  :param string name: Target name; by default uses the egg's project name.
  """
  # TODO(John Sirois): Rationalize with globs handling in ParseContext
  eggs = fsglob(ParseContext.path(glob))

  requirements = set()
  for egg in eggs:
    if os.path.isdir(egg):
      metadata = PathMetadata(egg, os.path.join(egg, 'EGG-INFO'))
    else:
      metadata = EggMetadata(zipimporter(egg))
    dist = Distribution.from_filename(egg, metadata=metadata)
    requirements.add(dist.as_requirement())

  if len(requirements) > 1:
    raise ValueError('Got multiple egg versions! => {}'.format(requirements))

  return PythonRequirement(str(requirements.pop()), name=name)
