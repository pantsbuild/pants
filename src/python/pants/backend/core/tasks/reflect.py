# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import argparse
import inspect
import re
from collections import OrderedDict

from docutils.core import publish_parts
from six.moves import range

from pants.base.build_manual import get_builddict_info
from pants.base.config import Config
from pants.base.exceptions import TaskError
from pants.base.generator import TemplateData
from pants.base.target import Target
from pants.goal.goal import Goal
from pants.option.global_options import register_global_options
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper, register_bootstrap_options
from pants.option.parser import Parser


# Our CLI help and doc-website-gen use this to get useful help text.

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


def dedent_docstring(s):
  return indent_docstring_by_n(s, 0)


def rst_to_html(in_rst):
  """Returns HTML rendering of an RST fragment.

  :param in_rst: rst-formatted string
  """
  if not in_rst:
    return ''
  return publish_parts(in_rst, writer_name='html')['body'].strip()


def entry(nom, classdoc_rst=None, classdoc_html=None,
          msg_rst=None, msg_html=None, argspec=None,
          funcdoc_rst=None, funcdoc_html=None, methods=None, paramdocs=None,
          impl=None, indent=1):
  """Create a struct that our template expects to see.

  :param nom: Symbol name, e.g. python_binary
  :param classdoc_rst: plain text appears above argspec
  :param msg_rst: reST. useful in hand-crafted entries
  :param argspec: arg string like (x, y="deflt")
  :param funcdoc_rst: function's __doc__, plain text
  :param methods: list of entries for class' methods
  :param impl: name of thing that implements this.
     E.g., "pants.backend.core.tasks.builddict.BuildBuildDictionary"
  :param indent: spaces to indent; rst uses this for outline level
  """

  return TemplateData(
    nom=nom.strip(),
    classdoc_rst=indent_docstring_by_n(classdoc_rst),
    classdoc_html=classdoc_html,
    msg_html=msg_html,
    msg_rst=indent_docstring_by_n(msg_rst, indent),
    argspec=argspec,
    funcdoc_html=funcdoc_html,
    funcdoc_rst=indent_docstring_by_n(funcdoc_rst, indent),
    methods=methods,
    showmethods=len(methods or []) > 0,
    paramdocs=paramdocs,
    showparams=paramdocs and (len(paramdocs) > 0),
    impl=impl)


def msg_entry(nom, msg_rst, msg_html):
  """For hard-wired entries a la "See Instead" or other simple stuff

  :param nom: name
  :param msg_rst: restructured text message
  :param msg_html: HTML message; by default, convert from rst"""
  return entry(nom, msg_rst=msg_rst, msg_html=msg_html)


def entry_for_one_func(nom, func):
  """Generate a BUILD dictionary entry for a function
  nom: name like 'python_binary'
  func: function object"""
  args, varargs, varkw, defaults = inspect.getargspec(func)
  argspec = inspect.formatargspec(args, varargs, varkw, defaults)
  funcdoc_body_rst = docstring_to_body(dedent_docstring(func.__doc__))
  funcdoc_body_html = rst_to_html(funcdoc_body_rst)
  param_docshards = shard_param_docstring(dedent_docstring(func.__doc__))
  paramdocs = param_docshards_to_template_datas(param_docshards)
  return entry(nom,
               argspec=argspec,
               funcdoc_html=funcdoc_body_html,
               funcdoc_rst=func.__doc__ or '',
               impl="{0}.{1}".format(func.__module__, func.__name__),
               paramdocs=paramdocs)


def entry_for_one_method(nom, method):
  """Generate a BUILD dictionary entry for a method
  nom: name like 'with_description'
  method: method object"""
  # TODO(lhosken) : This is darned similar to entry_for_one_func. Merge 'em?
  #                 (Punted so far since funcdoc indentation made my head hurt,
  #                 but that will go away when we stop generating RST)
  assert inspect.ismethod(method)
  args, varargs, varkw, defaults = inspect.getargspec(method)
  # args[:1] instead of args to discard "self" arg
  argspec = inspect.formatargspec(args[1:], varargs, varkw, defaults)
  funcdoc_body_rst = docstring_to_body(dedent_docstring(method.__doc__))
  funcdoc_body_html = rst_to_html(funcdoc_body_rst)
  param_docshards = shard_param_docstring(dedent_docstring(method.__doc__))
  paramdocs = param_docshards_to_template_datas(param_docshards)
  return entry(nom,
               argspec=argspec,
               funcdoc_html=funcdoc_body_html,
               funcdoc_rst=(method.__doc__ or ""),
               paramdocs=paramdocs,
               indent=2)


# regex for docstring lines of the forms
# :param foo: blah blah blah
# :param string foo: blah blah blah
param_re = re.compile(r':param (?P<type>[A-Za-z0-9_]* )?(?P<param>[^:]*):(?P<desc>.*)')


# regex for docstring lines of the form
# :type foo: list of strings
type_re = re.compile(r':type (?P<param>[^:]*):(?P<type>.*)')


def docstring_to_body(docstring):
  """Passed a sphinx-flavored docstring, return just the "body" part.

  Filter out the :param...: and :type...: part, if any.
  """
  docstring = docstring or ''
  body = ''  # return value
  recording_state = True  # are we "recording" or not
  for line in docstring.splitlines():
    if line and not line[0].isspace():
      if any(r.match(line) for r in [param_re, type_re]):
        recording_state = False
      else:
        recording_state = True
    if recording_state:
      body += line + '\n'
  return body


def shard_param_docstring(docstring):
  """Shard a sphinx-flavored __init__ docstring by param

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
  docstring = docstring or ''

  # state: what I'm "recording" right now. Needed for multi-line fields.
  # ('x', 'param') : recording contents of a :param x: blah blah blah
  # ('x', 'type') : recording contents of a :type x: blah blah blah
  # ('!forget', '!') not recording useful things; purged before returning
  state = ('!forget', '!')

  # shards: return value
  shards = OrderedDict([('!forget', {'!': ''})])
  for line in docstring.splitlines():
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


def param_docshards_to_template_datas(funcdoc_shards):
  template_datas = []
  if funcdoc_shards:
    for param, parts in funcdoc_shards.items():
      if 'type' in parts:
        type_ = parts['type']
      else:
        type_ = None
      if 'param' in parts:
        desc = rst_to_html(dedent_docstring(parts['param']))
      else:
        desc = None
      template_datas.append(TemplateData(param=param, typ=type_, desc=desc))
  return template_datas


def info_for_target_class(cls):
  """Walk up inheritance tree to get info about constructor args.

  Helper function for entry_for_one_class. Target classes use inheritance
  to handle constructor params. If you try to get the argspec for, e.g.,
  `JunitTests.__init__`, it won't mention the `name` parameter, because
  that's handled by the `Target` superclass.
  """
  # args to not-document. BUILD file authors shouldn't
  # use these; they're meant to be impl-only.
  ARGS_SUPPRESS = ['address', 'build_graph', 'payload']

  # "accumulate" argspec and docstring fragments going up inheritance tree.
  suppress = set(ARGS_SUPPRESS)  # only show things once. don't show silly things
  args_accumulator = []
  defaults_accumulator = []
  docs_accumulator = []
  for c in inspect.getmro(cls):
    if not issubclass(c, Target): continue
    if not inspect.ismethod(c.__init__): continue
    args, _, _, defaults = inspect.getargspec(c.__init__)
    args_that_have_defaults = args[len(args) - len(defaults or ()):]
    args_with_no_defaults = args[1:(len(args) - len(defaults or ()))]
    for i in range(len(args_that_have_defaults)):
      arg = args_that_have_defaults[i]
      if not arg in suppress:
        suppress.add(arg)
        args_accumulator.append(arg)
        defaults_accumulator.append(defaults[i])
    for arg in args_with_no_defaults:
      if not arg in suppress:
        suppress.add(arg)
        args_accumulator.insert(0, arg)
    dedented_doc = dedent_docstring(c.__init__.__doc__)
    docs_accumulator.append(shard_param_docstring(dedented_doc))
  argspec = inspect.formatargspec(args_accumulator,
                                  None,
                                  None,
                                  defaults_accumulator)
  suppress = set(ARGS_SUPPRESS)  # only show things once. don't show silly things
  funcdoc_rst = ''
  funcdoc_shards = OrderedDict()
  for shard in docs_accumulator:
    for param, parts in shard.items():
      if param in suppress:
        continue
      suppress.add(param)
      funcdoc_shards[param] = parts
      # Don't interpret param names like "type_" as links.
      if 'type' in parts:
        funcdoc_rst += '\n:type {0}: {1}'.format(param, parts['type'])
      if 'param' in parts:
        funcdoc_rst += '\n:param {0}: {1}'.format(param, parts['param'])
  paramdocs = param_docshards_to_template_datas(funcdoc_shards)
  return(argspec, funcdoc_rst, paramdocs)

def entry_for_one_class(nom, cls):
  """  Generate a BUILD dictionary entry for a class.
  nom: name like 'python_binary'
  cls: class like pants.python_binary"""

  if issubclass(cls, Target):
    # special case for Target classes: "inherit" information up the class tree.
    (argspec, funcdoc_rst, paramdocs) = info_for_target_class(cls)

  else:
    args, varargs, varkw, defaults = inspect.getargspec(cls.__init__)
    argspec = inspect.formatargspec(args[1:], varargs, varkw, defaults)
    funcdoc_shards = shard_param_docstring(dedent_docstring(cls.__init__.__doc__))
    paramdocs = param_docshards_to_template_datas(funcdoc_shards)
    funcdoc_rst = cls.__init__.__doc__

  methods = []
  for attrname in dir(cls):
    attr = getattr(cls, attrname)
    info = get_builddict_info(attr)
    # we want methods tagged @manual.builddict--except factory functions
    if info and not info.get('factory', False):
      if inspect.ismethod(attr):
        methods.append(entry_for_one_method(attrname, attr))
      else:
        raise TaskError('@manual.builddict() on non-method {0}'
                        ' within class {1}'.format(attrname, nom))

  return entry(nom,
               classdoc_rst=cls.__doc__,
               classdoc_html=rst_to_html(dedent_docstring(cls.__doc__)),
               argspec=argspec,
               funcdoc_rst=funcdoc_rst,
               methods=methods,
               paramdocs=paramdocs,
               impl='{0}.{1}'.format(cls.__module__, cls.__name__))


def entry_for_one(nom, sym):
  if inspect.isclass(sym):
    return entry_for_one_class(nom, sym)
  info = get_builddict_info(sym)
  if info and info.get('factory'):
    # instead of getting factory info, get info about associated class:
    return entry_for_one_class(nom, sym.im_self)
  if inspect.ismethod(sym) or inspect.isfunction(sym):
    return entry_for_one_func(nom, sym)
  return msg_entry(nom,
                   "TODO! no doc gen for {} {}".format(str(type(sym)), str(sym)),
                   "TODO! no doc gen for {} {}".format(str(type(sym)), str(sym)))


PREDEFS = {  # some hardwired entries
  'dependencies': {'defn':
                     msg_entry('dependencies',
                               'Old name for `target`_',
                               'Old name for <a href="#target">target</a>')},
  'egg': {'defn': msg_entry('egg',
                            'In older Pants, loads a pre-built Python egg '
                            'from file system. Undefined in newer Pants.',
                            'In older Pants, loads a pre-built Python egg '
                            'from file system. Undefined in newer Pants.')},
  'java_tests': {'defn':
                   msg_entry('java_tests',
                             'Old name for `junit_tests`_',
                             'Old name for <a href="#junit_tests">junit_tests</a>')},
  'pants': {'defn':
              msg_entry('pants',
                        """In old Pants versions, a reference to a Pants targets.
                        (In new Pants versions, just use strings.)""",
                        """In old Pants versions, a reference to a Pants targets.
                        (In new Pants versions, just use strings.)""")},
  'python_artifact': {'suppress': True},  # unused alias for PythonArtifact
  'python_test_suite': {'defn':
                          msg_entry('python_test_suite',
                                    'Deprecated way to group Python tests;'
                                    ' use `target`_',
                                    'Deprecated way to group Python tests;'
                                    ' use <a href="#target">target</a>')},
  'scala_tests': {'defn':
                    msg_entry('scala_tests',
                              'Old name for `scala_specs`_',
                              'Old name for <a href="#scala_specs">scala_specs</a>')},
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


def bootstrap_option_values():
  try:
    return OptionsBootstrapper(buildroot='<buildroot>').get_bootstrap_options().for_global_scope()
  finally:
    # Today, the OptionsBootstrapper mutates global state upon construction in the form of:
    #  Config.reset_default_bootstrap_option_values(...)
    # As such bootstrap options that use the buildroot get contaminated globally here.  We only
    # need the contaminated values locally though for doc display, thus the reset of global state.
    # TODO(John Sirois): remove this hack when mutable Config._defaults is killed.
    Config.reset_default_bootstrap_option_values()


def gen_glopts_reference_data():
  option_parser = Parser(env={}, config={}, scope='', help_request=None, parent_parser=None)
  def register(*args, **kwargs):
    option_parser.register(*args, **kwargs)
  register.bootstrap = bootstrap_option_values()
  register.scope = ''
  register_bootstrap_options(register, buildroot='<buildroot>')
  register_global_options(register)
  argparser = option_parser._help_argparser
  return oref_template_data_from_options(Options.GLOBAL_SCOPE, argparser)


def oref_template_data_from_options(scope, argparser):
  """Get data for the Options Reference from a CustomArgumentParser instance."""
  if not argparser: return None
  title = scope or ''
  pantsref = ''.join([c for c in title if c.isalnum()])
  option_l = []
  for o in argparser.walk_actions():
    st = '/'.join(o.option_strings)
    # Argparse elides the type in various circumstances, so we have to reverse that logic here.
    typ = o.type or (type(o.const) if isinstance(o, argparse._StoreConstAction) else str)
    default = None
    if o.default and not str(o.default).startswith("('NO',"):
      default = o.default
    hlp = None
    if o.help:
      hlp = indent_docstring_by_n(o.help, 6)
    option_l.append(TemplateData(
        st=st,
        default=default,
        hlp=hlp,
        typ=typ.__name__))
  return TemplateData(
    title=title,
    options=option_l,
    pantsref=pantsref)


def gen_tasks_options_reference_data():
  """Generate the template data for the options reference rst doc."""
  goal_dict = {}
  goal_names = []
  for goal in Goal.all():
    tasks = []
    for task_name in goal.ordered_task_names():
      task_type = goal.task_type_by_name(task_name)
      doc_rst = indent_docstring_by_n(task_type.__doc__ or '', 2)
      doc_html = rst_to_html(dedent_docstring(task_type.__doc__))
      option_parser = Parser(env={}, config={}, scope='', help_request=None, parent_parser=None)
      def register(*args, **kwargs):
        option_parser.register(*args, **kwargs)
      register.bootstrap = bootstrap_option_values()
      register.scope = ''
      task_type.register_options(register)
      argparser = option_parser._help_argparser
      scope = Goal.scope(goal.name, task_name)
      # task_type may actually be a synthetic subclass of the authored class from the source code.
      # We want to display the authored class's name in the docs (but note that we must use the
      # subclass for registering options above)
      for authored_task_type in task_type.mro():
        if authored_task_type.__module__ != 'abc':
          break
      impl = '{0}.{1}'.format(authored_task_type.__module__, authored_task_type.__name__)
      tasks.append(TemplateData(
          impl=impl,
          doc_html=doc_html,
          doc_rst=doc_rst,
          ogroup=oref_template_data_from_options(scope, argparser)))
    goal_dict[goal.name] = TemplateData(goal=goal, tasks=tasks)
    goal_names.append(goal.name)

  goals = [goal_dict[name] for name in sorted(goal_names, key=lambda x: x.lower())]
  return goals


def assemble_buildsyms(predefs=PREDEFS, build_file_parser=None):
  """Assemble big hash of entries suitable for smushing into a template.

  predefs: Hash of "hard-wired" predefined entries.
  build_file_parser: BuildFileParser which knows the BUILD-file symbols defined
    for this run of Pants; hopefully knows ~the same symbols defined for a
    "typical" run of Pants.
  """
  retval = {}
  for nom in predefs:
    val = predefs[nom]
    if 'suppress' in val and val['suppress']:
      continue
    retval[nom] = val
  if build_file_parser:
    symbol_hash = get_syms(build_file_parser)
    for nom in symbol_hash:
      v = symbol_hash[nom]
      bdi = get_builddict_info(v)
      if bdi and 'suppress' in bdi and bdi['suppress']:
        continue
      retval[nom] = {'defn': entry_for_one(nom, v)}
  return retval
