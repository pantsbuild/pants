# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import sys
from builtins import str
from collections import defaultdict

from packaging import requirements
from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.subsystems.pex_build_util import PexBuilderWrapper
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.base.build_environment import get_buildroot, get_pants_cachedir, pants_version
from pants.base.deprecated import deprecated_conditional
from pants.base.exceptions import TaskError
from pants.base.hash_utils import hash_all
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.address import Address
from pants.option.custom_types import file_option
from pants.task.lint_task_mixin import LintTaskMixin
from pants.task.task import Task
from pants.util.collections import factory_dict
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_concurrent_creation
from pants.util.memo import memoized_classproperty, memoized_property
from pants.util.strutil import safe_shlex_join
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.platforms import Platform
from pkg_resources import DistributionNotFound, Environment, Requirement, WorkingSet

from pants.contrib.python.checks.checker import checker
from pants.contrib.python.checks.tasks.checkstyle.plugin_subsystem_base import \
  default_subsystem_for_plugin
from pants.contrib.python.checks.tasks.checkstyle.pycodestyle_subsystem import PyCodeStyleSubsystem
from pants.contrib.python.checks.tasks.checkstyle.pyflakes_subsystem import FlakeCheckSubsystem


class Checkstyle(LintTaskMixin, Task):
  _PYTHON_SOURCE_EXTENSION = '.py'

  _CUSTOM_PLUGIN_SUBSYSTEMS = (
    PyCodeStyleSubsystem,
    FlakeCheckSubsystem,
  )

  @memoized_classproperty
  def plugin_subsystems(cls):
    subsystem_type_by_plugin_type = factory_dict(default_subsystem_for_plugin)
    subsystem_type_by_plugin_type.update((subsystem_type.plugin_type(), subsystem_type)
                                         for subsystem_type in cls._CUSTOM_PLUGIN_SUBSYSTEMS)
    return tuple(subsystem_type_by_plugin_type[plugin_type] for plugin_type in checker.plugins())

  @classmethod
  def subsystem_dependencies(cls):
    return super(Task, cls).subsystem_dependencies() + cls.plugin_subsystems + (
      PexBuilderWrapper.Factory,
      PythonInterpreterCache,
    )

  @classmethod
  def implementation_version(cls):
    return super(Checkstyle, cls).implementation_version() + [('Checkstyle', 2)]

  @classmethod
  def register_options(cls, register):
    super(Checkstyle, cls).register_options(register)
    register('--severity', fingerprint=True, default='COMMENT', type=str,
             help='Only messages at this severity or higher are logged. [COMMENT WARNING ERROR].')
    register('--strict', fingerprint=True, type=bool,
             help='If enabled, have non-zero exit status for any nit at WARNING or higher.')
    register('--suppress', fingerprint=True, type=file_option, default=None,
             help='Takes a text file where specific rules on specific files will be skipped.')
    register('--fail', fingerprint=True, default=True, type=bool,
             help='If disabled, prevent pants from exiting with a failure, but still produce '
                  'output for style problems.')
    register('--enable-py3-lint', fingerprint=True, default=False, type=bool,
             help='Enable linting on Python 3-compatible targets.')

  @memoized_property
  def _interpreter_cache(self):
    return PythonInterpreterCache.global_instance()

  def _is_checked(self, target):
    return (not target.is_synthetic and isinstance(target, PythonTarget) and
            target.has_sources(self._PYTHON_SOURCE_EXTENSION))

  _CHECKER_ADDRESS_SPEC = 'contrib/python/src/python/pants/contrib/python/checks/checker'
  _CHECKER_REQ = 'pantsbuild.pants.contrib.python.checks.checker=={}'.format(pants_version())
  _CHECKER_ENTRYPOINT = 'pants.contrib.python.checks.checker.checker:main'

  @memoized_property
  def checker_target(self):
    self.context.resolve(self._CHECKER_ADDRESS_SPEC)
    return self.context.build_graph.get_target(Address.parse(self._CHECKER_ADDRESS_SPEC))

  def checker_pex(self, interpreter):
    # TODO(John Sirois): Formalize in pants.base?
    pants_dev_mode = os.environ.get('PANTS_DEV')

    if pants_dev_mode:
      checker_id = self.checker_target.transitive_invalidation_hash()
      pex_base_dir = self.workdir
    else:
      checker_id = hash_all([self._CHECKER_REQ])
      pex_base_dir = os.path.join(get_pants_cachedir(), 'python-checkstyle-checker')

    pex_path = os.path.join(pex_base_dir, checker_id, str(interpreter.identity))

    if not os.path.exists(pex_path):
      with self.context.new_workunit(name='build-checker'):
        with safe_concurrent_creation(pex_path) as chroot:
          pex_builder = PexBuilderWrapper.Factory.create(
            builder=PEXBuilder(path=chroot, interpreter=interpreter),
            log=self.context.log)

          if pants_dev_mode:
            pex_builder.add_sources_from(self.checker_target)
            req_libs = [tgt for tgt in self.checker_target.closure()
                        if isinstance(tgt, PythonRequirementLibrary)]

            pex_builder.add_requirement_libs_from(req_libs=req_libs)
          else:
            try:
              # The checker is already on sys.path, eg: embedded in pants.pex.
              platform = Platform.current()
              platform_name = platform.platform
              env = Environment(search_path=sys.path,
                                platform=platform_name,
                                python=interpreter.version_string)
              working_set = WorkingSet(entries=sys.path)
              for dist in working_set.resolve([Requirement.parse(self._CHECKER_REQ)], env=env):
                pex_builder.add_direct_requirements(dist.requires())
                # NB: We add the dist location instead of the dist itself to make sure its a
                # distribution style pex knows how to package.
                pex_builder.add_dist_location(dist.location)
              pex_builder.add_direct_requirements([self._CHECKER_REQ])
            except (DistributionNotFound, PEXBuilder.InvalidDistribution):
              # We need to resolve the checker from a local or remote distribution repo.
              pex_builder.add_resolved_requirements(
                [PythonRequirement(self._CHECKER_REQ)])

          pex_builder.set_entry_point(self._CHECKER_ENTRYPOINT)
          pex_builder.freeze()

    return PEX(pex_path, interpreter=interpreter)

  def checkstyle(self, interpreter, sources):
    """Iterate over sources and run checker on each file.

    Files can be suppressed with a --suppress option which takes an xml file containing
    file paths that have exceptions and the plugins they need to ignore.

    :param sources: iterable containing source file names.
    :return: (int) number of failures
    """
    checker = self.checker_pex(interpreter)

    args = [
      '--root-dir={}'.format(get_buildroot()),
      '--severity={}'.format(self.get_options().severity),
    ]
    if self.get_options().suppress:
      args.append('--suppress={}'.format(self.get_options().suppress))
    if self.get_options().strict:
      args.append('--strict')

    with temporary_file(binary_mode=False) as argfile:
      for plugin_subsystem in self.plugin_subsystems:
        options_blob = plugin_subsystem.global_instance().options_blob()
        if options_blob:
          argfile.write('--{}-options={}\n'.format(plugin_subsystem.plugin_type().name(),
                                                   options_blob))
      argfile.write('\n'.join(sources))
      argfile.close()

      args.append('@{}'.format(argfile.name))

      with self.context.new_workunit(name='pythonstyle',
                                     labels=[WorkUnitLabel.TOOL, WorkUnitLabel.LINT],
                                     cmd=safe_shlex_join(checker.cmdline(args))) as workunit:

        # We have determined the exact interpreter we want here, so we override any pexrc settings.
        pex_invocation_env = {
          'PEX_PYTHON': interpreter.binary,
          'PEX_IGNORE_RCFILES': 'True',
        }
        return checker.run(args=args,
                           stdout=workunit.output('stdout'),
                           stderr=workunit.output('stderr'),
                           env=pex_invocation_env)

  def _constraints_are_whitelisted(self, constraint_tuple):
    """
    Detect whether a tuple of compatibility constraints
    matches constraints imposed by the merged list of the global
    constraints from PythonSetup and a user-supplied whitelist.
    """
    if self._acceptable_interpreter_constraints == []:
      # The user wants to lint everything.
      return True
    return all(version.parse(constraint) in self._acceptable_interpreter_constraints
           for constraint in constraint_tuple)

  class CheckstyleSetupError(TaskError): pass

  def _parse_requirement(self, filt):
    try:
      return requirements.Requirement(filt)
    except requirements.InvalidRequirement as orig_error:
      # For the case of '>3', add something that looks like a requirement name.
      new_filt = 'XXX{}'.format(filt)
      try:
        return requirements.Requirement(new_filt)
      except requirements.InvalidRequirement:
        raise self.CheckstyleSetupError('Could not parse interpreter constraint {}: {}'
                                        .format(filt, str(orig_error)),
                                        orig_error)

  def _constraints_probably_include_py3(self, filters):
    # NB: I've spent too much time trying to figure out if this catches every possible case.
    parsed_constraints = [self._parse_requirement(f) for f in filters]
    for pc in parsed_constraints:
      specifier_set = pc.specifier
      if '3' in specifier_set:
        return True
      if '3.9999' in specifier_set:
        return True
      non_py3_version_included = False
      for spec in specifier_set:
        if spec.version.startswith('3'):
          if spec.operator in ['<=', '==', '=>']:
            return True
        else:
          non_py3_version_included = True
      # If there are only py3 constraints mentioned, and pants can resolve an interpreter for it,
      # and '3' and '3.9999' aren't included, I'm pretty sure that means this is definitely py3.
      if not non_py3_version_included:
        return True
    return False

  def _partition_targets_by_min_interpreter(self, tgts):
    targets_by_compatibility, _ = self._interpreter_cache.partition_targets_by_compatibility(tgts)
    # TODO: Minimizing the number of interpreters used reduces the number of pexes we have to
    # create and invoke, which reduces the runtime of this task -- unfortunately, this is an
    # instance of general SAT and is a bit too much effort to implement right now, so we greedily
    # take the minimum here.
    targets_by_min_interpreter = defaultdict(list)
    py3_compatible_target_encountered = False
    for filters, targets in targets_by_compatibility.items():
      if self._constraints_probably_include_py3(filters):
        py3_compatible_target_encountered = True
      min_interpreter = min(self._interpreter_cache.setup(filters=filters))
      targets_by_min_interpreter[min_interpreter].extend(targets)
    return (targets_by_min_interpreter, py3_compatible_target_encountered)

  class CheckstyleRunError(TaskError): pass

  def execute(self):
    """"Run Checkstyle on all found non-synthetic source files."""
    if self.skip_execution:
      return

    if self.act_transitively:
      all_targets = self.get_targets(self._is_checked)
    else:
      all_targets = filter(self._is_checked, self.context.target_roots)

    with self.invalidated(all_targets) as invalidation_check:
      targets_by_min_interpreter, py3_encountered = self._partition_targets_by_min_interpreter(
        vt.target for vt in invalidation_check.invalid_vts)

      # TODO: consider changing the language here to "upcoming" instead of "deprecated".
      deprecated_conditional(
        predicate=lambda: py3_encountered and not self.get_options().enable_py3_lint,
        removal_version='1.14.0.dev2',
        entity_description="This warning",
        hint_message=(
          "Python 3 linting is currently experimental. Add --{}-enable-py3-lint to the "
          "front of the pants command line to silence this message."
          .format(self.get_options_scope_equivalent_flag_component())))

      failure_count = 0

      for interpreter, targets in targets_by_min_interpreter.items():
        sources_for_targets = self.calculate_sources(targets)
        if sources_for_targets:
          failure_count += self.checkstyle(interpreter, sources_for_targets)

      if failure_count > 0:
        err_msg = ('{} Python Style issues found. You may try `./pants fmt <targets>`.'
                   .format(failure_count))
        if self.get_options().fail:
          raise self.CheckstyleRunError(err_msg)
        else:
          self.context.log.warn(err_msg)

  def calculate_sources(self, targets):
    """Generate a set of source files from the given targets."""
    sources = set()
    for target in targets:
      sources.update(
        source for source in target.sources_relative_to_buildroot()
        if source.endswith(self._PYTHON_SOURCE_EXTENSION)
      )
    return sources
