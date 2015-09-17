# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict, namedtuple

from pants.backend.jvm.targets.import_jars_mixin import ImportJarsMixin


class JarImportProducts(object):
  """Represents the products of jar import resolutions.

  Jar imports are jars containing source code to be unpacked and used locally.
  """

  JarImport = namedtuple('JarImport', ['coordinate', 'jar'])
  """Represents a jar containing source imports.

  Each jar import has a `coordinate` :class:`pants.backend.jvm.jar_dependency_utls.M2Coordinate`
  and a `jar` path that points to the resolved jar import for the `coordinate`.
  """

  def __init__(self):
    self._imports = defaultdict(list)

  def imported(self, target, coordinate, jar):
    """Registers a :class`JarImportProducts.JarImport` for the given target.

    :param target: The :class:`pants.backend.jvm.targets.import_jars_mixin.ImportJarsMixin` target
                   whose `imported_jar_library_specs` were resolved.
    :param coordinate: The maven coordinate of the import jar.
    :type coordinate: :class:`pants.backend.jvm.jar_dependency_utls.M2Coordinate`
    :param string jar: The path of the resolved import jar.
    """
    if not isinstance(target, ImportJarsMixin):
      raise ValueError('The given target is not an `ImportJarsMixin`: {}'.format(target))
    self._imports[target].append(self.JarImport(coordinate, jar))

  def imports(self, target):
    """Returns a list of :class:`JarImportProducts.JarImport`s for the given target.

    Will be an empty list if the the target has no jar imports.

    :rtype: list
    """
    return self._imports[target]

  def __repr__(self):
    return 'JarImportProducts({!r})'.format(self._imports)
