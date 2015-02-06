# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

import pystache
from pkg_resources import resource_string

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.core.tasks.reflect import assemble_buildsyms


class TargetsHelp(ConsoleTask):
  """Show online help for symbols usable in BUILD files (java_library, etc)."""

  @classmethod
  def register_options(cls, register):
    super(TargetsHelp, cls).register_options(register)
    register('--details', help='Display details about the specific target type or BUILD symbol.')

  def __init__(self, *args, **kwargs):
    super(TargetsHelp, self).__init__(*args, **kwargs)
    self._templates_dir = os.path.join('templates', 'targets_help')

  def list_all(self):
    d = assemble_buildsyms(build_file_parser=self.context.build_file_parser)
    max_sym_len = max(len(sym) for sym in d.keys())
    console = []
    blurb_template = resource_string(__name__,
                                     os.path.join(self._templates_dir,
                                                  'cli_list_blurb.mustache'))
    for sym, data in sorted(d.items(), key=lambda(k, v): k.lower()):
      blurb = pystache.render(blurb_template, data)
      summary = re.sub('\s+', ' ', blurb).strip()
      if len(summary) > 50:
        summary = summary[:47].strip() + '...'
      console.append('{0}: {1}'.format(sym.rjust(max_sym_len), summary))
    return console

  def details(self, sym):
    '''Show details of one symbol.

    :param sym: string like 'java_library' or 'artifact'.'''
    d = assemble_buildsyms(build_file_parser=self.context.build_file_parser)
    if not sym in d:
      return ['\nNo such symbol: {0}\n'.format(sym)]
    template = resource_string(__name__, os.path.join(self._templates_dir,
                                                      'cli_details.mustache'))
    spacey_render = pystache.render(template, d[sym]['defn'])
    compact_render = re.sub('\n\n+', '\n\n', spacey_render)
    return compact_render.splitlines()

  def console_output(self, targets):
    if self.get_options().details:
      return self.details(self.get_options().details)
    else:
      return self.list_all()
