# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Mapping, Sequence

from pants.base.build_environment import get_buildroot, get_default_pants_config_file, pants_version
from pants.base.exceptions import BuildConfigurationError
from pants.engine.unions import UnionMembership
from pants.option.alias import CliAlias
from pants.option.config import Config
from pants.option.custom_types import DictValueComponent, ListValueComponent
from pants.option.global_options import BootstrapOptions, GlobalOptions
from pants.option.option_types import collect_options_info
from pants.option.options import NativeOptionsValidation, Options
from pants.option.scope import GLOBAL_SCOPE, ScopeInfo
from pants.option.subsystem import Subsystem
from pants.util.dirutil import read_file
from pants.util.memo import memoized_method, memoized_property
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import ensure_text, softwrap

if TYPE_CHECKING:
    from pants.build_graph.build_configuration import BuildConfiguration


@dataclass(frozen=True)
class OptionsBootstrapper:
    """Holds the result of the first stage of options parsing, and assists with parsing full
    options."""

    env_tuples: tuple[tuple[str, str], ...]
    bootstrap_args: tuple[str, ...]
    args: tuple[str, ...]
    config: Config
    alias: CliAlias

    def __repr__(self) -> str:
        env = {pair[0]: pair[1] for pair in self.env_tuples}
        # Bootstrap args are included in `args`. We also drop the first argument, which is the path
        # to `pants_loader.py`.
        args = list(self.args[1:])
        return f"OptionsBootstrapper(args={args}, env={env}, config={self.config})"

    @staticmethod
    def get_config_file_paths(env, args) -> list[str]:
        """Get the location of the config files.

        The locations are specified by the --pants-config-files option.  However we need to load the
        config in order to process the options.  This method special-cases --pants-config-files
        in order to solve this chicken-and-egg problem.

        Note that, obviously, it's not possible to set the location of config files in a config file.
        Doing so will have no effect.
        """
        # This exactly mirrors the logic applied in Option to all regular options.  Note that we'll
        # also parse --pants-config as a regular option later, but there's no harm in that.  In fact,
        # it's preferable, so that any code that happens to want to know where we read config from
        # can inspect the option.
        flag = "--pants-config-files="
        evars = [
            "PANTS_GLOBAL_PANTS_CONFIG_FILES",
            "PANTS_PANTS_CONFIG_FILES",
            "PANTS_CONFIG_FILES",
        ]

        path_list_values = []
        default = get_default_pants_config_file()
        if Path(default).is_file():
            path_list_values.append(ListValueComponent.create(default))
        for var in evars:
            if var in env:
                path_list_values.append(ListValueComponent.create(env[var]))
                break

        for arg in args:
            # Technically this is very slightly incorrect, as we don't check scope.  But it's
            # very unlikely that any task or subsystem will have an option named --pants-config-files.
            # TODO: Enforce a ban on options with a --pants- prefix outside our global options?
            if arg.startswith(flag):
                path_list_values.append(ListValueComponent.create(arg[len(flag) :]))

        return ListValueComponent.merge(path_list_values).val

    @staticmethod
    def parse_bootstrap_options(
        env: Mapping[str, str], args: Sequence[str], config: Config
    ) -> Options:
        bootstrap_options = Options.create(
            env=env,
            config=config,
            known_scope_infos=[GlobalOptions.get_scope_info()],
            args=args,
            # We ignore validation to ensure bootstrapping succeeds.
            # The bootstrap options will be validated anyway when we parse the full options.
            native_options_validation=NativeOptionsValidation.ignore,
            native_options_config_discovery=False,
        )

        for options_info in collect_options_info(BootstrapOptions):
            # Only use of Options.register?
            bootstrap_options.register(
                GLOBAL_SCOPE, *options_info.flag_names, **options_info.flag_options
            )

        return bootstrap_options

    @classmethod
    def create(
        cls, env: Mapping[str, str], args: Sequence[str], *, allow_pantsrc: bool
    ) -> OptionsBootstrapper:
        """Parses the minimum amount of configuration necessary to create an OptionsBootstrapper.

        :param env: An environment dictionary.
        :param args: An args array.
        :param allow_pantsrc: True to allow pantsrc files to be used. Unless tests are expecting to
          consume pantsrc files, they should pass False in order to avoid reading files from
          absolute paths. Production use-cases should pass True to allow options values to make the
          decision of whether to respect pantsrc files.
        """
        with warnings.catch_warnings(record=True):
            # We can't use pants.engine.fs.FileContent here because it would cause a circular dep.
            @dataclass(frozen=True)
            class FileContent:
                path: str
                content: bytes

            def filecontent_for(path: str) -> FileContent:
                return FileContent(
                    ensure_text(path),
                    read_file(path, binary_mode=True),
                )

            bargs = cls._get_bootstrap_args(args)

            config_file_paths = cls.get_config_file_paths(env=env, args=args)
            config_files_products = [filecontent_for(p) for p in config_file_paths]
            pre_bootstrap_config = Config.load(config_files_products, env=env)

            initial_bootstrap_options = cls.parse_bootstrap_options(
                env, bargs, pre_bootstrap_config
            )
            bootstrap_option_values = initial_bootstrap_options.for_global_scope()

            # Now re-read the config, post-bootstrapping. Note the order: First whatever we bootstrapped
            # from (typically pants.toml), then config override, then rcfiles.
            full_config_sources = pre_bootstrap_config.sources()
            if allow_pantsrc and bootstrap_option_values.pantsrc:
                rcfiles = [
                    os.path.expanduser(str(rcfile))
                    for rcfile in bootstrap_option_values.pantsrc_files
                ]
                existing_rcfiles = [filecontent_for(p) for p in filter(os.path.exists, rcfiles)]
                full_config_sources.extend(existing_rcfiles)

            post_bootstrap_config = Config.load(
                full_config_sources,
                seed_values=bootstrap_option_values.as_dict(),
                env=env,
            )

            # Finally, we expand any aliases and re-populate the bootstrap args, in case there
            # were any from aliases.
            # stuhood: This could potentially break the rust client when aliases are used:
            # https://github.com/pantsbuild/pants/pull/13228#discussion_r728223889
            alias_vals = post_bootstrap_config.get("cli", "alias")
            val = DictValueComponent.merge([DictValueComponent.create(v) for v in alias_vals]).val
            alias = CliAlias.from_dict(val)

            args = alias.expand_args(tuple(args))
            bargs = cls._get_bootstrap_args(args)

            # We need to set this env var to allow various static help strings to reference the
            # right name (via `pants.util.docutil`), and we need to do it as early as possible to
            # avoid needing to lazily import code to avoid chicken-and-egg-problems. This is the
            # earliest place it makes sense to do so and is generically used by both the local and
            # remote pants runners.
            os.environ["__PANTS_BIN_NAME"] = munge_bin_name(
                bootstrap_option_values.pants_bin_name, get_buildroot()
            )

            # TODO: We really only need the env vars starting with PANTS_, plus any env
            #  vars used in env.FOO-style interpolation in config files.
            #  Filtering to just those would allow OptionsBootstrapper to have a less
            #  unwieldy __str__.
            #  We used to filter all but PANTS_* (https://github.com/pantsbuild/pants/pull/7312),
            #  but we can't now because of env interpolation in the native config file parser.
            #  We can revisit this once the legacy python parser is no more, and we refactor
            #  the OptionsBootstrapper and/or convert it to Rust.
            env_tuples = tuple(sorted(env.items()))
            return cls(
                env_tuples=env_tuples,
                bootstrap_args=bargs,
                args=args,
                config=post_bootstrap_config,
                alias=alias,
            )

    @classmethod
    def _get_bootstrap_args(cls, args: Sequence[str]) -> tuple[str, ...]:
        # TODO(13244): there is a typing issue with `memoized_classmethod`.
        options = GlobalOptions.get_options_flags()  # type: ignore[call-arg]

        def is_bootstrap_option(arg: str) -> bool:
            components = arg.split("=", 1)
            if components[0] in options.flags:
                return True
            for flag in options.short_flags:
                if arg.startswith(flag):
                    return True
            return False

        # Take just the bootstrap args, so we don't choke on other global-scope args on the cmd line.
        # Stop before '--' since args after that are pass-through and may have duplicate names to our
        # bootstrap options.
        bargs = ("<ignored>",) + tuple(
            filter(is_bootstrap_option, itertools.takewhile(lambda arg: arg != "--", args))
        )
        return bargs

    @memoized_property
    def env(self) -> dict[str, str]:
        return dict(self.env_tuples)

    @memoized_property
    def bootstrap_options(self) -> Options:
        """The post-bootstrap options, computed from the env, args, and fully discovered Config.

        Re-computing options after Config has been fully expanded allows us to pick up bootstrap values
        (such as backends) from a config override file, for example.

        Because this can be computed from the in-memory representation of these values, it is not part
        of the object's identity.
        """
        return self.parse_bootstrap_options(self.env, self.bootstrap_args, self.config)

    def get_bootstrap_options(self) -> Options:
        """Returns an Options instance that only knows about the bootstrap options."""
        return self.bootstrap_options

    @memoized_method
    def _full_options(
        self,
        known_scope_infos: FrozenOrderedSet[ScopeInfo],
        union_membership: UnionMembership,
        allow_unknown_options: bool = False,
    ) -> Options:
        bootstrap_option_values = self.get_bootstrap_options().for_global_scope()
        options = Options.create(
            self.env,
            self.config,
            known_scope_infos,
            args=self.args,
            bootstrap_option_values=bootstrap_option_values,
            allow_unknown_options=allow_unknown_options,
            native_options_validation=bootstrap_option_values.native_options_validation,
        )

        distinct_subsystem_classes: set[type[Subsystem]] = set()
        for ksi in known_scope_infos:
            if not ksi.subsystem_cls or ksi.subsystem_cls in distinct_subsystem_classes:
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
        """Get the full Options instance bootstrapped by this object for the given known scopes.

        :param known_scope_infos: ScopeInfos for all scopes that may be encountered.
        :returns: A bootstrapped Options instance that also carries options for all the supplied known
                  scopes.
        """
        return self._full_options(
            FrozenOrderedSet(sorted(known_scope_infos, key=lambda si: si.scope)),
            union_membership,
            allow_unknown_options=allow_unknown_options,
        )

    def full_options(
        self, build_configuration: BuildConfiguration, union_membership: UnionMembership
    ) -> Options:
        global_bootstrap_options = self.get_bootstrap_options().for_global_scope()
        if global_bootstrap_options.pants_version != pants_version():
            raise BuildConfigurationError(
                softwrap(
                    f"""
                    Version mismatch: Requested version was {global_bootstrap_options.pants_version},
                    our version is {pants_version()}.
                    """
                )
            )

        # Parse and register options.
        known_scope_infos = [
            subsystem.get_scope_info() for subsystem in build_configuration.all_subsystems
        ]
        options = self.full_options_for_scopes(
            known_scope_infos,
            union_membership,
            allow_unknown_options=build_configuration.allow_unknown_options,
        )
        GlobalOptions.validate_instance(options.for_global_scope())
        self.alias.check_name_conflicts(
            options.known_scope_to_info, options.known_scope_to_scoped_args
        )
        return options


def munge_bin_name(pants_bin_name: str, build_root: str) -> str:
    # Determine a useful bin name to embed in help strings.
    # The bin name gets embedded in help comments in generated lockfiles,
    # so we never want to use an abspath.
    if os.path.isabs(pants_bin_name):
        pants_bin_name = os.path.realpath(pants_bin_name)
        build_root = os.path.realpath(os.path.abspath(build_root))
        # If it's in the buildroot, use the relpath from there. Otherwise use the basename.
        pants_bin_relpath = os.path.relpath(pants_bin_name, build_root)
        if pants_bin_relpath.startswith(".."):
            pants_bin_name = os.path.basename(pants_bin_name)
        else:
            pants_bin_name = os.path.join(".", pants_bin_relpath)
    return pants_bin_name
