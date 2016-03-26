# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import shutil

from pants.option.custom_types import target_option
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import safe_mkdir

from pants.contrib.node.subsystems.resolvers.node_resolver_base import NodeResolverBase


class ScalaJSPlatform(Subsystem, NodeResolverBase):
  """The scala.js platform."""

  options_scope = 'scala-js'

  @classmethod
  def register_options(cls, register):
    super(ScalaJSPlatform, cls).register_options(register)
    # TODO: revisit after https://rbcommons.com/s/twitter/r/3225/
    register('--runtime', advanced=True, type=list, member_type=target_option,
             default=['//:scala-js-library'],
             help='Target specs pointing to the scala-js runtime libraries.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(ScalaJSPlatform, cls).prepare(options, round_manager)
    round_manager.require_data('scala_js_binaries')

  @property
  def runtime(self):
    return self.get_options().runtime

  def resolve_target(self, node_task, target, results_dir, node_paths):
    # Copy any binaries to the results directory.
    main = ''
    scala_js_binaries = node_task.context.products.get_data('scala_js_binaries')
    for dirname, rel_paths in scala_js_binaries[target].rel_paths():
      for rel_path in rel_paths:
        main = rel_path
        src_path = os.path.join(dirname, rel_path)
        dest_path = os.path.join(results_dir, rel_path)
        safe_mkdir(os.path.dirname(dest_path))
        shutil.copy2(src_path, dest_path)

    # And emit an empty package.json.
    package = {
      'name': target.name,
      'version': '0.0.0',
      'main': main,
    }
    with open(os.path.join(results_dir, 'package.json'), 'wb') as fp:
      json.dump(package, fp, indent=2)
