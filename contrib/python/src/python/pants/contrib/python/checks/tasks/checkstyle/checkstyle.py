# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import sys
from builtins import str

from packaging import requirements, version
from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.subsystems.pex_build_util import PexBuilderWrapper
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.base.build_environment import get_buildroot, get_pants_cachedir, pants_version
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
      PythonSetup,
    )

  @classmethod
  def implementation_version(cls):
    return super(Checkstyle, cls).implementation_version() + [('Checkstyle', 1)]

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
             help='Prevent test failure but still produce output for problems.')

  @memoized_property
  def _python_setup(self):
    return PythonSetup.global_instance()

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

  @memoized_property
  def _acceptable_interpreter_constraints(self):
    default_constraints = PythonSetup.global_instance().interpreter_constraints
    whitelisted_constraints = self.get_options().interpreter_constraints_whitelist
    # The user wants to lint everything.
    if whitelisted_constraints == []:
      return []
    # The user did not pass a whitelist option.
    elif whitelisted_constraints is None:
      whitelisted_constraints = ()
    return [version.parse(v) for v in default_constraints + whitelisted_constraints]

  def checker_pex(self, interpreter):
    # TODO(John Sirois): Formalize in pants.base?
    pants_dev_mode = os.environ.get('PANTS_DEV')

    if pants_dev_mode:
      checker_id = self.checker_target.transitive_invalidation_hash()
    else:
      checker_id = hash_all([self._CHECKER_REQ])

    pex_path = os.path.join(
      get_pants_cachedir(), 'python-checkstyle-checker', checker_id, str(interpreter.identity))

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

  class CheckstyleSetupError(Exception): pass

  # TODO: this should be an option!
  _DEFAULT_INTERPRETER_TYPE = 'CPython'

  def _parse_requirement(self, constraint_string):
    # This does a lot of the same job as pex.interpreter.PythonIdentity.parse_requirement, but more
    # easily handles checking for compatibility with python 2 or 3 using .specifier
    try:
      return requirements.Requirement(constraint_string)
    except requirements.InvalidRequirement as orig_exc:
      # packaging.requirements.Requirement chokes on e.g. '<4', so we try again.
      try:
        return requirements.Requirement(
          '{}{}'.format(self._DEFAULT_INTERPRETER_TYPE, constraint_string))
      except requirements.InvalidRequirement:
        # We don't want to raise an error message with the hacked on interpreter type, just the
        # original input.
        raise orig_exc

  class CheckstyleRunError(TaskError):

    def __init__(self, num_failures, *args, **kwargs):
      self.num_failures = num_failures
      super(Checkstyle.CheckstyleRunError, self).__init__(*args, **kwargs)

  def execute(self):
    """"Run Checkstyle on all found non-synthetic source files."""
    if self.skip_execution:
      return

    if self.act_transitively:
      targets = self.get_targets(self._is_checked)
    else:
      targets = filter(self._is_checked, self.context.target_roots)

    with self.invalidated(targets) as invalidation_check:
      targets_by_compatibility, _ = self._interpreter_cache.partition_targets_by_compatibility(
        vt.target for vt in invalidation_check.invalid_vts)
      # TODO: Minimizing the number of interpreters used reduces the number of pexes we have to
      # create and invoke, which reduces the runtime of this task -- unfortunately, this is an
      # instance of general SAT and is a bit too much effort to implement right now, so we greedily
      # take the minimum here.
      targets_by_min_interpreter = {
        min(self._interpreter_cache.setup(filters=filters)):targets
        for filters, targets in targets_by_compatibility.items()
      }

      failure_count = 0

      for interpreter, targets in targets_by_min_interpreter.items():
        sources_for_targets = self.calculate_sources(targets)
        if sources_for_targets:
          failure_count += self.checkstyle(interpreter, sources_for_targets)

      if failure_count > 0:
        err_msg = ('{} Python Style issues found. You may try `./pants fmt <targets>`.'
                   .format(failure_count))
        if self.get_options().fail:
          raise self.CheckstyleRunError(failure_count, err_msg)
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
