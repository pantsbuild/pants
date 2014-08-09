# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import inspect
import optparse
import os

from pkg_resources import resource_string
from pants.backend.core.tasks.task import Task
from pants.base.build_manual import get_builddict_info
from pants.base.exceptions import TaskError
from pants.base.generator import Generator, TemplateData
from pants.goal.option_helpers import add_global_options
from pants.goal.phase import Phase
from pants.util.dirutil import safe_open


def indent_docstring_by_n(s, n=1):
  """Given a non-empty docstring, return version indented N spaces.
  Given an empty thing, return the thing itself."""
  # In reST, it's useful to have strings that are similarly-indented.
  # If we have a classdoc indented by 2 next to an __init__ funcdoc indented
  # by 4, reST doesn't format things nicely. Oh, totally-dedenting doesn't
  # format nicely either.

  # Docstring indentation: more gnarly than you'd think:
  # http://www.python.org/dev/peps/pep-0257/#handling-docstring-indentation
  if not s: return s
  # Convert tabs to spaces (following the normal Python rules)
  # and split into a list of lines:
  lines = s.expandtabs().splitlines()
  # Determine minimum indentation (first line doesn't count):
  indent = 999
  for line in lines[1:]:
    stripped = line.lstrip()
    if stripped:
      indent = min(indent, len(line) - len(stripped))
  # Remove indentation (first line is special):
  trimmed = [lines[0].strip()]
  if indent < 999:
    for line in lines[1:]:
      trimmed.append(line[indent:].rstrip())
  # Strip off trailing and leading blank lines:
  while trimmed and not trimmed[-1]:
    trimmed.pop()
  while trimmed and not trimmed[0]:
    trimmed.pop(0)
  # Return a single string:
  indent = n * " "
  return '\n'.join([indent + t for t in trimmed])


def entry(nom, classdoc=None, msg_rst=None, argspec=None, funcdoc=None,
          methods=None, impl=None, indent=1):
  """Create a struct that our template expects to see.

  :param nom: Symbol name, e.g. python_binary
  :param classdoc: plain text appears above argspec
  :param msg_rst: reST. useful in hand-crafted entries
  :param argspec: arg string like (x, y="deflt")
  :param funcdoc: function's __doc__, plain text
  :param methods: list of entries for class' methods
  :param impl: name of thing that implements this.
     E.g., "pants.backend.core.tasks.builddict.BuildBuildDictionary"
  :param indent: spaces to indent; rst uses this for outline level
  """

  return TemplateData(
    nom=nom.strip(),
    classdoc=indent_docstring_by_n(classdoc),
    msg_rst=indent_docstring_by_n(msg_rst, indent),
    argspec=argspec,
    funcdoc=indent_docstring_by_n(funcdoc, indent),
    methods=methods,
    showmethods=methods and (len(methods) > 0),
    impl=impl)


def msg_entry(nom, defn):
  """For hard-wired entries a la "See Instead" or other simple stuff"""
  return entry(nom, msg_rst=defn)


def entry_for_one_func(nom, func):
  """Generate a BUILD dictionary entry for a function
  nom: name like 'python_binary'
  func: function object"""
  args, varargs, varkw, defaults = inspect.getargspec(func)
  argspec = inspect.formatargspec(args, varargs, varkw, defaults)
  return entry(nom,
               argspec=argspec,
               funcdoc=func.__doc__,
               impl="{0}.{1}".format(func.__module__, func.__name__))


def entry_for_one_method(nom, method):
  """Generate a BUILD dictionary entry for a method
  nom: name like 'with_description'
  method: method object"""
  # TODO(lhosken) : This is darned similar to entry_for_one_func. Merge 'em?
  #                 (Punted so far since funcdoc indentation made my head hurt)
  assert inspect.ismethod(method)
  args, varargs, varkw, defaults = inspect.getargspec(method)
  # args[:1] instead of args to discard "self" arg
  argspec = inspect.formatargspec(args[1:], varargs, varkw, defaults)
  return entry(nom,
               argspec=argspec,
               funcdoc=(method.__doc__ or ""),
               indent=2)


def entry_for_one_class(nom, cls):
  """  Generate a BUILD dictionary entry for a class.
  nom: name like 'python_binary'
  cls: class like pants.python_binary"""
  try:
    args, varargs, varkw, defaults = inspect.getargspec(cls.__init__)
    argspec = inspect.formatargspec(args[1:], varargs, varkw, defaults)
    funcdoc = cls.__init__.__doc__

    methods = []
    for attrname in dir(cls):
      attr = getattr(cls, attrname)
      attr_bdi = get_builddict_info(attr)
      if attr_bdi is None: continue
      if inspect.ismethod(attr):
        methods.append(entry_for_one_method(attrname, attr))
        continue
      raise TaskError('@manual.builddict on non-method %s within class %s '
                      'but I only know what to do with methods' %
                      (attrname, nom))

  except TypeError:  # __init__ might not be a Python function
    argspec = None
    funcdoc = None
    methods = None

  return entry(nom,
               classdoc=cls.__doc__,
               argspec=argspec,
               funcdoc=funcdoc,
               methods=methods,
               impl="{0}.{1}".format(cls.__module__, cls.__name__))


def entry_for_one(nom, sym):
  if inspect.isclass(sym):
    return entry_for_one_class(nom, sym)
  if inspect.ismethod(sym) or inspect.isfunction(sym):
    return entry_for_one_func(nom, sym)
  return msg_entry(nom, "TODO! no doc gen for %s %s" % (
        str(type(sym)), str(sym)))


PREDEFS = {  # some hardwired entries
  "egg" : {"defn": msg_entry("egg",
                             "In older Pants, loads a pre-built Python egg "
                             "from file system. Undefined in newer Pants.")},
  "java_tests": {"defn": msg_entry("java_tests",
                  """Old name for `junit_tests`_"""),},
  "pants": {"defn": msg_entry("pants",
                  """In old Pants versions, a reference to a Pants targets.
                  (In new Pants versions, just use strings.)""")},
  "python_artifact": {"suppress": True},  # unused alias for PythonArtifact
  "python_test_suite": {"defn": msg_entry("python_test_suite",
                                          """Deprecated way to group Python tests; use `dependencies`_""")},
  "scala_tests": {"defn": msg_entry("scala_tests",
                  """Old name for `scala_specs`_""")},
}

# Report symbols defined in BUILD files (jvm_binary...)
# Returns dict {"scala_library": ScalaLibrary, ...}
def get_syms(build_file_parser):
  syms = {}

  def map_symbols(symbols):
    for sym, item in symbols.items():
      if sym not in PREDEFS:
        syms[sym] = item

  aliases = build_file_parser.registered_aliases()
  map_symbols(aliases.targets)
  map_symbols(aliases.objects)
  map_symbols(aliases.context_aware_object_factories)
  return syms

# Needed since x may be a str or a unicode, so we can't hard-code str.lower or unicode.lower.
_lower = lambda x: x.lower()


def tocl(d):
  """Generate TOC, in-page links to the IDs we're going to define below"""
  anchors = sorted(d.keys(), key=_lower)
  return TemplateData(t="All The Things", e=[a for a in anchors])


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
    if not d[anc]["defn"]["impl"]: continue
    found = [t for t in substr_list if t in d[anc]["defn"]["impl"]]
    if not found: continue
    filtered_anchors.append(anc)
  return TemplateData(t=title, e=filtered_anchors)


def jvm_sub_tocl(d):
  return sub_tocl(d, ["android", "jvm", "backend.core", "java", "scala"], "JVM")


def python_sub_tocl(d):
  return sub_tocl(d, ["backend.python", "core"], "Python")


def gen_goals_glopts_reference_data():
  global_option_parser = optparse.OptionParser(add_help_option=False)
  add_global_options(global_option_parser)
  glopts = []
  for o in global_option_parser.option_list:
    hlp = None
    if o.help:
      hlp = indent_docstring_by_n(o.help.replace("[%default]", "").strip(), 2)
    glopts.append(TemplateData(st=str(o), hlp=hlp))
  return glopts


def gref_template_data_from_options(og):
  """Get data for the Goals Reference from an optparse.OptionGroup"""
  if not og: return None
  title = og.title or ""
  xref = "".join([c for c in title if c.isalnum()])
  option_l = []
  for o in og.option_list:
    default = None
    if o.default and not str(o.default).startswith("('NO',"):
      default = o.default
    hlp = None
    if o.help:
      hlp = indent_docstring_by_n(o.help.replace("[%default]", "").strip(), 6)
    option_l.append(TemplateData(
        st=str(o),
        default=default,
        hlp=hlp,
        typ=o.type))
  return TemplateData(
    title=title,
    options=option_l,
    xref=xref)


def gen_goals_phases_reference_data():
  """Generate the template data for the goals reference rst doc."""
  phase_dict = {}
  phase_names = []
  for phase, raw_goals in Phase.all():
    parser = optparse.OptionParser(add_help_option=False)
    phase.setup_parser(parser, [], [phase])
    options_by_title = defaultdict(lambda: None)
    for group in parser.option_groups:
      options_by_title[group.title] = group
    found_option_groups = set()
    goals = []
    for goal in sorted(raw_goals, key=(lambda x: x.name.lower())):
      doc = indent_docstring_by_n(goal.task_type.__doc__ or "", 2)
      options_title = goal.title_for_option_group(phase)
      og = options_by_title[options_title]
      if og:
        found_option_groups.add(options_title)
      impl = "{0}.{1}".format(goal.task_type.__module__, goal.task_type.__name__)
      goals.append(TemplateData(
          impl=impl,
          doc=doc,
          ogroup=gref_template_data_from_options(og)))

    leftover_option_groups = []
    for group in parser.option_groups:
      if group.title in found_option_groups: continue
      leftover_option_groups.append(gref_template_data_from_options(group))
    leftover_options = []
    for option in parser.option_list:
      leftover_options.append(TemplateData(st=str(option)))
    phase_dict[phase.name] = TemplateData(phase=phase,
                                          goals=goals,
                                          leftover_opts=leftover_options,
                                          leftover_ogs=leftover_option_groups)
    phase_names.append(phase.name)

  phases = [phase_dict[name] for name in sorted(phase_names, key=_lower)]
  return phases


def assemble(predefs=PREDEFS, build_file_parser=None):
  """Assemble big hash of entries suitable for smushing into a template.

  predefs: Hash of "hard-wired" predefined entries.
  build_file_parser: BuildFileParser which knows the BUILD-file symbols defined
    for this run of Pants; hopefully knows ~the same symbols defined for a
    "typical" run of Pants.
  """
  retval = {}
  for nom in predefs:
    val = predefs[nom]
    if "suppress" in val and val["suppress"]: continue
    retval[nom] = val
  if build_file_parser:
    symbol_hash = get_syms(build_file_parser)
    for nom in symbol_hash:
      v = symbol_hash[nom]
      retval[nom] = {"defn": entry_for_one(nom, v)}
  return retval


class BuildBuildDictionary(Task):
  """Generate documentation for the Sphinx site."""

  def __init__(self, *args, **kwargs):
    super(BuildBuildDictionary, self).__init__(*args, **kwargs)
    self._templates_dir = os.path.join('templates', 'builddictionary')
    self._outdir = os.path.join(self.context.config.getdefault("pants_distdir"), "builddict")

  def execute(self):
    self._gen_goals_reference()
    self._gen_build_dictionary()

  def _gen_build_dictionary(self):
    """Generate the BUILD dictionary reference rst doc."""
    d = assemble(build_file_parser=self.context.build_file_parser)
    template = resource_string(__name__, os.path.join(self._templates_dir, 'page.mustache'))
    tocs = [tocl(d), jvm_sub_tocl(d), python_sub_tocl(d)]

    defns = [d[t]["defn"] for t in sorted(d.keys(), key=_lower)]
    filename = os.path.join(self._outdir, 'build_dictionary.rst')
    self.context.log.info('Generating %s' % filename)
    with safe_open(filename, 'w') as outfile:
      generator = Generator(template,
                            tocs=tocs,
                            defns=defns)
      generator.write(outfile)

  def _gen_goals_reference(self):
    """Generate the goals reference rst doc."""
    phases = gen_goals_phases_reference_data()
    glopts = gen_goals_glopts_reference_data()

    template = resource_string(__name__,
                               os.path.join(self._templates_dir, 'goals_reference.mustache'))
    filename = os.path.join(self._outdir, 'goals_reference.rst')
    self.context.log.info('Generating %s' % filename)
    with safe_open(filename, 'w') as outfile:
      generator = Generator(template, phases=phases, glopts=glopts)
      generator.write(outfile)
