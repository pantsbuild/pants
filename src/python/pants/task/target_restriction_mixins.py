# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.deprecated import resolve_conflicting_options
from pants.subsystem.subsystem import Subsystem
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
        register(
            "--transitive",
            type=bool,
            default=True,
            fingerprint=True,
            recursive=True,
            help="If false, act only on the targets directly specified on the command line. "
            "If true, act on the transitive dependency closure of those targets.",
        )


class HasSkipOptionMixin:
    """A mixin for tasks that have a --skip option.

    Some tasks may be skipped during certain usages. E.g., you may not want to apply linters
    while developing.  This mixin supports such tasks.

    Note that this mixin doesn't actually register the --skip option. It assumes that this
    option was registered on the task (either directly or recursively from its goal).
    """

    @property
    def skip_execution(self):
        return self.resolve_only_as_skip(self.get_options().skip)

    def resolve_only_as_skip(self, skip: bool):
        # This flag is defined only on fmt, which is done in FmtTaskMixin.
        # In v2, we expect to have a --only flag on both fmt and lint which will allow individual
        # formatters to be selected.
        #
        # This is a hacky one-off implementation to help Twitter deal with the fact that they have a
        # custom Goal called scalafix, which does the equivalent of `fmt --fmt-only=scalafix`, as it
        # provides them with a forward-compatible way of migrating people off of their scalafix goal.
        #
        # When the v2 goal is renamed from fmt2 to fmt, this option should be moved to that Goal, and
        # its implementation broadened to support all v2 formatters, as well as any v1 formatters we
        # fancy while we keep them around.
        #
        # Skip mypy because this is a temporary hack, and mypy doesn't follow the inheritance chain
        # properly.
        options = self.get_options()  # type: ignore
        if hasattr(options, "only"):
            only = options.only
            if only is None:
                return skip
            elif only == "scalafix":
                only_resolved_as_skip = not self.__class__.__name__.startswith("ScalaFix")
                if skip and not only_resolved_as_skip:
                    raise ValueError(
                        f"Invalid flag combination; cannot specify --only={only} if --skip=True",
                    )
                return only_resolved_as_skip
            else:
                raise ValueError(
                    "Invalid value for flag --only - must be scalafix or not set at all"
                )
        return skip

    def resolve_conflicting_skip_options(
        self, old_scope: str, new_scope: str, subsystem: Subsystem
    ):
        skip = resolve_conflicting_options(
            old_option="skip",
            new_option="skip",
            old_scope=old_scope,
            new_scope=new_scope,
            # Skip mypy because this is a temporary hack, and mypy doesn't follow the inheritance chain
            # properly.
            old_container=self.get_options(),  # type: ignore
            new_container=subsystem.options,
        )
        return self.resolve_only_as_skip(skip)


class SkipOptionRegistrar:
    """Registrar of --skip."""

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip", type=bool, default=False, fingerprint=True, recursive=True, help="Skip task."
        )


class HasSkipGoalOptionMixin(GoalOptionsMixin, HasSkipOptionMixin):
    """A mixin for tasks that have a --skip option registered at the goal level."""


class HasSkipAndTransitiveOptionsMixin(HasSkipOptionMixin, HasTransitiveOptionMixin):
    """A mixin for tasks that have a --transitive and a --skip option."""


class HasSkipAndTransitiveGoalOptionsMixin(GoalOptionsMixin, HasSkipAndTransitiveOptionsMixin):
    """A mixin for tasks that have a --transitive and a --skip option registered at the goal
    level."""


class SkipAndTransitiveOptionsRegistrar(SkipOptionRegistrar, TransitiveOptionRegistrar):
    """Registrar of --skip and --transitive."""


class SkipAndTransitiveGoalOptionsRegistrar(
    SkipAndTransitiveOptionsRegistrar, GoalOptionsRegistrar
):
    """Registrar of --skip and --transitive at the goal level."""


class DeprecatedSkipGoalOptionsRegistrar(GoalOptionsRegistrar):
    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        deprecated_skip_mapping = {
            "lint-checkstyle": "checkstyle",
            "fmt-javascriptstyle": "eslint",
            "lint-javascriptstyle": "eslint",
            "fmt-go": "gofmt",
            "lint-go": "gofmt",
            "fmt-google-java-format": "google-java-format",
            "lint-google-java-format": "google-java-format",
            "fmt-isort": "isort",
            "lint-mypy": "mypy",
            "lint-pythonstyle": "pycheck",
            "lint-python-eval": "python-eval",
            "fmt-scalafix": "scalafix",
            "lint-scalafix": "scalafix",
            "fmt-scalafmt": "scalafmt",
            "lint-scalafmt": "scalafmt",
            "lint-scalastyle": "scalastyle",
            "lint-thrift": "scrooge-linter",
        }
        deprecated_skip_mapping_str = "\n".join(
            f"* --{old}-skip -> --{new}-skip"
            for old, new in sorted(deprecated_skip_mapping.items())
        )
        skip_deprecation_message = (
            "`--fmt-skip` and `--lint-skip` are being replaced by options on the linters and formatters "
            "themselves. For example, `--fmt-isort-skip` is now `--isort-skip`.\n\nPlease use these new "
            f"options instead:\n\n{deprecated_skip_mapping_str}\n\nThere is no alternative for the "
            f"top-level `--fmt-skip` and `--lint-skip`. Instead, don't run "
            f"`./pants fmt` and `./pants lint`."
        )
        register(
            "--skip",
            type=bool,
            default=False,
            fingerprint=True,
            recursive=True,
            removal_version="1.27.0.dev0",
            removal_hint=skip_deprecation_message,
            help="Skip task.",
        )
