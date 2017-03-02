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
from pants.engine.engine import LocalSerialEngine
from pants.engine.fs import PathGlobs
from pants.engine.storage import Storage
from pants.engine.subsystem.native import Native
from pants.util import desktop
from pants.util.contextutil import temporary_file_path
from pants_test.engine.examples.planners import setup_json_scheduler
from pants_test.subsystem.subsystem_util import subsystem_instance


def visualize_execution_graph(scheduler):
  with temporary_file_path(cleanup=False, suffix='.dot') as dot_file:
    scheduler.visualize_graph_to_file(dot_file)
    print('dot file saved to: {}'.format(dot_file))

  with temporary_file_path(cleanup=False, suffix='.svg') as image_file:
    subprocess.check_call('dot -Tsvg -o{} {}'.format(image_file, dot_file), shell=True)
    print('svg file saved to: {}'.format(image_file))
    desktop.ui_open(image_file)


def visualize_build_request(build_root, goals, subjects):
  with subsystem_instance(Native.Factory) as native_factory:
    scheduler = setup_json_scheduler(build_root, native_factory.create())

    execution_request = scheduler.build_request(goals, subjects)
    # NB: Calls `reduce` independently of `execute`, in order to render a graph before validating it.
    engine = LocalSerialEngine(scheduler, Storage.create())
    engine.reduce(execution_request)
    visualize_execution_graph(scheduler)


def pop_build_root_and_goals(description, args):
  def usage(error_message):
    print(error_message, file=sys.stderr)
    print(dedent("""
    {}
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
  path_globs = PathGlobs.create('', include=args, exclude=[])
  visualize_build_request(build_root, goals, path_globs)
