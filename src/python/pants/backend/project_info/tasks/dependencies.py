# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from twitter.common.collections import OrderedSet

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.project_info.rules.dependencies import DependencyType
from pants.base.deprecated import deprecated_conditional
from pants.base.exceptions import TaskError
from pants.base.payload_field import JarsField, PythonRequirementsField
from pants.task.console_task import ConsoleTask


class Dependencies(ConsoleTask):
  """Print the target's dependencies."""

  @staticmethod
  def _is_jvm(target):
    return isinstance(target, (JarLibrary, JvmTarget, JvmApp))

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register(
      '--type', type=DependencyType, default=DependencyType.INTERNAL,
      help="Which types of dependencies to find, where `internal` means source code dependencies "
           "and `external` means 3rd party requirements and JARs."
    )
    register(
      '--internal-only', type=bool,
      help='Specifies that only internal dependencies should be included in the graph output '
           '(no external jars).',
      removal_version="1.27.0.dev0",
      removal_hint="Use `--dependencies-type=internal` instead.",
    )
    register(
      '--external-only',
      type=bool,
      help='Specifies that only external dependencies should be included in the graph output '
           '(only external jars).',
      removal_version="1.27.0.dev0",
      removal_hint="Use `--dependencies-type=external` instead.",
    )

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    opts = self.get_options()
    type_configured = not opts.is_default("type")
    if type_configured:
      self.dependency_type = opts.type
      return
    else:
      if opts.internal_only and opts.external_only:
        raise TaskError('At most one of --internal-only or --external-only can be selected.')
      if opts.internal_only:
        self.dependency_type = DependencyType.INTERNAL
      elif opts.external_only:
        self.dependency_type = DependencyType.EXTERNAL
      else:
        self.dependency_type = DependencyType.INTERNAL_AND_EXTERNAL

  def console_output(self, unused_method_argument):
    opts = self.get_options()
    deprecated_conditional(
      lambda: opts.is_default("type") and not opts.internal_only and not opts.external_only,
      removal_version="1.27.0.dev0",
      entity_description="The default dependencies output including external dependencies",
      hint_message="Pants will soon default to `--dependencies-type=internal`, rather than "
                   "`--dependencies-type=internal-and-external`. To prepare, run this task with"
                   " `--dependencies-type=internal`.",
    )
    ordered_closure = OrderedSet()
    for target in self.context.target_roots:
      if self.act_transitively:
        target.walk(ordered_closure.add)
      else:
        ordered_closure.update(target.dependencies)

    for tgt in ordered_closure:
      if self.dependency_type in [DependencyType.INTERNAL, DependencyType.INTERNAL_AND_EXTERNAL]:
        yield tgt.address.spec
      if self.dependency_type in [DependencyType.EXTERNAL, DependencyType.INTERNAL_AND_EXTERNAL]:
        # TODO(John Sirois): We need an external payload abstraction at which point knowledge
        # of jar and requirement payloads can go and this hairball will be untangled.
        if isinstance(tgt.payload.get_field('requirements'), PythonRequirementsField):
          for requirement in tgt.payload.requirements:
            yield str(requirement.requirement)
        elif isinstance(tgt.payload.get_field('jars'), JarsField):
          for jar in tgt.payload.jars:
            data = dict(org=jar.org, name=jar.name, rev=jar.rev)
            yield ('{org}:{name}:{rev}' if jar.rev else '{org}:{name}').format(**data)
