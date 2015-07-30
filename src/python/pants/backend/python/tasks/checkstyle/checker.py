# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re


# from twitter.common import app
#
# from .common import Nit, PythonFile
# from .iterators import git_iterator, path_iterator
# from .plugins import list_plugins


# app.add_option(
#   '-p',
#   action='append',
#   type='str',
#   default=[],
#   dest='plugins',
#   help='Explicitly list plugins to enable.')


# app.add_option(
#   '-n',
#   action='append',
#   type='str',
#   default=[],
#   dest='skip_plugins',
#   help='Explicitly list plugins to disable.')


# app.add_option(
#   '-l', '--list',
#   action='store_true',
#   default=False,
#   dest='list_plugins',
#   help='List available plugins and exit.')


# app.add_option(
#   '--diff',
#   type='str',
#   default=None,
#   dest='diff',
#   help='If specified, only checkstyle against the diff of the supplied branch, e.g. --diff=master.'
#     ' Defaults to $(git merge-base master HEAD) if no paths are specified.')


# app.add_option(
#   '-s', '--severity',
#   default='COMMENT',
#   type='choice',
#   choices=('COMMENT', 'WARNING', 'ERROR'),
#   dest='severity',
#   help='Only messages at this severity or higher are logged.  Options: COMMENT, WARNING, ERROR.')


# app.add_option(
#   '--strict',
#   default=False,
#   action='store_true',
#   dest='strict',
#   help='If enabled, have non-zero exit status for any nit at WARNING or higher.')


# _NOQA_LINE_SEARCH = re.compile(r'# noqa\b').search
# _NOQA_FILE_SEARCH = re.compile(r'# (flake8|checkstyle): noqa$').search
#
#
# def noqa_line_filter(python_file, line_number):
#   return _NOQA_LINE_SEARCH(python_file.lines[line_number]) is not None
#
#
# def noqa_file_filter(python_file):
#   return any(_NOQA_FILE_SEARCH(line) is not None for line in python_file.lines)


# def apply_filter(python_file, checker, line_filter):
#   if noqa_file_filter(python_file):
#     return
#
#   plugin = checker(python_file)
#
#   for nit in plugin:
#     if nit._line_number is None:
#       yield nit
#       continue
#
#     nit_slice = python_file.line_range(nit._line_number)
#
#     for line_number in range(nit_slice.start, nit_slice.stop):
#       if noqa_line_filter(python_file, line_number):
#         break
#       if line_filter and line_filter(python_file, line_number):
#         break
#     else:
#       yield nit


def proxy_main():
  def main(args, options):
    # plugins = list_plugins()
    #
    # if options.list_plugins:
    #   for plugin in plugins:
    #     print('\n%s' % plugin.__name__)
    #     if plugin.__doc__:
    #       for line in plugin.__doc__.splitlines():
    #         print('    %s' % line)
    #     else:
    #       print('    No information')
    #   return
    #
    # if options.plugins:
    #   plugins_map = dict((plugin.__name__, plugin) for plugin in plugins)
    #   plugins = list(filter(None, map(plugins_map.get, options.plugins)))
    #
    # if options.skip_plugins:
    #   plugins_map = dict((plugin.__name__, plugin) for plugin in plugins)
    #   for plugin in options.skip_plugins:
    #     plugins_map.pop(plugin, None)
    #   plugins = list(plugins_map.values())
    #
    # if args and not options.diff:
    #   iterator = path_iterator(args, options)
    # else:
    #   # No path, use git to find what changed.
    #   iterator = git_iterator(args, options)
    #
    # severity = Nit.COMMENT
    # for number, name in Nit.SEVERITY.items():
    #   if name == options.severity:
    #     severity = number
    #
    # should_fail = False
    # for filename, line_filter in iterator:
    #   try:
    #     python_file = PythonFile.parse(filename)
    #   except SyntaxError as e:
    #     print('%s:SyntaxError: %s' % (filename, e))
    #     continue
    #   for checker in plugins:
    #     for nit in apply_filter(python_file, checker, line_filter):
    #       if nit.severity >= severity:
    #         print(nit)
    #         print()
    #       should_fail |= nit.severity >= Nit.ERROR or (
    #           nit.severity >= Nit.WARNING and options.strict)

    return int(should_fail)

  app.main()
