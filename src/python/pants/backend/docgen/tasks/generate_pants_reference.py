# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.mustache import MustacheRenderer
from pants.goal.goal import Goal
from pants.help.build_dictionary_info_extracter import BuildDictionaryInfoExtracter
from pants.help.help_info_extracter import HelpInfoExtracter
from pants.help.scope_info_iterator import ScopeInfoIterator
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.option.scope import ScopeInfo
from pants.task.task import Task
from pants.util.dirutil import safe_open


class GeneratePantsReference(Task):
  """Generate Pants reference documentation.

  Specifically, generates two files: a build dictionary detailing all the directive that
  can appear in BUILD files, and a reference listing all available goals and options.
  """

  @classmethod
  def register_options(cls, register):
    register('--pants-reference-template', default='reference/pants_reference.html',
             help='The template for the Pants reference document.  Defaults to generating '
                  'a standalone reference page.')
    register('--build-dictionary-template', default='reference/build_dictionary.html',
             help='The template for the build dictionary document.  Defaults to generating '
                  'a standalone build dictionary page.')

  def __init__(self, *args, **kwargs):
    super(GeneratePantsReference, self).__init__(*args, **kwargs)
    self._outdir = os.path.join(self.get_options().pants_distdir, 'reference')

  def execute(self):
    self._gen_reference()
    self._gen_build_dictionary()

  def _gen_reference(self):
    def get_scope_data(scope):
      ret = []
      for si in ScopeInfoIterator(self.context.options.known_scope_to_info).iterate([scope]):
        help_info = HelpInfoExtracter(si.scope).get_option_scope_help_info_from_parser(
          self.context.options.get_parser(si.scope))
        ret.append({
          # We don't use _asdict(), because then .description wouldn't be available.
          'scope_info': si,
          # We do use _asdict() here, so our mustache library can do property expansion.
          'help_info': help_info._asdict(),
        })
      return ret

    all_global_data = get_scope_data(GLOBAL_SCOPE)
    global_scope_data = all_global_data[0:1]
    global_subsystem_data = all_global_data[1:]

    goal_scopes = sorted([si.scope for si in self.context.options.known_scope_to_info.values()
    if si.scope and '.' not in si.scope and si.category != ScopeInfo.SUBSYSTEM])
    # TODO: Make goals Optionable and get their description via their ScopeInfo?
    goal_data = []
    for scope in goal_scopes:
      goal_data.append({
        'goal': scope,
        'goal_description': Goal.by_name(scope).description,
        'task_data': get_scope_data(scope)[1:]
      })

    self._do_render(self.get_options().pants_reference_template, {
      'global_scope_data': global_scope_data,
      'global_subsystem_data': global_subsystem_data,
      'goal_data': goal_data
    })

  def _gen_build_dictionary(self):
    buildfile_aliases = self.context.build_file_parser.registered_aliases()
    extracter = BuildDictionaryInfoExtracter(buildfile_aliases)
    target_type_infos = extracter.get_target_type_info()
    other_infos = sorted(extracter.get_object_info() + extracter.get_object_factory_info())
    self._do_render(self.get_options().build_dictionary_template, {
      'target_types': {
        'infos': target_type_infos
      },
      'other_symbols': {
        'infos': other_infos
      }
    })

  def _do_render(self, filename, args):
    package_name, _, _ = __name__.rpartition('.')
    renderer = MustacheRenderer(package_name=package_name)
    output_path = os.path.join(self._outdir, os.path.basename(filename))
    self.context.log.info('Generating {}'.format(output_path))
    html = renderer.render_name(filename, args)
    with safe_open(output_path, 'w') as outfile:
      outfile.write(html.encode('utf8'))
