from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from pkg_resources import resource_string
import pystache
import re

from pants.backend.core.tasks.builddictionary import assemble
from pants.backend.core.tasks.console_task import ConsoleTask

class TargetsHelp(ConsoleTask):
  """Show online help for symbols usable in BUILD files (java_library, etc)."""

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(TargetsHelp, cls).setup_parser(option_group, args, mkflag)
    option_group.add_option(mkflag("details"), dest="goal_targets_details", default=None,
                            help='Display details about the specific target type or BUILD symbol.')

  def __init__(self, *args, **kwargs):
    super(TargetsHelp, self).__init__(*args, **kwargs)
    self._templates_dir = os.path.join('templates', 'targets_help')

  def list_all(self):
    d = assemble(build_file_parser=self.context.build_file_parser)
    syms = d.keys()
    syms.sort(key=lambda x: x.lower())
    max_sym_len = max(len(sym) for sym in syms)
    console = []
    for sym in syms:
      blurb_template = '''
      {{#defn.msg_rst}}{{defn.msg_rst}}{{/defn.msg_rst}}
      {{#defn.classdoc_rst}}{{defn.classdoc_rst}}{{/defn.classdoc_rst}}
      {{#defn.funcdoc_rst}}{{defn.funcdoc_rst}}{{/defn.funcdoc_rst}}
      {{#defn.argspec}}{{defn.argspec}}{{/defn.argspec}}
      '''
      blurb = pystache.render(blurb_template, d[sym])
      summary = re.sub('\s+', ' ', blurb).strip()
      if len(summary) > 50:
        summary = summary[:47].strip() + '...'
      console.append('{0}: {1}'.format(sym.rjust(max_sym_len), summary))
    return console

  def details(self):
    d = assemble(build_file_parser=self.context.build_file_parser)
    sym = self.context.options.goal_targets_details
    if not sym in d:
      return ['No such symbol: {0}'.format(sym)]
    template = resource_string(__name__, os.path.join(self._templates_dir,
                                                      'cli.mustache'))
    spacey_render = pystache.render(template, d[sym]['defn'])
    compact_render = re.sub('\n\n+', '\n\n', spacey_render)
    return compact_render.splitlines()

  def console_output(self, targets):
    if self.context.options.goal_targets_details:
      return self.details()
    else:
      return self.list_all()
