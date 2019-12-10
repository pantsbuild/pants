# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from twitter.common.collections import OrderedSet

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_target import JvmTarget
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
    register('--internal-only', type=bool,
             help='Specifies that only internal dependencies should be included in the graph '
                  'output (no external jars).')
    register(
      '--external-only',
      type=bool,
      help='Specifies that only external dependencies should be included in the graph output (only external jars).',
      removal_version="1.26.0.dev1",
      removal_hint="This feature is being removed. If you depend on this functionality, please let us know in the "
                   "#general channel on Slack at https://pantsbuild.slack.com/. \nYou can join the pants slack here: "
                   "https://pantsslack.herokuapp.com/ ",
    )

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

    self.is_internal_only = self.get_options().internal_only
    self.is_external_only = self.get_options().external_only
    if self.is_internal_only and self.is_external_only:
      raise TaskError('At most one of --internal-only or --external-only can be selected.')

  def console_output(self, unused_method_argument):
    deprecated_conditional(
      lambda: not self.is_external_only and not self.is_internal_only,
      removal_version="1.26.0.dev1",
      entity_description="The default dependencies output including external dependencies",
      hint_message="Pants will soon default to `--internal-only`, and remove the `--external-only` option. "
                    "Currently, Pants defaults to include both internal and external dependencies, which means this "
                    "task returns a mix of both target addresses and requirement strings."
                    "\n\nTo prepare, you can run this task with the `--internal-only` option. "
                    "If you need still need support for including external dependencies in the output, please let us "
                    "know in the #general channel on Slack at https://pantsbuild.slack.com/."
                    "\nYou can join the pants slack here: https://pantsslack.herokuapp.com/",
    )
    ordered_closure = OrderedSet()
    for target in self.context.target_roots:
      if self.act_transitively:
        target.walk(ordered_closure.add)
      else:
        ordered_closure.update(target.dependencies)

    for tgt in ordered_closure:
      if not self.is_external_only:
        yield tgt.address.spec
      if not self.is_internal_only:
        # TODO(John Sirois): We need an external payload abstraction at which point knowledge
        # of jar and requirement payloads can go and this hairball will be untangled.
        if isinstance(tgt.payload.get_field('requirements'), PythonRequirementsField):
          for requirement in tgt.payload.requirements:
            yield str(requirement.requirement)
        elif isinstance(tgt.payload.get_field('jars'), JarsField):
          for jar in tgt.payload.jars:
            data = dict(org=jar.org, name=jar.name, rev=jar.rev)
            yield ('{org}:{name}:{rev}' if jar.rev else '{org}:{name}').format(**data)
