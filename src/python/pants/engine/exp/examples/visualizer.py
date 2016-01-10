# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
import sys
from textwrap import dedent

from pants.binaries import binary_util
from pants.build_graph.address import Address
from pants.engine.exp.examples.planners import setup_json_scheduler
from pants.engine.exp.scheduler import BuildRequest, Promise
from pants.engine.exp.engine import LocalSerialEngine
from pants.util.contextutil import temporary_file, temporary_file_path


def create_digraph(execution_graph):
  def format_node(node):
    return '{}:{}:{}'.format(node.subject, node.product, type(node))

  colorscheme = 'set312'
  colors = {}

  def color_index(key):
    return colors.setdefault(key, len(colors) + 1)

  yield 'digraph plans {'
  yield '  node[colorscheme={}];'.format(colorscheme)
  yield '  concentrate=true;'
  yield '  rankdir=LR;'

  for node, dependency_nodes in execution_graph.dependencies().items():
    node_str = format_node(node)
    label = format_label(promise, plan)
    color = color_index(type(node))

    yield ('  node [style=filled, fillcolor={color}] "{node}";'
            .format(color=color,
                    node=format_node(node)))

    for dep in dependency_nodes:
      yield '  "{}" -> "{}"'.format(node_str, formate_node(dep))

  yield '}'


def visualize_execution_graph(execution_graph):
  with temporary_file() as fp:
    for line in create_digraph(execution_graph):
      fp.write(line)
      fp.write('\n')
    fp.close()
    with temporary_file_path(cleanup=False) as image_file:
      subprocess.check_call('dot -Tsvg -o{} {}'.format(image_file, fp.name), shell=True)
      binary_util.ui_open(image_file)


def visualize_build_request(build_root, build_request):
  _, scheduler = setup_json_scheduler(build_root)
  LocalSerialEngine(scheduler).reduce(build_request)
  visualize_execution_graph(scheduler.product_graph)


def main():
  def usage(error_message):
    print(error_message, file=sys.stderr)
    print(dedent("""
    {} [build root path] [goal]+ [address spec]*
    """.format(sys.argv[0])), file=sys.stderr)
    sys.exit(1)

  args = sys.argv[1:]
  if len(args) < 2:
    usage('Must supply at least the build root path and one goal.')

  build_root = args.pop(0)
  if not os.path.isdir(build_root):
    usage('First argument must be a valid build root, {} is not a directory.'.format(build_root))

  goals = [arg for arg in args if os.path.sep not in arg]
  if not goals:
    usage('Must supply at least one goal.')

  build_request = BuildRequest(goals=goals,
                               addressable_roots=[Address.parse(spec) for spec in args
                                                  if os.path.sep in spec])
  visualize_build_request(build_root, build_request)
