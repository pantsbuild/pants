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
from pants.util.contextutil import temporary_file, temporary_file_path


def create_digraph(execution_graph):
  def format_subject(subject):
    return subject.primary.address.spec if subject.primary.address else repr(subject.primary)

  def format_promise(promise):
    return '{}({})'.format(promise.product_type.__name__, format_subject(promise.subject))

  def format_label(promise, plan):
    return '{}:{}'.format(plan.func_or_task_type.value.__name__, promise.product_type.__name__)

  colorscheme = 'set312'
  colors = {}

  def color_index(key):
    return colors.setdefault(key, len(colors) + 1)

  yield 'digraph plans {'
  yield '  node[colorscheme={}];'.format(colorscheme)
  yield '  concentrate=true;'
  yield '  rankdir=LR;'

  for promise, plan in execution_graph.walk():
    label = format_label(promise, plan)
    color = color_index(plan.func_or_task_type)
    if len(plan.subjects) > 1:
      # NB: naming a subgraph cluster* triggers drawing of a box around the subgraph.  We levarge
      # this to highlight plans that chunk or are fully global.
      # See: http://www.graphviz.org/pdf/dot.1.pdf
      yield '  subgraph "cluster_{}" {{'.format(plan.func_or_task_type.value.__name__)
      yield '    colorscheme={};'.format(colorscheme)
      yield '    style=filled;'
      yield '    fillcolor={};'.format(color)
      yield '    label="{}";'.format(label)

      subgraph_node_color = color_index((plan.func_or_task_type, plan.subjects))
      for subject in plan.subjects:
        yield ('    node [style=filled, fillcolor={color}, label="{label}"] "{node}";'
               .format(color=subgraph_node_color,
                       label=format_subject(subject),
                       node=format_promise(promise.rebind(subject))))

      yield '  }'
    else:
      subject = list(plan.subjects)[0]
      node = promise.rebind(subject)

      yield ('  node [style=filled, fillcolor={color}, label="{label}({subject})"] "{node}";'
             .format(color=color,
                     label=label,
                     subject=format_subject(subject),
                     node=format_promise(node)))

    for pr in plan.promises:
      for subject in plan.subjects:
        yield '  "{}" -> "{}"'.format(format_promise(promise.rebind(subject)),
                                      format_promise(pr))

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
  execution_graph = scheduler.execution_graph(build_request)
  visualize_execution_graph(execution_graph)


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
