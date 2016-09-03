# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.cmd_line_spec_parser import CmdLineSpecParser


class EngineCmdLineSpecParser(CmdLineSpecParser):
  """A CmdLineSpecParser that provides a helper for use with the v2 engine."""

  def _iter_resolve_and_parse_specs(self, rel_path, specs):
    """Given a relative path and set of input specs, produce a list of absolute specs."""
    for spec in specs:
      if spec.startswith(':'):
        yield self.parse_spec(''.join((rel_path, spec)))
      else:
        yield self.parse_spec(spec)

  def resolve_and_parse_specs(self, rel_path, specs):
    return list(self._iter_resolve_and_parse_specs(rel_path, specs))
