# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Type

from pants.base.build_environment import get_default_pants_config_file
from pants.option.config import Config
from pants.option.custom_types import ListValueComponent
from pants.option.global_options import GlobalOptions
from pants.option.optionable import Optionable
from pants.option.options import Options
from pants.option.scope import GLOBAL_SCOPE, ScopeInfo
from pants.util.dirutil import read_file
from pants.util.memo import memoized_method, memoized_property
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import ensure_text


# This is a temporary hack that allows us to note the fact that we're in v2-exclusive mode
# in a static location, as soon as we know it. This way code that cannot access options
# can still use this information to customize behavior. Again, this is a temporary hack
# to provide a better v2 experience to users who are not (and possibly never have been)
# running v1, and should go away ASAP.
class IsV2Exclusive:
    def __init__(self):
        self._value = False

    def set(self):
        self._value = True

    def __bool__(self):
        return self._value


is_v2_exclusive = IsV2Exclusive()


@dataclass(frozen=True)
class OptionsBootstrapper:
    """Holds the result of the first stage of options parsing, and assists with parsing full
    options."""

    env_tuples: Tuple[Tuple[str, str], ...]
    bootstrap_args: Tuple[str, ...]
    args: Tuple[str, ...]
    config: Config

    @staticmethod
    def get_config_file_paths(env, args) -> List[str]:
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
            env=env, config=config, known_scope_infos=[GlobalOptions.get_scope_info()], args=args,
        )

        def register_global(*args, **kwargs):
            ## Only use of Options.register?
            bootstrap_options.register(GLOBAL_SCOPE, *args, **kwargs)

        GlobalOptions.register_bootstrap_options(register_global)
        opts = bootstrap_options.for_global_scope()
        if opts.v2 and not opts.v1 and opts.backend_packages == []:
            is_v2_exclusive.set()
        return bootstrap_options

    @classmethod
    def create(
        cls, env: Optional[Mapping[str, str]] = None, args: Optional[Sequence[str]] = None,
    ) -> "OptionsBootstrapper":
        """Parses the minimum amount of configuration necessary to create an OptionsBootstrapper.

        :param env: An environment dictionary, or None to use `os.environ`.
        :param args: An args array, or None to use `sys.argv`.
        """
        env = {
            k: v for k, v in (os.environ if env is None else env).items() if k.startswith("PANTS_")
        }
        args = tuple(sys.argv if args is None else args)

        flags = set()
        short_flags = set()

        # We can't use pants.engine.fs.FileContent here because it would cause a circular dep.
        @dataclass(frozen=True)
        class FileContent:
            path: str
            content: bytes

        def filecontent_for(path: str) -> FileContent:
            return FileContent(ensure_text(path), read_file(path, binary_mode=True),)

        def capture_the_flags(*args: str, **kwargs) -> None:
            for arg in args:
                flags.add(arg)
                if len(arg) == 2:
                    short_flags.add(arg)
                elif kwargs.get("type") == bool:
                    flags.add(f"--no-{arg[2:]}")

        GlobalOptions.register_bootstrap_options(capture_the_flags)

        def is_bootstrap_option(arg: str) -> bool:
            components = arg.split("=", 1)
            if components[0] in flags:
                return True
            for flag in short_flags:
                if arg.startswith(flag):
                    return True
            return False

        # Take just the bootstrap args, so we don't choke on other global-scope args on the cmd line.
        # Stop before '--' since args after that are pass-through and may have duplicate names to our
        # bootstrap options.
        bargs = tuple(
            filter(is_bootstrap_option, itertools.takewhile(lambda arg: arg != "--", args))
        )

        config_file_paths = cls.get_config_file_paths(env=env, args=args)
        config_files_products = [filecontent_for(p) for p in config_file_paths]
        pre_bootstrap_config = Config.load_file_contents(config_files_products)

        initial_bootstrap_options = cls.parse_bootstrap_options(env, bargs, pre_bootstrap_config)
        bootstrap_option_values = initial_bootstrap_options.for_global_scope()

        # Now re-read the config, post-bootstrapping. Note the order: First whatever we bootstrapped
        # from (typically pants.toml), then config override, then rcfiles.
        full_config_paths = pre_bootstrap_config.sources()
        if bootstrap_option_values.pantsrc:
            rcfiles = [
                os.path.expanduser(str(rcfile)) for rcfile in bootstrap_option_values.pantsrc_files
            ]
            existing_rcfiles = list(filter(os.path.exists, rcfiles))
            full_config_paths.extend(existing_rcfiles)

        full_config_files_products = [filecontent_for(p) for p in full_config_paths]
        post_bootstrap_config = Config.load_file_contents(
            full_config_files_products, seed_values=bootstrap_option_values.as_dict(),
        )

        env_tuples = tuple(sorted(env.items(), key=lambda x: x[0]))
        return cls(
            env_tuples=env_tuples, bootstrap_args=bargs, args=args, config=post_bootstrap_config
        )

    @memoized_property
    def env(self) -> Dict[str, str]:
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
    def _full_options(self, known_scope_infos: FrozenOrderedSet[ScopeInfo]) -> Options:
        bootstrap_option_values = self.get_bootstrap_options().for_global_scope()
        options = Options.create(
            self.env,
            self.config,
            known_scope_infos,
            args=self.args,
            bootstrap_option_values=bootstrap_option_values,
        )

        distinct_optionable_classes: Set[Type[Optionable]] = set()
        for ksi in known_scope_infos:
            if not ksi.optionable_cls or ksi.optionable_cls in distinct_optionable_classes:
                continue
            distinct_optionable_classes.add(ksi.optionable_cls)
            ksi.optionable_cls.register_options_on_scope(options)

        return options

    def get_full_options(self, known_scope_infos: Iterable[ScopeInfo]) -> Options:
        """Get the full Options instance bootstrapped by this object for the given known scopes.

        :param known_scope_infos: ScopeInfos for all scopes that may be encountered.
        :returns: A bootrapped Options instance that also carries options for all the supplied known
                  scopes.
        """
        return self._full_options(
            FrozenOrderedSet(sorted(known_scope_infos, key=lambda si: si.scope))
        )
