# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pants.base.build_environment import pants_version
from pants.base.exceptions import BuildConfigurationError
from pants.engine.unions import UnionMembership
from pants.option.global_options import BootstrapOptions, GlobalOptions
from pants.option.option_types import collect_options_info
from pants.option.options import Options
from pants.option.scope import GLOBAL_SCOPE, ScopeInfo
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized_method, memoized_property
from pants.util.strutil import softwrap

if TYPE_CHECKING:
    from pants.build_graph.build_configuration import BuildConfiguration


# TODO: Rebrand this. It isn't actually about "bootstrapping" any more (and the term
#  "bootstrap options" now means just "options needed to create a Scheduler").


@dataclass(frozen=True)
class OptionsBootstrapper:
    """Creates Options instances with appropriately registered options."""

    args: tuple[str, ...]
    env: FrozenDict[str, str]
    allow_pantsrc: bool

    def __repr__(self) -> str:
        # Bootstrap args are included in `args`. We also drop the first argument, which is the path
        # to `pants_loader.py`.
        args = list(self.args[1:])
        return f"OptionsBootstrapper(args={args}, env={self.env})"

    @classmethod
    def create(
        cls,
        *,
        args: Sequence[str],
        env: Mapping[str, str],
        allow_pantsrc: bool = True,
    ) -> OptionsBootstrapper:
        """Parses the minimum amount of configuration necessary to create an OptionsBootstrapper.

        :param args: An args array.
        :param env: An environment dictionary.
        :param allow_pantsrc: True to allow pantsrc files to be used. Unless tests are expecting to
            consume pantsrc files, they should pass False in order to avoid reading files from
            absolute paths. Production use-cases should pass True to allow options values to make
            the decision of whether to respect pantsrc files.
        """
        args = tuple(args)

        # TODO: We really only need the env vars starting with PANTS_, plus any env
        #  vars used in env.FOO-style interpolation in config files.
        #  Filtering to just those would allow OptionsBootstrapper to have a less
        #  unwieldy __str__.
        #  We used to filter all but PANTS_* (https://github.com/pantsbuild/pants/pull/7312),
        #  but we can't now because of env interpolation in the native config file parser.
        #  We can revisit this once the legacy python parser is no more, and we refactor
        #  the OptionsBootstrapper and/or convert it to Rust.
        return cls(
            args=args,
            env=FrozenDict(env),
            allow_pantsrc=allow_pantsrc,
        )

    @staticmethod
    def _create_bootstrap_options(
        args: Sequence[str], env: Mapping[str, str], allow_pantsrc: bool
    ) -> Options:
        """Create an Options instance containing just the bootstrap options.

        These are the options needed to create a scheduler.
        """
        ret = Options.create(
            args=args,
            env=env,
            config_sources=None,
            known_scope_infos=[GlobalOptions.get_scope_info()],
            allow_unknown_options=True,
            allow_pantsrc=allow_pantsrc,
        )
        for option_info in collect_options_info(BootstrapOptions):
            ret.register(GLOBAL_SCOPE, *option_info.args, **option_info.kwargs)
        return ret

    @memoized_property
    def bootstrap_options(self) -> Options:
        """An Options instance containing just the bootstrap options.

        These are the options needed to create a scheduler.
        """
        return self._create_bootstrap_options(self.args, self.env, self.allow_pantsrc)

    @memoized_method
    def _full_options(
        self,
        known_scope_infos: Sequence[ScopeInfo],
        union_membership: UnionMembership,
        allow_unknown_options: bool = False,
    ) -> Options:
        options = Options.create(
            args=self.args,
            env=self.env,
            config_sources=None,
            known_scope_infos=known_scope_infos,
            allow_unknown_options=allow_unknown_options,
            allow_pantsrc=self.allow_pantsrc,
        )

        distinct_subsystem_classes = set()
        for ksi in known_scope_infos:
            if ksi.subsystem_cls is not None:
                if ksi.subsystem_cls in distinct_subsystem_classes:
                    continue
                distinct_subsystem_classes.add(ksi.subsystem_cls)
                ksi.subsystem_cls.register_options_on_scope(options, union_membership)

        return options

    def full_options_for_scopes(
        self,
        known_scope_infos: Iterable[ScopeInfo],
        union_membership: UnionMembership,
        allow_unknown_options: bool = False,
    ) -> Options:
        """Get the full Options instance bootstrapped by this object for the given known scopes."""
        return self._full_options(
            tuple(sorted(set(known_scope_infos), key=lambda si: si.scope)),
            union_membership,
            allow_unknown_options=allow_unknown_options,
        )

    def full_options(
        self, build_configuration: BuildConfiguration, union_membership: UnionMembership
    ) -> Options:
        # Parse and register options.
        known_scope_infos = [
            subsystem.get_scope_info() for subsystem in build_configuration.all_subsystems
        ]
        options = self.full_options_for_scopes(
            known_scope_infos,
            union_membership,
            allow_unknown_options=build_configuration.allow_unknown_options,
        )

        global_options = options.for_global_scope()
        if global_options.pants_version != pants_version():
            raise BuildConfigurationError(
                softwrap(
                    f"""
                        Version mismatch: Requested version was {global_options.pants_version},
                        our version is {pants_version()}.
                        """
                )
            )
        GlobalOptions.validate_instance(options.for_global_scope())
        return options
