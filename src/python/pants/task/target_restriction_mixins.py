# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.deprecated import deprecated_conditional
from pants.task.goal_options_mixin import GoalOptionsMixin, GoalOptionsRegistrar


class HasTransitiveOptionMixin:
  """A mixin for tasks that have a --transitive option.

  Some tasks must always act on the entire dependency closure. E.g., when compiling, one must
  compile all of a target's dependencies before compiling that target.

  Other tasks must always act only on the target roots (the targets explicitly specified by the
  user on the command line). E.g., when finding paths between two user-specified targets.

  Still other tasks may optionally act on either the target roots or the entire closure,
  as the user prefers in each case. E.g., when invoking a linter. This mixin supports such tasks.

  Note that this mixin doesn't actually register the --transitive option. It assumes that this
  option was registered on the task (either directly or recursively from its goal).
  """

  @property
  def act_transitively(self):
    return self.get_options().transitive


class TransitiveOptionRegistrar:
  """Registrar of --transitive."""

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--transitive', type=bool, default=True, fingerprint=True, recursive=True,
             help="If false, act only on the targets directly specified on the command line. "
                  "If true, act on the transitive dependency closure of those targets.")


class HasSkipOptionMixin:
  """A mixin for tasks that have a --skip option.

  Some tasks may be skipped during certain usages. E.g., you may not want to apply linters
  while developing.  This mixin supports such tasks.

  Note that this mixin doesn't actually register the --skip option. It assumes that this
  option was registered on the task (either directly or recursively from its goal).
  """

  @property
  def skip_execution(self):
    return self.get_options().skip


class SkipOptionRegistrar:
  """Registrar of --skip."""

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--skip', type=bool, default=False, fingerprint=True, recursive=True,
             help='Skip task.')


class HasSkipAndTransitiveOptionsMixin(HasSkipOptionMixin, HasTransitiveOptionMixin):
  """A mixin for tasks that have a --transitive and a --skip option."""


class HasSkipAndTransitiveGoalOptionsMixin(GoalOptionsMixin, HasSkipAndTransitiveOptionsMixin):
  """A mixin for tasks that have a --transitive and a --skip option registered at the goal level."""


class SkipAndTransitiveOptionsRegistrar(SkipOptionRegistrar, TransitiveOptionRegistrar):
  """Registrar of --skip and --transitive."""


class SkipAndTransitiveGoalOptionsRegistrar(SkipAndTransitiveOptionsRegistrar,
                                            GoalOptionsRegistrar):
  """Registrar of --skip and --transitive at the goal level."""


# TODO: delete this class once we change the default of `--fmt-transitive` and `--lint-transitive`
# to False. Go back to using HasSkipAndTransitiveOptionsMixin.
class HasSkipAndDeprecatedTransitiveGoalOptionsMixin(GoalOptionsMixin, HasSkipAndTransitiveOptionsMixin):
  """A mixin for tasks that have a --transitive and a --skip option registered at the goal level."""

  @property
  def act_transitively(self):
    deprecated_conditional(
      lambda: self.get_options().is_default("transitive"),
      removal_version="1.25.0.dev2",
      entity_description="Pants defaulting to `--fmt-transitive` and `--lint-transitive`",
      hint_message="Pants will soon default to `--no-fmt-transitive` and `--no-lint-transitive`. "
                   "Currently, Pants defaults to `--fmt-transitive` and `--lint-transitive`, which "
                   "means that tools like isort and Scalafmt will work on transitive dependencies "
                   "as well. This behavior is unexpected. Normally when running tools like isort, "
                   "you'd expect them to only work on the files you specify.\n\nTo prepare, "
                   "please add to your `pants.ini` under both the `fmt` and the `lint` "
                   "sections the option `transitive: False`. If you want to keep the default, use "
                   "`True`, although we recommend setting to `False` as the `--transitive` option "
                   "will be removed in a future Pants version."
    )
    return self.get_options().transitive


class DeprecatedSkipAndDeprecatedTransitiveGoalOptionsRegistrar(GoalOptionsRegistrar):

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    # TODO: deprecate this option once the default for `--fmt-transitive` and `--lint-transitive`
    # changes.
    register(
      '--transitive', type=bool, default=True, fingerprint=True, recursive=True,
      help="If false, act only on the targets directly specified on the command line. "
           "If true, act on the transitive dependency closure of those targets.",
    )
    deprecated_skip_mapping = {
      'lint-checkstyle': 'checkstyle',
      'fmt-javascriptstyle': 'eslint',
      'lint-javascriptstyle': 'eslint',
      'fmt-go': 'gofmt',
      'lint-go': 'gofmt',
      'fmt-google-java-format': 'google-java-format',
      'lint-google-java-format': 'google-java-format',
      'fmt-isort': 'isort',
      'lint-mypy': 'mypy',
      'lint-python-eval': 'python-eval',
      'fmt-scalafix': 'scalafix',
      'lint-scalafix': 'scalafix',
      'fmt-scalafmt': 'scalafmt',
      'lint-scalafmt': 'scalafmt',
      'lint-scalastyle': 'scalastyle',
      'lint-thrift': 'scrooge-linter',
    }
    deprecated_skip_mapping_str = '\n'.join(
      f'* --{old}-skip -> --{new}-skip' for old, new in sorted(deprecated_skip_mapping.items())
    )
    skip_deprecation_message = (
      "`--fmt-skip` and `--lint-skip` are being replaced by options on the linters and formatters "
      "themselves. For example, `--fmt-isort-skip` is now `--isort-skip`.\n\nPlease use these new "
      f"options instead:\n\n{deprecated_skip_mapping_str}\n\nThere is no alternative for the "
      f"top-level `--fmt-skip` and `--lint-skip`. Instead, don't run "
      f"`./pants fmt` and `./pants lint`."
    )
    register(
      '--skip', type=bool, default=False, fingerprint=True, recursive=True,
      removal_version='1.27.0.dev0', removal_hint=skip_deprecation_message,
      help='Skip task.',
    )
