# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


def ensure_arg(args, arg, param=None):
  """Make sure the arg is present in the list of args.

  If arg is not present, adds the arg and the optional param.
  If present and param != None, sets the parameter following the arg to param.

  :param list args: strings representing an argument list.
  :param string arg: argument to make sure is present in the list.
  :param string param: parameter to add or update after arg in the list.
  :return: possibly modified list of args.
  """
  found = False
  for idx, found_arg in enumerate(args):
    if found_arg == arg:
      if param is not None:
        args[idx + 1] = param
      return args

  if not found:
    args += [arg]
    if param is not None:
      args += [param]
  return args


def remove_arg(args, arg, has_param=False):
  """Removes the first instance of the specified arg from the list of args.

  If the arg is present and has_param is set, also removes the parameter that follows
  the arg.
  :param list args: strings representing an argument list.
  :param staring arg: argument to remove from the list.
  :param bool has_param: if true, also remove the parameter that follows arg in the list.
  :return: possibly modified list of args.
  """
  for idx, found_arg in enumerate(args):
    if found_arg == arg:
      if has_param:
        slice_idx = idx + 2
      else:
        slice_idx = idx + 1
      args = args[:idx] + args[slice_idx:]
      break
  return args
