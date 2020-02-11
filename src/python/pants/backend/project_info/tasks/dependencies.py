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
      '--type', type=DependencyType, default=DependencyType.SOURCE,
      help="Which types of dependencies to find, where `source` means source code dependencies "
           "and `3rdparty` means third-party requirements and JARs."
    )
    register(
      '--internal-only', type=bool,
      help='Specifies that only internal dependencies should be included in the graph output '
           '(no external jars).',
      removal_version="1.27.0.dev0",
      removal_hint="Use `--dependencies-type=source` instead.",
    )
    register(
      '--external-only',
      type=bool,
      help='Specifies that only external dependencies should be included in the graph output '
           '(only external jars).',
      removal_version="1.27.0.dev0",
      removal_hint="Use `--dependencies-type=3rdparty` instead.",
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
        self.dependency_type = DependencyType.SOURCE
      elif opts.external_only:
        self.dependency_type = DependencyType.THIRD_PARTY
      else:
        self.dependency_type = DependencyType.SOURCE_AND_THIRD_PARTY

  @property
  def act_transitively(self):
    # NB: Stop overriding this property once the deprecation is complete.
    deprecated_conditional(
      lambda: self.get_options().is_default("transitive"),
      entity_description=f"Pants defaulting to `--dependencies-transitive`",
      removal_version="1.28.0.dev0",
      hint_message="Currently, Pants defaults to `--dependencies-transitive`, which means that it "
                   "will find all transitive dependencies for the target, rather than only direct "
                   "dependencies. This is a useful feature, but surprising to be the default."
                   "\n\nTo prepare for this change to the default value, set in `pants.ini` under "
                   "the section `dependencies` the value `transitive: False`. In Pants 1.28.0, "
                   "you can safely remove the setting."
    )
    return self.get_options().transitive

  def console_output(self, unused_method_argument):
    opts = self.get_options()
    deprecated_conditional(
      lambda: opts.is_default("type") and not opts.internal_only and not opts.external_only,
      removal_version="1.27.0.dev0",
      entity_description="The default dependencies output including external dependencies",
      hint_message="Pants will soon default to `--dependencies-type=source`, rather than "
                   "`--dependencies-type=source-and-3rdparty`. To prepare, run this goal with"
                   " `--dependencies-type=source`.",
    )
    ordered_closure = OrderedSet()
    for target in self.context.target_roots:
      if self.act_transitively:
        target.walk(ordered_closure.add)
      else:
        ordered_closure.update(target.dependencies)

    for tgt in ordered_closure:
      if self.dependency_type in [DependencyType.SOURCE, DependencyType.SOURCE_AND_THIRD_PARTY]:
        yield tgt.address.spec
      if self.dependency_type in [DependencyType.THIRD_PARTY, DependencyType.SOURCE_AND_THIRD_PARTY]:
        # TODO(John Sirois): We need an external payload abstraction at which point knowledge
        # of jar and requirement payloads can go and this hairball will be untangled.
        if isinstance(tgt.payload.get_field('requirements'), PythonRequirementsField):
          for requirement in tgt.payload.requirements:
            yield str(requirement.requirement)
        elif isinstance(tgt.payload.get_field('jars'), JarsField):
          for jar in tgt.payload.jars:
            data = dict(org=jar.org, name=jar.name, rev=jar.rev)
            yield ('{org}:{name}:{rev}' if jar.rev else '{org}:{name}').format(**data)
