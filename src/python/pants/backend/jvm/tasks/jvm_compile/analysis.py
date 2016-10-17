# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class Analysis(object):
  """Parsed representation of an analysis for some JVM language.

  An analysis provides information on the src -> class product mappings
  and on the src -> {src|class|jar} file dependency mappings.
  """

  def write_to_path(self, outfile_path):
    with open(outfile_path, 'w') as outfile:
      self.write(outfile)

  def write(self, outfile):
    """Write this Analysis to outfile."""
    raise NotImplementedError()
