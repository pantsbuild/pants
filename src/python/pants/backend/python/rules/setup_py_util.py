# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import io
import os
from collections import abc, defaultdict
from typing import Dict, Iterator, List, Set, Tuple

from pants.engine.fs import Snapshot
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.legacy.structs import PythonTargetAdaptor, ResourcesAdaptor
from pants.rules.core.strip_source_root import SourceRootStrippedSources
from pants.source.source_root import SourceRoots
from pants.util.strutil import ensure_text


# Convenient type alias for the pair (package name, data files in the package).
PackageDatum = Tuple[str, Tuple[str, ...]]


class NoSourceRootError(Exception):
  """Indicates we failed to map a source file to a source root.

  This future-proofs us against switching --source-unmatched from 'create' to 'fail'.
  """


def source_root_or_raise(source_roots: SourceRoots, path: str) -> str:
  source_root = source_roots.find_by_path(path)
  if not source_root:
    raise NoSourceRootError(f'Found no source root for {path}')
  return source_root.path


# Distutils does not support unicode strings in setup.py, so we must explicitly convert to binary
# strings as pants uses unicode_literals. A natural and prior technique was to use `pprint.pformat`,
# but that embeds u's in the string itself during conversion. For that reason we roll out own
# literal pretty-printer here.
#
# Note that we must still keep this code, even though Pants only runs with Python 3, because
# the created product may still be run by Python 2.
#
# For more information, see http://bugs.python.org/issue13943.
def distutils_repr(obj):
  output = io.StringIO()
  linesep = os.linesep

  def _write(data):
    output.write(ensure_text(data))

  def _write_repr(o, indent=False, level=0):
    pad = ' ' * 4 * level
    if indent:
      _write(pad)
    level += 1

    if isinstance(o, (bytes, str)):
      # The py2 repr of str (unicode) is `u'...'` and we don't want the `u` prefix; likewise,
      # the py3 repr of bytes is `b'...'` and we don't want the `b` prefix so we hand-roll a
      # repr here.
      o_txt = ensure_text(o)
      if linesep in o_txt:
        _write('"""{}"""'.format(o_txt.replace('"""', r'\"\"\"')))
      else:
        _write("'{}'".format(o_txt.replace("'", r"\'")))
    elif isinstance(o, abc.Mapping):
      _write('{' + linesep)
      for k, v in o.items():
        _write_repr(k, indent=True, level=level)
        _write(': ')
        _write_repr(v, indent=False, level=level)
        _write(',' + linesep)
      _write(pad + '}')
    elif isinstance(o, abc.Iterable):
      if isinstance(o, abc.MutableSequence):
        open_collection, close_collection = '[]'
      elif isinstance(o, abc.Set):
        open_collection, close_collection = '{}'
      else:
        open_collection, close_collection = '()'

      _write(open_collection + linesep)
      for i in o:
        _write_repr(i, indent=True, level=level)
        _write(',' + linesep)
      _write(pad + close_collection)
    else:
      _write(repr(o))  # Numbers and bools.

  _write_repr(obj)
  return output.getvalue()


def find_packages(
    source_roots: SourceRoots,
    tgts_and_stripped_srcs: Iterator[Tuple[HydratedTarget, SourceRootStrippedSources]],
    all_sources: Snapshot
) -> Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[PackageDatum, ...]]:
  """Analyze the package structure for the given sources.

  Returns a tuple (packages, namespace_packages, package_data).
  """
  # Find all packages.
  packages: Set[str] = set()
  package_data: Dict[str, List[str]] = defaultdict(list)
  for tgt, stripped_srcs in tgts_and_stripped_srcs:
    if isinstance(tgt.adaptor, PythonTargetAdaptor):
      for file in stripped_srcs.snapshot.files:
        # Any directory containing python source files is a package.
        packages.add(os.path.dirname(file).replace(os.path.sep, '.'))
    elif isinstance(tgt.adaptor, ResourcesAdaptor):
      # Resource targets also define packages, at the target's dir (so resources can be loaded
      # via pkg_resources, using their relative path to the target as the resource name).
      source_root = source_root_or_raise(source_roots, tgt.address.spec_path)
      pkg_relpath = os.path.relpath(tgt.address.spec_path, source_root)
      package = pkg_relpath.replace(os.path.sep, '.')
      if package == '.':
        package = ''
      # Package data values should be relative to the package.
      package_data[package].extend(
        os.path.relpath(file, pkg_relpath) for file in stripped_srcs.snapshot.files)
      if package:
        # Resources might come from outside the python source root entirely, in which case
        # they will be embedded in the chroot relative to the root. This is fine, but we
        # don't want to list the root package in the metadata.
        packages.add(package)

  # See which packages are namespace packages.
  namespace_packages: Set[str] = set()
  actual_init_pys = {file for file in all_sources.files if os.path.basename(file) == '__init__.py'}
  for package in packages:
    init_py_path = os.path.join(package.replace('.', os.path.sep), '__init__.py')
    if init_py_path not in actual_init_pys:
      # PEP 420: "Regular packages will ... have an __init__.py and will reside in a single
      # directory. Namespace packages cannot contain an __init__.py."
      namespace_packages.add(package)

  return (tuple(sorted(packages)),
          tuple(sorted(namespace_packages)),
          tuple((pkg, tuple(sorted(files))) for pkg, files in package_data.items()))
