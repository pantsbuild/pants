# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
from pkg_resources import resource_string
import inspect
import optparse
import os
import re

from twitter.common.collections.ordereddict import OrderedDict

from pants.backend.core.tasks.task import Task
from pants.base.build_manual import get_builddict_info
from pants.base.exceptions import TaskError
from pants.base.generator import Generator, TemplateData
from pants.base.target import Target
from pants.goal.option_helpers import add_global_options
from pants.goal.goal import Goal
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


# regex for docstring lines of the forms
# :param foo: blah blah blah
# :param string foo: blah blah blah
param_re = re.compile(r':param (?P<type>[A-Za-z0-9_]* )?(?P<param>[^:]*):(?P<desc>.*)')


# regex for docstring lines of the form
# :type foo: list of strings
type_re = re.compile(r':type (?P<param>[^:]*):(?P<type>.*)')


def shard_param_docstring(s):
  """Shard a Target class' sphinx-flavored __init__ docstring by param

  E.g., if the docstring is

  :param float x: x coordinate
     blah blah blah
  :param y: y coordinate
  :type y: float

  should return
  OrderedDict(
    'x' : {'type': 'float', 'param': 'x coordinate\n   blah blah blah'},
    'y' : {'type': 'float', 'param': 'y coordinate'},
  )
  """

  # state: what I'm "recording" right now. Needed for multi-line fields.
  # ('x', 'param') : recording contents of a :param x: blah blah blah
  # ('x', 'type') : recording contents of a :type x: blah blah blah
  # ('!forget', '!') not recording useful things; purged before returning
  state = ('!forget', '!')

  # shards: return value
  shards = OrderedDict([('!forget', {'!': ''})])

  s = s or ''
  for line in s.splitlines():
    # If this line is indented, keep "recording" whatever we're recording:
    if line and line[0].isspace():
      param, type_or_desc = state
      shards[param][type_or_desc] += '\n' + line
    else:  # line not indented, starting something new
      # if a :param foo: line...
      if param_re.match(line):
        param_m = param_re.match(line)
        param_name = param_m.group('param')
        state = (param_name, 'param')
        if not param_name in shards:
          shards[param_name] = {}
        if param_m.group('type'):
          shards[param_name]['type'] = param_m.group('type')
        shards[param_name]['param'] = param_m.group('desc')
      # if a :type foo: line...
      elif type_re.match(line):
        type_m = type_re.match(line)
        param_name = type_m.group('param')
        state = (param_name, 'type')
        if not param_name in shards:
          shards[param_name] = {}
        shards[param_name]['type'] = type_m.group('type')
      # else, nothing that we want to "record"
      else:
        state = ('!forget', '!')
  del shards['!forget']
  return shards


def entry_for_one_class(nom, cls):
  """  Generate a BUILD dictionary entry for a class.
  nom: name like 'python_binary'
  cls: class like pants.python_binary"""

  if issubclass(cls, Target):
    # special case for Target classes: "inherit" information up the class tree.

    args_accumulator = []
    defaults_accumulator = ()
    docs_accumulator = []
    for c in inspect.getmro(cls):
      if not issubclass(c, Target): continue
      if not inspect.ismethod(c.__init__): continue
      args, _, _, defaults = inspect.getargspec(c.__init__)
      args_accumulator = args[1:] + args_accumulator
      defaults_accumulator = (defaults or ()) + defaults_accumulator
      dedented_doc = indent_docstring_by_n(c.__init__.__doc__, 0)
      docs_accumulator.append(shard_param_docstring(dedented_doc))
    # Suppress these from BUILD dictionary: they're legit args to the
    # Target implementation, but they're not for BUILD files:
    assert(args_accumulator[1] == 'address')
    assert(args_accumulator[2] == 'build_graph')
    args_accumulator = [args_accumulator[0]] + args_accumulator[3:]
    defaults_accumulator = (defaults_accumulator[0],) + defaults_accumulator[3:]
    argspec = inspect.formatargspec(args_accumulator,
                                    None,
                                    None,
                                    defaults_accumulator)
    # Suppress these from BUILD dictionary: they're legit args to the
    # Target implementation, but they're not for BUILD files:
    suppress = set(['address', 'build_graph', 'payload'])
    funcdoc = ''
    for shard in docs_accumulator:
      for param, parts in shard.items():
        if param in suppress:
          continue
        suppress.add(param)  # only show things once
        if 'param' in parts:
          funcdoc += '\n:param {0}: {1}'.format(param, parts['param'])
        if 'type' in parts:
          funcdoc += '\n:type {0}: {1}'.format(param, parts['type'])
  else:
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

  return entry(nom,
               classdoc=cls.__doc__,
               argspec=argspec,
               funcdoc=funcdoc,
               methods=methods,
               impl='{0}.{1}'.format(cls.__module__, cls.__name__))


def entry_for_one(nom, sym):
  if inspect.isclass(sym):
    return entry_for_one_class(nom, sym)
  if inspect.ismethod(sym) or inspect.isfunction(sym):
    return entry_for_one_func(nom, sym)
  return msg_entry(nom, "TODO! no doc gen for %s %s" % (
        str(type(sym)), str(sym)))


PREDEFS = {  # some hardwired entries
  'dependencies' : {'defn': msg_entry('dependencies',
                    """Old name for `target`_"""),},
  'egg' : {'defn': msg_entry('egg',
                             'In older Pants, loads a pre-built Python egg '
                             'from file system. Undefined in newer Pants.')},
  'java_tests': {'defn': msg_entry('java_tests',
                  """Old name for `junit_tests`_"""),},
  'pants': {'defn': msg_entry('pants',
                  """In old Pants versions, a reference to a Pants targets.
                  (In new Pants versions, just use strings.)""")},
  'python_artifact': {'suppress': True},  # unused alias for PythonArtifact
  'python_test_suite': {'defn': msg_entry('python_test_suite',
                                          """Deprecated way to group Python tests; use `dependencies`_""")},
  'scala_tests': {'defn': msg_entry('scala_tests',
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


def gen_goals_glopts_reference_data():
  global_option_parser = optparse.OptionParser(add_help_option=False)
  add_global_options(global_option_parser)
  glopts = []
  for o in global_option_parser.option_list:
    hlp = None
    if o.help:
      hlp = indent_docstring_by_n(o.help.replace('[%default]', '').strip(), 2)
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
      hlp = indent_docstring_by_n(o.help.replace('[%default]', '').strip(), 6)
    option_l.append(TemplateData(
        st=str(o),
        default=default,
        hlp=hlp,
        typ=o.type))
  return TemplateData(
    title=title,
    options=option_l,
    xref=xref)


def gen_tasks_goals_reference_data():
  """Generate the template data for the goals reference rst doc."""
  goal_dict = {}
  goal_names = []
  for goal in Goal.all():
    parser = optparse.OptionParser(add_help_option=False)
    Goal.setup_parser(parser, [], [goal])
    options_by_title = defaultdict(lambda: None)
    for group in parser.option_groups:
      options_by_title[group.title] = group
    found_option_groups = set()
    tasks = []
    for task_name in goal.ordered_task_names():
      task_type = goal.task_type_by_name(task_name)
      doc = indent_docstring_by_n(task_type.__doc__ or '', 2)
      options_title = Goal.option_group_title(goal, task_name)
      og = options_by_title[options_title]
      if og:
        found_option_groups.add(options_title)
      impl = '{0}.{1}'.format(task_type.__module__, task_type.__name__)
      tasks.append(TemplateData(
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
    goal_dict[goal.name] = TemplateData(goal=goal,
                                        tasks=tasks,
                                        leftover_opts=leftover_options,
                                        leftover_ogs=leftover_option_groups)
    goal_names.append(goal.name)

  goals = [goal_dict[name] for name in sorted(goal_names, key=_lower)]
  return goals


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
    if 'suppress' in val and val['suppress']: continue
    retval[nom] = val
  if build_file_parser:
    symbol_hash = get_syms(build_file_parser)
    for nom in symbol_hash:
      v = symbol_hash[nom]
      retval[nom] = {'defn': entry_for_one(nom, v)}
  return retval


class BuildBuildDictionary(Task):
  """Generate documentation for the Sphinx site."""

  def __init__(self, *args, **kwargs):
    super(BuildBuildDictionary, self).__init__(*args, **kwargs)
    self._templates_dir = os.path.join('templates', 'builddictionary')
    self._outdir = os.path.join(self.context.config.getdefault('pants_distdir'), 'builddict')

  def execute(self):
    self._gen_goals_reference()
    self._gen_build_dictionary()

  def _gen_build_dictionary(self):
    """Generate the BUILD dictionary reference rst doc."""
    d = assemble(build_file_parser=self.context.build_file_parser)
    template = resource_string(__name__, os.path.join(self._templates_dir, 'page.mustache'))
    tocs = [tocl(d), jvm_sub_tocl(d), python_sub_tocl(d)]

    defns = [d[t]['defn'] for t in sorted(d.keys(), key=_lower)]
    filename = os.path.join(self._outdir, 'build_dictionary.rst')
    self.context.log.info('Generating %s' % filename)
    with safe_open(filename, 'w') as outfile:
      generator = Generator(template,
                            tocs=tocs,
                            defns=defns)
      generator.write(outfile)

  def _gen_goals_reference(self):
    """Generate the goals reference rst doc."""
    goals = gen_tasks_goals_reference_data()
    glopts = gen_goals_glopts_reference_data()

    template = resource_string(__name__,
                               os.path.join(self._templates_dir, 'goals_reference.mustache'))
    filename = os.path.join(self._outdir, 'goals_reference.rst')
    self.context.log.info('Generating %s' % filename)
    with safe_open(filename, 'w') as outfile:
      generator = Generator(template, goals=goals, glopts=glopts)
      generator.write(outfile)
