# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict


def get_jar_infos(ivy_products, confs=None):
  """Returns a list of dicts containing the paths of various jar file resources.

  Keys include 'default' (normal jar path), 'sources' (path to source jar), and 'javadoc'
  (path to doc jar). None of them are guaranteed to be present, but 'sources' and 'javadoc'
  will never be present if 'default' isn't.

  :param ivy_products: ivy_jar_products data from a context
  :param confs: List of key types to return (eg ['default', 'sources']). Just returns 'default' if
    left unspecified.
  :returns mapping of IvyModuleRef --> {'default' : <jar_filenames>,
                                        'sources' : <jar_filenames>,
                                        'javadoc' : <jar_filenames>}
  """
  confs = confs or ['default']
  classpath_maps = defaultdict(dict)
  if ivy_products:
    for conf, info_group in ivy_products.items():
      if conf not in confs:
        continue # We don't care about it.
      for info in info_group:
        for module in info.modules_by_ref.values():
          if module.artifact:
            classpath_maps[module.ref][conf] = module.artifact
  return classpath_maps
