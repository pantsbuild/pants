# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


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
                  "If true, act on the transitive dependency closure of those targets.",
             removal_version="1.25.0.dev2",
             removal_hint="Pants will soon remove the --fmt-transitive and --lint-transitive "
                          "options, which, when set, cause tools like isort and Scalafmt to work "
                          "on the transitive dependencies of the targets you specify, rather than "
                          "only the targets specified. Pants defaults to using this option, which "
                          "is unexpected. Normally when running tools like isort, you'd "
                          "expect them to only work on the files you specify.\n\nIf you "
                          "still need the behavior of --fmt-transitive or --lint-transitive, you "
                          "may use `./pants dependencies --transitive path/to:targets > out.txt`, "
                          "followed by `./pants --target-spec-file=out.txt fmt`.")


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
  pass


class HasSkipAndTransitiveGoalOptionsMixin(GoalOptionsMixin, HasSkipAndTransitiveOptionsMixin):
  """A mixin for tasks that have a --transitive and a --skip option registered at the goal level."""
  pass


class SkipAndTransitiveOptionsRegistrar(SkipOptionRegistrar, TransitiveOptionRegistrar):
  """Registrar of --skip and --transitive."""
  pass


class SkipAndTransitiveGoalOptionsRegistrar(SkipAndTransitiveOptionsRegistrar,
                                            GoalOptionsRegistrar):
  """Registrar of --skip and --transitive at the goal level."""
  pass
