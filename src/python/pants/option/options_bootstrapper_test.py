# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import unittest
from functools import partial
from textwrap import dedent
from typing import Dict, List, Optional

from pants.base.build_environment import get_buildroot
from pants.option.option_value_container import OptionValueContainer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.scope import ScopeInfo
from pants.util.contextutil import temporary_dir, temporary_file, temporary_file_path
from pants.util.logging import LogLevel


class OptionsBootstrapperTest(unittest.TestCase):
    def _config_path(self, path: Optional[str]) -> List[str]:
        if path is None:
            return ["--pants-config-files=[]"]
        return [f"--pants-config-files=['{path}']"]

    def assert_bootstrap_options(
        self,
        *,
        config: Optional[Dict[str, str]] = None,
        env: Optional[Dict[str, str]] = None,
        args: Optional[List[str]] = None,
        **expected_entries,
    ) -> None:
        with temporary_file(binary_mode=False) as fp:
            fp.write("[DEFAULT]\n")
            if config:
                for k, v in config.items():
                    fp.write(f"{k}: {v}\n")
            fp.close()

            args = [*self._config_path(fp.name), *(args or [])]
            bootstrapper = OptionsBootstrapper.create(env=env or {}, args=args)
            vals = bootstrapper.get_bootstrap_options().for_global_scope()

        vals_dict = {k: getattr(vals, k) for k in expected_entries}
        self.assertEqual(expected_entries, vals_dict)

    def test_bootstrap_seed_values(self) -> None:
        def assert_seed_values(
            *,
            config: Optional[Dict[str, str]] = None,
            env: Optional[Dict[str, str]] = None,
            args: Optional[List[str]] = None,
            workdir: Optional[str] = None,
            supportdir: Optional[str] = None,
            distdir: Optional[str] = None,
        ) -> None:
            self.assert_bootstrap_options(
                config=config,
                env=env,
                args=args,
                pants_workdir=workdir or os.path.join(get_buildroot(), ".pants.d"),
                pants_supportdir=supportdir or os.path.join(get_buildroot(), "build-support"),
                pants_distdir=distdir or os.path.join(get_buildroot(), "dist"),
            )

        # Check for valid default seed values
        assert_seed_values()

        # Check getting values from config, env and args.
        assert_seed_values(
            config={"pants_workdir": "/from_config/.pants.d"}, workdir="/from_config/.pants.d",
        )
        assert_seed_values(
            env={"PANTS_SUPPORTDIR": "/from_env/build-support"},
            supportdir="/from_env/build-support",
        )
        assert_seed_values(args=["--pants-distdir=/from_args/dist"], distdir="/from_args/dist")

        # Check that args > env > config.
        assert_seed_values(
            config={
                "pants_workdir": "/from_config/.pants.d",
                "pants_supportdir": "/from_config/build-support",
                "pants_distdir": "/from_config/dist",
            },
            env={"PANTS_SUPPORTDIR": "/from_env/build-support", "PANTS_DISTDIR": "/from_env/dist"},
            args=["--pants-distdir=/from_args/dist"],
            workdir="/from_config/.pants.d",
            supportdir="/from_env/build-support",
            distdir="/from_args/dist",
        )

        # Check that unrelated args and config don't confuse us.
        assert_seed_values(
            config={
                "pants_workdir": "/from_config/.pants.d",
                "pants_supportdir": "/from_config/build-support",
                "pants_distdir": "/from_config/dist",
                "unrelated": "foo",
            },
            env={
                "PANTS_SUPPORTDIR": "/from_env/build-support",
                "PANTS_DISTDIR": "/from_env/dist",
                "PANTS_NO_RELATIONSHIP": "foo",
            },
            args=["--pants-distdir=/from_args/dist", "--foo=bar", "--baz"],
            workdir="/from_config/.pants.d",
            supportdir="/from_env/build-support",
            distdir="/from_args/dist",
        )

    def test_bootstrap_bool_option_values(self) -> None:
        # Check the default.
        self.assert_bootstrap_options(pantsrc=True)

        assert_pantsrc_is_false = partial(self.assert_bootstrap_options, pantsrc=False)
        assert_pantsrc_is_false(args=["--no-pantsrc"])
        assert_pantsrc_is_false(config={"pantsrc": False})
        assert_pantsrc_is_false(env={"PANTS_PANTSRC": "False"})

    def test_create_bootstrapped_options(self) -> None:
        # Check that we can set a bootstrap option from a cmd-line flag and have that interpolate
        # correctly into regular config.
        with temporary_file(binary_mode=False) as fp:
            fp.write(
                dedent(
                    """
                    [foo]
                    bar: %(pants_workdir)s/baz

                    [fruit]
                    apple: %(pants_supportdir)s/banana
                    """
                )
            )
            fp.close()
            args = ["--pants-workdir=/qux"] + self._config_path(fp.name)
            bootstrapper = OptionsBootstrapper.create(env={"PANTS_SUPPORTDIR": "/pear"}, args=args)
            opts = bootstrapper.get_full_options(
                known_scope_infos=[
                    ScopeInfo("", ScopeInfo.GLOBAL),
                    ScopeInfo("foo", ScopeInfo.TASK),
                    ScopeInfo("fruit", ScopeInfo.TASK),
                ]
            )
            # So we don't choke on these on the cmd line.
            opts.register("", "--pants-workdir")
            opts.register("", "--pants-config-files")

            opts.register("foo", "--bar")
            opts.register("fruit", "--apple")
        self.assertEqual("/qux/baz", opts.for_scope("foo").bar)
        self.assertEqual("/pear/banana", opts.for_scope("fruit").apple)

    def test_bootstrapped_options_ignore_irrelevant_env(self) -> None:
        included = "PANTS_SUPPORTDIR"
        excluded = "NON_PANTS_ENV"
        bootstrapper = OptionsBootstrapper.create(env={excluded: "pear", included: "banana"})
        self.assertIn(included, bootstrapper.env)
        self.assertNotIn(excluded, bootstrapper.env)

    def test_create_bootstrapped_multiple_pants_config_files(self) -> None:
        """When given multiple config files, the later files should take precedence when options
        conflict."""

        def create_options_bootstrapper(*config_paths: str) -> OptionsBootstrapper:
            return OptionsBootstrapper.create(
                args=[f"--pants-config-files={cp}" for cp in config_paths]
            )

        def assert_config_read_correctly(
            options_bootstrapper: OptionsBootstrapper, *, expected_worker_count: int,
        ) -> None:
            options = options_bootstrapper.get_full_options(
                known_scope_infos=[
                    ScopeInfo("", ScopeInfo.GLOBAL),
                    ScopeInfo("compile.apt", ScopeInfo.TASK),
                    ScopeInfo("fruit", ScopeInfo.TASK),
                ],
            )
            # So we don't choke on these on the cmd line.
            options.register("", "--pants-config-files", type=list)
            options.register("", "--config-override", type=list)
            options.register("compile.apt", "--worker-count")
            options.register("fruit", "--apple")

            self.assertEqual(
                str(expected_worker_count), options.for_scope("compile.apt").worker_count
            )
            self.assertEqual("red", options.for_scope("fruit").apple)

        with temporary_file(binary_mode=False) as fp1, temporary_file(binary_mode=False) as fp2:
            fp1.write(
                dedent(
                    """\
                    [compile.apt]
                    worker_count: 1

                    [fruit]
                    apple: red
                    """
                )
            )
            fp2.write(
                dedent(
                    """\
                    [compile.apt]
                    worker_count: 2
                    """
                )
            )
            fp1.close()
            fp2.close()

            assert_config_read_correctly(
                create_options_bootstrapper(fp1.name), expected_worker_count=1,
            )
            assert_config_read_correctly(
                create_options_bootstrapper(fp1.name, fp2.name), expected_worker_count=2,
            )
            assert_config_read_correctly(
                create_options_bootstrapper(fp2.name, fp1.name), expected_worker_count=1,
            )

    def test_options_pantsrc_files(self) -> None:
        def create_options_bootstrapper(*config_paths: str) -> OptionsBootstrapper:
            return OptionsBootstrapper.create(args=[f"--pantsrc-files={cp}" for cp in config_paths])

        with temporary_file(binary_mode=False) as fp:
            fp.write(
                dedent(
                    """
                    [resolver]
                    resolver: coursier
                    """
                )
            )
            fp.close()
            bootstrapped_options = create_options_bootstrapper(fp.name)
            opts_single_config = bootstrapped_options.get_full_options(
                known_scope_infos=[
                    ScopeInfo("", ScopeInfo.GLOBAL),
                    ScopeInfo("resolver", ScopeInfo.TASK),
                ]
            )
            opts_single_config.register("", "--pantsrc-files", type=list)
            opts_single_config.register("resolver", "--resolver")
            self.assertEqual("coursier", opts_single_config.for_scope("resolver").resolver)

    def test_full_options_caching(self) -> None:
        with temporary_file_path() as config:
            args = self._config_path(config)
            bootstrapper = OptionsBootstrapper.create(env={}, args=args)

            opts1 = bootstrapper.get_full_options(
                known_scope_infos=[
                    ScopeInfo("", ScopeInfo.GLOBAL),
                    ScopeInfo("foo", ScopeInfo.TASK),
                ]
            )
            opts2 = bootstrapper.get_full_options(
                known_scope_infos=[
                    ScopeInfo("foo", ScopeInfo.TASK),
                    ScopeInfo("", ScopeInfo.GLOBAL),
                ]
            )
            assert opts1 is opts2

            opts3 = bootstrapper.get_full_options(
                known_scope_infos=[
                    ScopeInfo("", ScopeInfo.GLOBAL),
                    ScopeInfo("foo", ScopeInfo.TASK),
                    ScopeInfo("", ScopeInfo.GLOBAL),
                ]
            )
            assert opts1 is opts3

            opts4 = bootstrapper.get_full_options(
                known_scope_infos=[ScopeInfo("", ScopeInfo.GLOBAL)]
            )
            assert opts1 is not opts4

            opts5 = bootstrapper.get_full_options(
                known_scope_infos=[ScopeInfo("", ScopeInfo.GLOBAL)]
            )
            assert opts4 is opts5
            assert opts1 is not opts5

    def test_bootstrap_short_options(self) -> None:
        def parse_options(*args: str) -> OptionValueContainer:
            full_args = [*args, *self._config_path(None)]
            return (
                OptionsBootstrapper.create(args=full_args)
                .get_bootstrap_options()
                .for_global_scope()
            )

        # No short options passed - defaults presented.
        vals = parse_options()
        self.assertIsNone(vals.logdir)
        self.assertEqual(LogLevel.INFO, vals.level)

        # Unrecognized short options passed and ignored - defaults presented.
        vals = parse_options("-_UnderscoreValue", "-^")
        self.assertIsNone(vals.logdir)
        self.assertEqual(LogLevel.INFO, vals.level)

        vals = parse_options("-d/tmp/logs", "-ldebug")
        self.assertEqual("/tmp/logs", vals.logdir)
        self.assertEqual(LogLevel.DEBUG, vals.level)

    def test_bootstrap_options_passthrough_dup_ignored(self) -> None:
        def parse_options(*args: str) -> OptionValueContainer:
            full_args = [*args, *self._config_path(None)]
            return (
                OptionsBootstrapper.create(args=full_args)
                .get_bootstrap_options()
                .for_global_scope()
            )

        vals = parse_options("main", "args", "-d/tmp/frogs", "--", "-d/tmp/logs")
        self.assertEqual("/tmp/frogs", vals.logdir)

        vals = parse_options("main", "args", "--", "-d/tmp/logs")
        self.assertIsNone(vals.logdir)

    def test_bootstrap_options_explicit_config_path(self) -> None:
        def config_path(*args, **env):
            return OptionsBootstrapper.get_config_file_paths(env, args)

        self.assertEqual(
            ["/foo/bar/pants.toml"],
            config_path("main", "args", "--pants-config-files=['/foo/bar/pants.toml']"),
        )

        self.assertEqual(
            ["/from/env1", "/from/env2"],
            config_path("main", "args", PANTS_CONFIG_FILES="['/from/env1', '/from/env2']"),
        )

        self.assertEqual(
            ["/from/flag"],
            config_path(
                "main",
                "args",
                "-x",
                "--pants-config-files=['/from/flag']",
                "goal",
                "--other-flag",
                PANTS_CONFIG_FILES="['/from/env']",
            ),
        )

        # Test appending to the default.
        self.assertEqual(
            [f"{get_buildroot()}/pants.toml", "/from/env", "/from/flag"],
            config_path(
                "main",
                "args",
                "-x",
                "--pants-config-files=+['/from/flag']",
                "goal",
                "--other-flag",
                PANTS_CONFIG_FILES="+['/from/env']",
            ),
        )

        # Test replacing the default, then appending.
        self.assertEqual(
            ["/from/env", "/from/flag"],
            config_path(
                "main",
                "args",
                "-x",
                "--pants-config-files=+['/from/flag']",
                "goal",
                "--other-flag",
                PANTS_CONFIG_FILES="['/from/env']",
            ),
        )

        self.assertEqual(
            ["/from/flag"],
            config_path(
                "main",
                "args",
                "-x",
                "--pants-config-files=['/from/flag']",
                "goal",
                "--other-flag",
                PANTS_CONFIG_FILES="+['/from/env']",
            ),
        )

    def test_setting_pants_config_in_config(self) -> None:
        # Test that setting pants_config in the config file has no effect.
        with temporary_dir() as tmpdir:
            config1 = os.path.join(tmpdir, "config1")
            config2 = os.path.join(tmpdir, "config2")
            with open(config1, "w") as out1:
                out1.write(f"[DEFAULT]\npants_config_files: ['{config2}']\nlogdir: logdir1\n")
            with open(config2, "w") as out2:
                out2.write("[DEFAULT]\nlogdir: logdir2\n")

            ob = OptionsBootstrapper.create(env={}, args=[f"--pants-config-files=['{config1}']"])
            logdir = ob.get_bootstrap_options().for_global_scope().logdir
            self.assertEqual("logdir1", logdir)
