# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
import sys
from textwrap import dedent

from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.binaries import binary_util
from pants.engine.exp.engine import LocalSerialEngine
from pants.engine.exp.examples.planners import setup_json_scheduler
from pants.engine.exp.fs import PathGlobs
from pants.engine.exp.nodes import Noop, SelectNode, TaskNode, Throw
from pants.util.contextutil import temporary_file, temporary_file_path


def format_type(node):
  if type(node) == TaskNode:
    return node.func.__name__
  return type(node).__name__


def format_subject(node):
  if node.variants:
    return '({})@{}'.format(node.subject, ','.join('{}={}'.format(k, v) for k, v in node.variants))
  else:
    return '({})'.format(node.subject)


def format_product(node):
  if type(node) == SelectNode and node.variant_key:
    return '{}@{}'.format(node.product.__name__, node.variant_key)
  return node.product.__name__


def format_node(node, state):
  return '{}:{}:{} == {}'.format(format_product(node),
                                 format_subject(node),
                                 format_type(node),
                                 str(state).replace('"', '\\"'))


# NB: there are only 12 colors in `set312`.
colorscheme = 'set312'
max_colors = 12
colors = {}


def format_color(node, node_state):
  if type(node_state) is Throw:
    return 'tomato'
  elif type(node_state) is Noop:
    return 'white'
  key = node.product
  return colors.setdefault(key, (len(colors) % max_colors) + 1)


def create_digraph(scheduler, storage, request):

  yield 'digraph plans {'
  yield '  node[colorscheme={}];'.format(colorscheme)
  yield '  concentrate=true;'
  yield '  rankdir=LR;'

  for ((node, node_state), dependency_entries) in scheduler.product_graph.walk(request.roots):
    node_str = format_node(node, node_state)

    yield (' "{node}" [style=filled, fillcolor={color}];'
            .format(color=format_color(node, node_state),
                    node=node_str))

    for (dep, dep_state) in dependency_entries:
      yield '  "{}" -> "{}"'.format(node_str, format_node(dep, dep_state))

  yield '}'


def visualize_execution_graph(scheduler, storage, request):
  with temporary_file(cleanup=False, suffix='.dot') as fp:
    for line in create_digraph(scheduler, storage, request):
      fp.write(line)
      fp.write('\n')

  print('dot file saved to: {}'.format(fp.name))
  with temporary_file_path(cleanup=False, suffix='.svg') as image_file:
    subprocess.check_call('dot -Tsvg -o{} {}'.format(image_file, fp.name), shell=True)
    print('svg file saved to: {}'.format(image_file))
    binary_util.ui_open(image_file)


def visualize_build_request(build_root, goals, subjects):
  scheduler, storage = setup_json_scheduler(build_root)
  execution_request = scheduler.build_request(goals, subjects)
  # NB: Calls `reduce` independently of `execute`, in order to render a graph before validating it.
  engine = LocalSerialEngine(scheduler, storage)
  engine.start()
  try:
    engine.reduce(execution_request)
    visualize_execution_graph(scheduler, storage, execution_request)
  finally:
    engine.close()


def pop_build_root_and_goals(description, args):
  def usage(error_message):
    print(error_message, file=sys.stderr)
    print(dedent("""
    {} {}
    """.format(sys.argv[0])), file=sys.stderr)
    sys.exit(1)

  if len(args) < 2:
    usage('Must supply at least the build root path and one goal.')

  build_root = args.pop(0)


  if not os.path.isdir(build_root):
    usage('First argument must be a valid build root, {} is not a directory.'.format(build_root))
  build_root = os.path.realpath(build_root)

  def is_goal(arg): return os.path.sep not in arg

  goals = [arg for arg in args if is_goal(arg)]
  if not goals:
    usage('Must supply at least one goal.')

  return build_root, goals, [arg for arg in args if not is_goal(arg)]


def main_addresses():
  build_root, goals, args = pop_build_root_and_goals('[build root path] [goal]+ [address spec]*', sys.argv[1:])

  cmd_line_spec_parser = CmdLineSpecParser(build_root)
  spec_roots = [cmd_line_spec_parser.parse_spec(spec) for spec in args]
  visualize_build_request(build_root, goals, spec_roots)


def main_filespecs():
  build_root, goals, args = pop_build_root_and_goals('[build root path] [filespecs]*', sys.argv[1:])

  # Create PathGlobs for each arg relative to the buildroot.
  path_globs = [PathGlobs.create('', globs=[arg]) for arg in args]
  visualize_build_request(build_root, goals, path_globs)
