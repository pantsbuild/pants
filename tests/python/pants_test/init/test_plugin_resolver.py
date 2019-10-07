# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import time
import unittest
from contextlib import contextmanager
from textwrap import dedent

from parameterized import parameterized
from pex.crawler import Crawler
from pex.installer import EggInstaller, Packager, WheelInstaller
from pex.interpreter import PythonInterpreter
from pex.resolver import Unsatisfiable
from pkg_resources import Requirement, WorkingSet

from pants.init.plugin_resolver import PluginResolver
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_open, safe_rmtree, touch
from pants_test.interpreter_selection_utils import (
    PY_36,
    PY_37,
    python_interpreter_path,
    skip_unless_python36_and_python37_present,
)


req = Requirement.parse

INSTALLERS = [("sdist", Packager), ("egg", EggInstaller), ("whl", WheelInstaller)]


class PluginResolverTest(unittest.TestCase):
    @staticmethod
    def create_plugin(distribution_repo_dir, plugin, version=None, packager_cls=None):
        with safe_open(os.path.join(distribution_repo_dir, plugin, "setup.py"), "w") as fp:
            fp.write(
                dedent(
                    f"""
        from setuptools import setup


        setup(name="{plugin}", version="{version or '0.0.0'}")
      """
                )
            )
        packager_cls = packager_cls or Packager
        packager = packager_cls(
            source_dir=os.path.join(distribution_repo_dir, plugin),
            install_dir=distribution_repo_dir,
        )
        packager.run()

    @contextmanager
    def plugin_resolution(self, *, interpreter=None, chroot=None, plugins=None, packager_cls=None):
        @contextmanager
        def provide_chroot(existing):
            if existing:
                yield existing, False
            else:
                with temporary_dir() as new_chroot:
                    yield new_chroot, True

        with provide_chroot(chroot) as (root_dir, create_artifacts):
            env = {"PANTS_BOOTSTRAPDIR": root_dir}
            repo_dir = None
            if plugins:
                repo_dir = os.path.join(root_dir, "repo")
                env.update(
                    PANTS_PYTHON_REPOS_REPOS=f"[{repo_dir!r}]",
                    PANTS_PYTHON_REPOS_INDEXES="[]",
                    PANTS_PYTHON_SETUP_RESOLVER_CACHE_TTL="1",
                )
                plugin_list = []
                for plugin in plugins:
                    version = None
                    if isinstance(plugin, tuple):
                        plugin, version = plugin
                    plugin_list.append(f"{plugin}=={version}" if version else plugin)
                    if create_artifacts:
                        self.create_plugin(repo_dir, plugin, version, packager_cls=packager_cls)
                env["PANTS_PLUGINS"] = "[{}]".format(",".join(map(repr, plugin_list)))

            configpath = os.path.join(root_dir, "pants.ini")
            if create_artifacts:
                touch(configpath)
            args = [f"--pants-config-files=['{configpath}']"]

            options_bootstrapper = OptionsBootstrapper.create(env=env, args=args)
            plugin_resolver = PluginResolver(options_bootstrapper, interpreter=interpreter)
            cache_dir = plugin_resolver.plugin_cache_dir
            yield plugin_resolver.resolve(WorkingSet(entries=[])), root_dir, repo_dir, cache_dir

    def test_no_plugins(self):
        with self.plugin_resolution() as (working_set, _, _, _):
            self.assertEqual([], working_set.entries)

    @parameterized.expand(INSTALLERS)
    def test_plugins(self, unused_test_name, packager_cls):
        with self.plugin_resolution(
            plugins=[("jake", "1.2.3"), "jane"], packager_cls=packager_cls
        ) as (working_set, _, _, cache_dir):
            self.assertEqual(2, len(working_set.entries))

            dist = working_set.find(req("jake"))
            self.assertIsNotNone(dist)
            self.assertEqual(
                os.path.realpath(cache_dir), os.path.realpath(os.path.dirname(dist.location))
            )

            dist = working_set.find(req("jane"))
            self.assertIsNotNone(dist)
            self.assertEqual(
                os.path.realpath(cache_dir), os.path.realpath(os.path.dirname(dist.location))
            )

    @parameterized.expand(INSTALLERS)
    def test_exact_requirements(self, unused_test_name, packager_cls):
        with self.plugin_resolution(
            plugins=[("jake", "1.2.3"), ("jane", "3.4.5")], packager_cls=packager_cls
        ) as results:
            working_set, chroot, repo_dir, cache_dir = results

            self.assertEqual(2, len(working_set.entries))

            # Kill the repo source dir and re-resolve.  If the PluginResolver truly detects exact
            # requirements it should skip any resolves and load directly from the still in-tact cache.
            safe_rmtree(repo_dir)

            with self.plugin_resolution(
                chroot=chroot, plugins=[("jake", "1.2.3"), ("jane", "3.4.5")]
            ) as results2:
                working_set2, _, _, _ = results2

                self.assertEqual(working_set.entries, working_set2.entries)

    @parameterized.expand(INSTALLERS)
    @skip_unless_python36_and_python37_present
    def test_exact_requirements_interpreter_change(self, unused_test_name, packager_cls):
        python36 = PythonInterpreter.from_binary(python_interpreter_path(PY_36))
        python37 = PythonInterpreter.from_binary(python_interpreter_path(PY_37))

        with self.plugin_resolution(
            interpreter=python36,
            plugins=[("jake", "1.2.3"), ("jane", "3.4.5")],
            packager_cls=packager_cls,
        ) as results:
            working_set, chroot, repo_dir, cache_dir = results

            self.assertEqual(2, len(working_set.entries))

            safe_rmtree(repo_dir)
            with self.assertRaises(Unsatisfiable):
                with self.plugin_resolution(
                    interpreter=python37,
                    chroot=chroot,
                    plugins=[("jake", "1.2.3"), ("jane", "3.4.5")],
                ):
                    self.fail(
                        "Plugin re-resolution is expected for an incompatible interpreter and it is "
                        "expected to fail since we removed the dist `repo_dir` above."
                    )

            # But for a compatible interpreter the exact resolve results should be re-used and load
            # directly from the still in-tact cache.
            with self.plugin_resolution(
                interpreter=python36, chroot=chroot, plugins=[("jake", "1.2.3"), ("jane", "3.4.5")]
            ) as results2:
                working_set2, _, _, _ = results2

                self.assertEqual(working_set.entries, working_set2.entries)

    @parameterized.expand(INSTALLERS)
    def test_inexact_requirements(self, unused_test_name, packager_cls):
        with self.plugin_resolution(
            plugins=[("jake", "1.2.3"), "jane"], packager_cls=packager_cls
        ) as results:
            working_set, chroot, repo_dir, cache_dir = results

            self.assertEqual(2, len(working_set.entries))

            # Kill the cache and the repo source dir and wait past our 1s test TTL, if the PluginResolver
            # truly detects inexact plugin requirements it should skip perma-caching and fall through to
            # pex to a TLL expiry resolve and then fail.
            safe_rmtree(repo_dir)
            safe_rmtree(cache_dir)
            Crawler.reset_cache()
            time.sleep(1.5)

            with self.assertRaises(Unsatisfiable):
                with self.plugin_resolution(chroot=chroot, plugins=[("jake", "1.2.3"), "jane"]):
                    self.fail("Should not reach here, should raise first.")
