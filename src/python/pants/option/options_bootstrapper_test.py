# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from functools import partial
from pathlib import Path
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.engine.unions import UnionMembership
from pants.option.option_value_container import OptionValueContainer
from pants.option.options_bootstrapper import OptionsBootstrapper, munge_bin_name
from pants.option.scope import ScopeInfo
from pants.util.contextutil import temporary_file, temporary_file_path
from pants.util.logging import LogLevel


class TestOptionsBootstrapper:
    @staticmethod
    def _config_path(path: str | None) -> list[str]:
        if path is None:
            return ["--pants-config-files=[]"]
        return [f"--pants-config-files=['{path}']"]

    def assert_bootstrap_options(
        self,
        *,
        config: dict[str, str] | None = None,
        env: dict[str, str] | None = None,
        args: list[str] | None = None,
        **expected_entries,
    ) -> None:
        with temporary_file(binary_mode=False) as fp:
            fp.write("[DEFAULT]\n")
            if config:
                for k, v in config.items():
                    fp.write(f"{k} = {repr(v)}\n")
            fp.close()

            args = [*self._config_path(fp.name), *(args or [])]
            bootstrapper = OptionsBootstrapper.create(env=env or {}, args=args, allow_pantsrc=False)
            vals = bootstrapper.get_bootstrap_options().for_global_scope()

        vals_dict = {k: getattr(vals, k) for k in expected_entries}
        assert expected_entries == vals_dict

    def test_bootstrap_seed_values(self) -> None:
        def assert_seed_values(
            *,
            config: dict[str, str] | None = None,
            env: dict[str, str] | None = None,
            args: list[str] | None = None,
            workdir: str | None = None,
            distdir: str | None = None,
        ) -> None:
            self.assert_bootstrap_options(
                config=config,
                env=env,
                args=args,
                pants_workdir=workdir or os.path.join(get_buildroot(), ".pants.d", "workdir"),
                pants_distdir=distdir or os.path.join(get_buildroot(), "dist"),
            )

        # Check for valid default seed values
        assert_seed_values()

        # Check getting values from config, env and args.
        assert_seed_values(
            config={"pants_workdir": "/from_config/.pants.d"},
            workdir="/from_config/.pants.d",
        )
        assert_seed_values(args=["--pants-distdir=/from_args/dist"], distdir="/from_args/dist")

        # Check that args > env > config.
        assert_seed_values(
            config={
                "pants_workdir": "/from_config/.pants.d",
                "pants_distdir": "/from_config/dist",
            },
            args=["--pants-distdir=/from_args/dist"],
            workdir="/from_config/.pants.d",
            distdir="/from_args/dist",
        )

        # Check that unrelated args and config don't confuse us.
        assert_seed_values(
            config={
                "pants_workdir": "/from_config/.pants.d",
                "pants_distdir": "/from_config/dist",
                "unrelated": "foo",
            },
            env={
                "PANTS_DISTDIR": "/from_env/dist",
                "PANTS_NO_RELATIONSHIP": "foo",
            },
            args=["--pants-distdir=/from_args/dist", "--foo=bar", "--baz"],
            workdir="/from_config/.pants.d",
            distdir="/from_args/dist",
        )

    def test_bootstrap_bool_option_values(self) -> None:
        # Check the default.
        self.assert_bootstrap_options(pantsrc=True)

        assert_pantsrc_is_false = partial(self.assert_bootstrap_options, pantsrc=False)
        assert_pantsrc_is_false(args=["--no-pantsrc"])
        assert_pantsrc_is_false(config={"pantsrc": "false"})
        assert_pantsrc_is_false(env={"PANTS_PANTSRC": "False"})

    def test_create_bootstrapped_options(self) -> None:
        # Check that we can set a bootstrap option from a cmd-line flag and have that interpolate
        # correctly into regular config.
        with temporary_file(binary_mode=False) as fp:
            fp.write(
                dedent(
                    """
                    [foo]
                    bar = "%(pants_workdir)s/baz"

                    [fruit]
                    apple = "%(pants_distdir)s/banana"
                    """
                )
            )
            fp.close()
            args = ["--pants-workdir=/qux"] + self._config_path(fp.name)
            bootstrapper = OptionsBootstrapper.create(
                env={"PANTS_DISTDIR": "/pear"}, args=args, allow_pantsrc=False
            )
            opts = bootstrapper.full_options_for_scopes(
                known_scope_infos=[
                    ScopeInfo(""),
                    ScopeInfo("foo"),
                    ScopeInfo("fruit"),
                ],
                union_membership=UnionMembership({}),
            )
            # So we don't choke on these on the cmd line.
            opts.register("", "--pants-workdir")
            opts.register("", "--pants-config-files")

            opts.register("foo", "--bar")
            opts.register("fruit", "--apple")
        assert "/qux/baz" == opts.for_scope("foo").bar
        assert "/pear/banana" == opts.for_scope("fruit").apple

    def test_bootstrapped_options_ignore_irrelevant_env(self) -> None:
        included = "PANTS_DISTDIR"
        excluded = "NON_PANTS_ENV"
        bootstrapper = OptionsBootstrapper.create(
            env={excluded: "pear", included: "banana"}, args=[], allow_pantsrc=False
        )
        assert included in bootstrapper.env
        assert excluded not in bootstrapper.env

    def test_create_bootstrapped_multiple_pants_config_files(self) -> None:
        """When given multiple config files, the later files should take precedence when options
        conflict."""

        def create_options_bootstrapper(*config_paths: str) -> OptionsBootstrapper:
            return OptionsBootstrapper.create(
                env={},
                args=[f"--pants-config-files={cp}" for cp in config_paths],
                allow_pantsrc=False,
            )

        def assert_config_read_correctly(
            options_bootstrapper: OptionsBootstrapper,
            *,
            expected_worker_count: int,
        ) -> None:
            options = options_bootstrapper.full_options_for_scopes(
                known_scope_infos=[
                    ScopeInfo(""),
                    ScopeInfo("compile_apt"),
                    ScopeInfo("fruit"),
                ],
                union_membership=UnionMembership({}),
            )
            # So we don't choke on these on the cmd line.
            options.register("", "--pants-config-files", type=list)
            options.register("", "--config-override", type=list)
            options.register("compile_apt", "--worker-count")
            options.register("fruit", "--apple")

            assert str(expected_worker_count) == options.for_scope("compile_apt").worker_count
            assert "red" == options.for_scope("fruit").apple

        with temporary_file(binary_mode=False) as fp1, temporary_file(binary_mode=False) as fp2:
            fp1.write(
                dedent(
                    """\
                    [compile_apt]
                    worker_count = 1

                    [fruit]
                    apple = "red"
                    """
                )
            )
            fp2.write(
                dedent(
                    """\
                    [compile_apt]
                    worker_count = 2
                    """
                )
            )
            fp1.close()
            fp2.close()

            assert_config_read_correctly(
                create_options_bootstrapper(fp1.name),
                expected_worker_count=1,
            )
            assert_config_read_correctly(
                create_options_bootstrapper(fp1.name, fp2.name),
                expected_worker_count=2,
            )
            assert_config_read_correctly(
                create_options_bootstrapper(fp2.name, fp1.name),
                expected_worker_count=1,
            )

    def test_options_pantsrc_files(self) -> None:
        def create_options_bootstrapper(*config_paths: str) -> OptionsBootstrapper:
            return OptionsBootstrapper.create(
                env={},
                args=[f"--pantsrc-files={cp}" for cp in config_paths],
                allow_pantsrc=True,
            )

        with temporary_file(binary_mode=False) as fp:
            fp.write(
                dedent(
                    """
                    [resolver]
                    resolver = "coursier"
                    """
                )
            )
            fp.close()
            bootstrapped_options = create_options_bootstrapper(fp.name)
            opts_single_config = bootstrapped_options.full_options_for_scopes(
                known_scope_infos=[
                    ScopeInfo(""),
                    ScopeInfo("resolver"),
                ],
                union_membership=UnionMembership({}),
            )
            opts_single_config.register("", "--pantsrc-files", type=list)
            opts_single_config.register("resolver", "--resolver")
            assert "coursier" == opts_single_config.for_scope("resolver").resolver

    def test_full_options_caching(self) -> None:
        with temporary_file_path() as config:
            args = self._config_path(config)
            bootstrapper = OptionsBootstrapper.create(env={}, args=args, allow_pantsrc=False)

            opts1 = bootstrapper.full_options_for_scopes(
                known_scope_infos=[
                    ScopeInfo(""),
                    ScopeInfo("foo"),
                ],
                union_membership=UnionMembership({}),
            )
            opts2 = bootstrapper.full_options_for_scopes(
                known_scope_infos=[
                    ScopeInfo("foo"),
                    ScopeInfo(""),
                ],
                union_membership=UnionMembership({}),
            )
            assert opts1 is opts2

            opts3 = bootstrapper.full_options_for_scopes(
                known_scope_infos=[
                    ScopeInfo(""),
                    ScopeInfo("foo"),
                    ScopeInfo(""),
                ],
                union_membership=UnionMembership({}),
            )
            assert opts1 is opts3

            opts4 = bootstrapper.full_options_for_scopes(
                known_scope_infos=[ScopeInfo("")],
                union_membership=UnionMembership({}),
            )
            assert opts1 is not opts4

            opts5 = bootstrapper.full_options_for_scopes(
                known_scope_infos=[ScopeInfo("")],
                union_membership=UnionMembership({}),
            )
            assert opts4 is opts5
            assert opts1 is not opts5

    def test_bootstrap_short_options(self) -> None:
        def parse_options(*args: str) -> OptionValueContainer:
            full_args = [*args, *self._config_path(None)]
            return (
                OptionsBootstrapper.create(env={}, args=full_args, allow_pantsrc=False)
                .get_bootstrap_options()
                .for_global_scope()
            )

        # No short options passed - defaults presented.
        vals = parse_options()
        assert vals.logdir is None
        assert LogLevel.INFO == vals.level

        # Unrecognized short options passed and ignored - defaults presented.
        vals = parse_options("-_UnderscoreValue", "-^")
        assert vals.logdir is None
        assert LogLevel.INFO == vals.level

        vals = parse_options("--logdir=/tmp/logs", "-ldebug")
        assert "/tmp/logs" == vals.logdir
        assert LogLevel.DEBUG == vals.level

    def test_bootstrap_options_passthrough_dup_ignored(self) -> None:
        def parse_options(*args: str) -> OptionValueContainer:
            full_args = [*args, *self._config_path(None)]
            return (
                OptionsBootstrapper.create(env={}, args=full_args, allow_pantsrc=False)
                .get_bootstrap_options()
                .for_global_scope()
            )

        vals = parse_options("main", "args", "-lwarn", "--", "-lerror")
        assert LogLevel.WARN == vals.level

        vals = parse_options("main", "args", "--", "-lerror")
        assert LogLevel.INFO == vals.level

    def test_bootstrap_options_explicit_config_path(self) -> None:
        def config_path(*args, **env):
            return OptionsBootstrapper.get_config_file_paths(env, args)

        assert ["/foo/bar/pants.toml"] == config_path(
            "main", "args", "--pants-config-files=['/foo/bar/pants.toml']"
        )

        assert ["/from/env1", "/from/env2"] == config_path(
            "main", "args", PANTS_CONFIG_FILES="['/from/env1', '/from/env2']"
        )

        assert ["/from/flag"] == config_path(
            "main",
            "args",
            "-x",
            "--pants-config-files=['/from/flag']",
            "goal",
            "--other-flag",
            PANTS_CONFIG_FILES="['/from/env']",
        )

        # Test appending to the default.
        assert [f"{get_buildroot()}/pants.toml", "/from/env", "/from/flag"] == config_path(
            "main",
            "args",
            "-x",
            "--pants-config-files=+['/from/flag']",
            "goal",
            "--other-flag",
            PANTS_CONFIG_FILES="+['/from/env']",
        )

        # Test replacing the default, then appending.
        assert ["/from/env", "/from/flag"] == config_path(
            "main",
            "args",
            "-x",
            "--pants-config-files=+['/from/flag']",
            "goal",
            "--other-flag",
            PANTS_CONFIG_FILES="['/from/env']",
        )

        assert ["/from/flag"] == config_path(
            "main",
            "args",
            "-x",
            "--pants-config-files=['/from/flag']",
            "goal",
            "--other-flag",
            PANTS_CONFIG_FILES="+['/from/env']",
        )

    def test_setting_pants_config_in_config(self, tmp_path: Path) -> None:
        # Test that setting pants_config in the config file has no effect.

        config1 = tmp_path / "config1"
        config2 = tmp_path / "config2"
        config1.write_text(f"[DEFAULT]\npants_config_files = ['{config2}']\nlogdir = 'logdir1'\n")
        config2.write_text("[DEFAULT]\nlogdir = 'logdir2'\n")

        ob = OptionsBootstrapper.create(
            env={}, args=[f"--pants-config-files=['{config1.as_posix()}']"], allow_pantsrc=False
        )
        logdir = ob.get_bootstrap_options().for_global_scope().logdir
        assert "logdir1" == logdir

    def test_alias(self, tmp_path: Path) -> None:
        config0 = tmp_path / "config0"
        config0.write_text(
            dedent(
                """\
                    [cli.alias]
                    pyupgrade = "--backend-packages=pants.backend.python.lint.pyupgrade fmt"
                    green = "lint test"
                    """
            )
        )

        config1 = tmp_path / "config1"
        config1.write_text(
            dedent(
                """\
                    [cli]
                    alias.add = {green = "lint test --force check"}
                    """
            )
        )

        config2 = tmp_path / "config2"
        config2.write_text(
            dedent(
                """\
                    [cli]
                    alias = "+{'shell': 'repl'}"
                    """
            )
        )

        config_arg = (
            f"--pants-config-files=["
            f"'{config0.as_posix()}','{config1.as_posix()}','{config2.as_posix()}']"
        )
        ob = OptionsBootstrapper.create(
            env={}, args=[config_arg, "pyupgrade", "green"], allow_pantsrc=False
        )
        assert (
            config_arg,
            "--backend-packages=pants.backend.python.lint.pyupgrade",
            "fmt",
            "lint",
            "test",
            "--force",
            "check",
        ) == ob.args
        assert (
            "<ignored>",
            config_arg,
            "--backend-packages=pants.backend.python.lint.pyupgrade",
        ) == ob.bootstrap_args

        ob = OptionsBootstrapper.create(env={}, args=[config_arg, "shell"], allow_pantsrc=False)
        assert (
            config_arg,
            "repl",
        ) == ob.args
        assert (
            "<ignored>",
            config_arg,
        ) == ob.bootstrap_args


def test_munge_bin_name():
    build_root = "/my/repo"

    def munge(bin_name: str) -> str:
        return munge_bin_name(bin_name, build_root)

    assert munge("pants") == "pants"
    assert munge("pantsv2") == "pantsv2"
    assert munge("bin/pantsv2") == "bin/pantsv2"
    assert munge("./pants") == "./pants"
    assert munge(os.path.join(build_root, "pants")) == "./pants"
    assert munge(os.path.join(build_root, "bin", "pants")) == "./bin/pants"
    assert munge("/foo/pants") == "pants"
    assert munge("/foo/bar/pants") == "pants"
