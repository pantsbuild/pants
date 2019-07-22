# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import io
import json
import os
import re
import subprocess
from contextlib import contextmanager

from pants.backend.jvm.subsystems.dependency_context import DependencyContext
from pants.backend.jvm.subsystems.zinc import Zinc
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.util.contextutil import temporary_dir
from pants.util.memo import memoized_property


class AnalysisExtraction(NailgunTask):
  """A task that handles extracting product and dependency information from zinc analysis."""

  # The output JSON created by this task is not localized, but is used infrequently enough
  # that re-computing it from the zinc analysis (which _is_ cached) when necessary is fine.
  create_target_dirs = True

  @classmethod
  def subsystem_dependencies(cls):
    return super().subsystem_dependencies() + (DependencyContext, Zinc.Factory)

  @classmethod
  def register_options(cls, register):
    super().register_options(register)

  @classmethod
  def prepare(cls, options, round_manager):
    super().prepare(options, round_manager)
    round_manager.require_data('runtime_classpath')

  @classmethod
  def product_types(cls):
    return ['product_deps_by_target']

  def _create_products_if_should_run(self):
    """If this task should run, initialize empty products that it will populate.

    Returns true if the task should run.
    """

    should_run = False
    if self.context.products.is_required_data('product_deps_by_target'):
      should_run = True
      self.context.products.safe_create_data('product_deps_by_target', dict)
    return should_run

  @memoized_property
  def _zinc(self):
    return Zinc.Factory.global_instance().create(self.context.products, self.get_options().execution_strategy)

  def _jdeps_output_json(self, vt):
    return os.path.join(vt.results_dir, 'jdeps_output.json')

  @contextmanager
  def aliased_classpaths(self, classpaths):
    """
    Create unique names for each classpath entry as symlinks in a temporary directory.
    returns: dict[str -> classpath entry] which maps string paths of symlinks to classpaths.
    """
    with temporary_dir() as tempdir:
      aliases = {}
      for i, cp in enumerate(classpaths):
        alias = os.path.join(tempdir, f"{i}.jar" if not os.path.isdir(cp) else f"{1}")
        os.symlink(cp, alias)
        aliases[alias] = cp
      yield aliases

  def execute(self):
    # If none of our computed products are necessary, return immediately.
    if not self._create_products_if_should_run():
      return

    classpath_product = self.context.products.get_data('runtime_classpath')
    product_deps_by_target = self.context.products.get_data('product_deps_by_target')

    fingerprint_strategy = DependencyContext.global_instance().create_fingerprint_strategy(
        classpath_product)

    targets = self.context.targets()
    # complete classpath list
    deps_classpaths = [
      cp[1] for target in targets for cp in classpath_product.get_for_target(target) if cp[1]
    ]
    with self.aliased_classpaths(deps_classpaths) as deps_classpath_by_alias:
      with self.invalidated(targets,
                            fingerprint_strategy=fingerprint_strategy,
                            invalidate_dependents=True) as invalidation_check:
        for vt in invalidation_check.all_vts:
          # class paths for the target we are computing deps for
          target_cps = [cp[1] for cp in classpath_product.get_for_target(vt.target)]

          jdeps_output_json = self._jdeps_output_json(vt)
          if not vt.valid:
            self._run_jdeps_analysis(vt.target, target_cps, deps_classpath_by_alias, jdeps_output_json)
          self._register_products(vt.target,
                                  jdeps_output_json,
                                  product_deps_by_target)

  @memoized_property
  def _jdeps_summary_line_regex(self):
    return re.compile(r"^\S+\s->\s(\S+)$")

  def _run_jdeps_analysis(self, target, target_cps, deps_classpath_by_alias, jdeps_output_json):
    with open(jdeps_output_json, 'w') as f:
      if target_cps:
        # TODO should we find an abs path to jdeps in a better way? a jdk path?
        cmd = [
            "jdeps", "-summary",
            '-classpath', ":".join(cp for cp in deps_classpath_by_alias.keys()),
          ] + target_cps
        jdeps_output = io.StringIO(subprocess.run(cmd, stdout=subprocess.PIPE).stdout.decode('utf-8'))
        deps_classpaths = set()
        for line in jdeps_output:
          match = self._jdeps_summary_line_regex.fullmatch(line.strip()).group(1)
          deps_classpaths.add(deps_classpath_by_alias.get(match, match))

      else:
        deps_classpaths = []
      json.dump(list(deps_classpaths), f)

  def _register_products(self,
                         target,
                         jdeps_output_json,
                         product_deps_by_target):
    if target not in product_deps_by_target:
      with open(jdeps_output_json) as f:
        product_deps_by_target[target] = json.load(f)
