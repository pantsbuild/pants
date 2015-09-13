# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from pkg_resources import resource_string

from pants.backend.core.tasks.reflect import (assemble_buildsyms, gen_glopts_reference_data,
                                              gen_tasks_options_reference_data)
from pants.backend.core.tasks.task import Task
from pants.base.generator import Generator, TemplateData
from pants.util.dirutil import safe_open


# x may be a str or a unicode, so don't hard-code str.lower or unicode.lower.
_lower = lambda x: x.lower()


def tocl(d):
  """Generate TOC, in-page links to the IDs we're going to define below"""
  anchors = sorted(d.keys(), key=_lower)
  return TemplateData(t='All The Things', e=[a for a in anchors])


def sub_tocl(d, substr_list, title):
  """Generate specialized TOC. Generates the "JVM" and "Android" lists.

  E.g., sub_tocl(d, ["backend.python", "backend.core"], "Python")
  returns a list with things like "python_library" but not like "java_library"

  Filters based on each thing's impl

  :param substr_list: if an entry's impl contains any of these, use it
  :param title: pretty title
  """
  filtered_anchors = []
  for anc in sorted(d.keys(), key=_lower):
    if not d[anc]['defn']['impl']: continue
    found = [t for t in substr_list if t in d[anc]['defn']['impl']]
    if not found: continue
    filtered_anchors.append(anc)
  return TemplateData(t=title, e=filtered_anchors)


def jvm_sub_tocl(d):
  return sub_tocl(d, ['android', 'jvm', 'backend.core', 'java', 'scala'], 'JVM')


def python_sub_tocl(d):
  return sub_tocl(d, ['backend.python', 'core'], 'Python')


class BuildBuildDictionary(Task):
  """Generate documentation for the Sphinx site."""

  def __init__(self, *args, **kwargs):
    super(BuildBuildDictionary, self).__init__(*args, **kwargs)
    self._templates_dir = os.path.join('templates', 'builddictionary')
    self._outdir = os.path.join(self.get_options().pants_distdir, 'builddict')

  @classmethod
  def register_options(cls, register):
    super(BuildBuildDictionary, cls).register_options(register)
    register('--omit-impl-re', action='append', fingerprint=True,
             help='Omit goals who have a task matching one of these regexps.')

  def execute(self):
    self._gen_options_reference()
    self._gen_build_dictionary()

  def _gen_build_dictionary(self):
    """Generate the BUILD dictionary reference rst doc."""
    d = assemble_buildsyms(build_file_parser=self.context.build_file_parser)
    tocs = [tocl(d), jvm_sub_tocl(d), python_sub_tocl(d)]

    defns = [d[t]['defn'] for t in sorted(d.keys(), key=_lower)]
    # generate rst
    template = resource_string(__name__, os.path.join(self._templates_dir, 'page.mustache'))
    filename = os.path.join(self._outdir, 'build_dictionary.rst')
    self.context.log.info('Generating {}'.format(filename))
    with safe_open(filename, 'wb') as outfile:
      generator = Generator(template,
                            tocs=tocs,
                            defns=defns)
      generator.write(outfile)
    # generate html
    template = resource_string(__name__, os.path.join(self._templates_dir, 'bdict_html.mustache'))
    filename = os.path.join(self._outdir, 'build_dictionary.html')
    self.context.log.info('Generating {}'.format(filename))
    with safe_open(filename, 'wb') as outfile:
      generator = Generator(template,
                            tocs=tocs,
                            defns=defns)
      generator.write(outfile)

  def _gen_options_reference(self):
    """Generate the options reference rst doc."""
    goals = gen_tasks_options_reference_data(self.context.options)
    filtered_goals = []
    omit_impl_regexps = [re.compile(r) for r in self.get_options().omit_impl_re]
    for g in goals:
      if any(r.match(t['impl']) for r in omit_impl_regexps for t in g.tasks):
        continue
      filtered_goals.append(g)
    glopts = gen_glopts_reference_data(self.context.options)

    # generate the .rst file
    template = resource_string(__name__,
                               os.path.join(self._templates_dir, 'options_reference.mustache'))
    filename = os.path.join(self._outdir, 'options_reference.rst')
    self.context.log.info('Generating {}'.format(filename))
    with safe_open(filename, 'wb') as outfile:
      generator = Generator(template, goals=filtered_goals, glopts=glopts)
      generator.write(outfile)

    # generate the .html file
    template = resource_string(__name__,
                               os.path.join(self._templates_dir, 'oref_html.mustache'))
    filename = os.path.join(self._outdir, 'options_reference.html')
    self.context.log.info('Generating {}'.format(filename))
    with safe_open(filename, 'wb') as outfile:
      generator = Generator(template, goals=filtered_goals, glopts=glopts)
      generator.write(outfile)
