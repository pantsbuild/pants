# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import unittest.mock
from contextlib import contextmanager
from textwrap import dedent

from pants.base.exceptions import TaskError
from pants.build_graph.target import Target
from pants.testutil.task_test_base import TaskTestBase

from pants.contrib.node.subsystems.resolvers.node_preinstalled_module_resolver import (
    NodePreinstalledModuleResolver,
)
from pants.contrib.node.subsystems.resolvers.npm_resolver import NpmResolver
from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.targets.node_preinstalled_module import NodePreinstalledModule
from pants.contrib.node.targets.node_remote_module import NodeRemoteModule
from pants.contrib.node.tasks.node_paths import NodePaths, NodePathsLocal
from pants.contrib.node.tasks.node_resolve import NodeResolve


class NodeResolveTest(TaskTestBase):
    @classmethod
    def task_type(cls):
        return NodeResolve

    def setUp(self):
        super().setUp()
        NodeResolve.register_resolver_for_type(
            NodePreinstalledModule, NodePreinstalledModuleResolver
        )
        NodeResolve.register_resolver_for_type(NodeModule, NpmResolver)

    def tearDown(self):
        super().tearDown()
        NodeResolve._clear_resolvers()

    def wrap_context(self, context, product_types):
        for product_type in product_types:
            context.products.require_data(product_type)

    def test_register_resolver_for_type(self):
        NodeResolve._clear_resolvers()

        self.assertIsNone(NodeResolve._resolver_for_target(NodePreinstalledModule))
        self.assertIsNone(NodeResolve._resolver_for_target(NodeModule))

        node_preinstalled__module_target = self.make_target(
            spec=":empty_fake_node_preinstalled_module_target", target_type=NodePreinstalledModule
        )
        NodeResolve.register_resolver_for_type(
            NodePreinstalledModule, NodePreinstalledModuleResolver
        )
        self.assertEqual(
            NodePreinstalledModuleResolver,
            NodeResolve._resolver_for_target(node_preinstalled__module_target),
        )

        node_module_target = self.make_target(
            spec=":empty_fake_node_module_target", target_type=NodeModule
        )
        NodeResolve.register_resolver_for_type(NodeModule, NpmResolver)
        self.assertEqual(NpmResolver, NodeResolve._resolver_for_target(node_module_target))

    def test_product_types(self):
        self.assertEqual([NodePaths, NodePathsLocal], NodeResolve.product_types())

    def test_noop(self):
        task = self.create_task(self.context())
        task.execute()

    def test_noop_na(self):
        target = self.make_target(spec=":not_a_node_target", target_type=Target)
        task = self.create_task(self.context(target_roots=[target]))
        task.execute()

    def test_resolve_simple(self):
        typ = self.make_target(
            spec="3rdparty/node:typ", target_type=NodeRemoteModule, version="0.6.3"
        )
        self.create_file(
            "src/node/util/package.json",
            contents=dedent(
                """
                {
                  "name": "util",
                  "version": "0.0.1"
                }
                """
            ),
        )
        self.create_file(
            "src/node/util/util.js",
            contents=dedent(
                """
                var typ = require('typ');
                console.log("type of boolean is: " + typ.BOOLEAN);
                """
            ),
        )
        target = self.make_target(
            spec="src/node/util",
            target_type=NodeModule,
            sources=["util.js", "package.json"],
            dependencies=[typ],
        )

        context = self.context(
            target_roots=[target],
            options={
                "npm-resolver": {
                    "install_optional": False,
                    "force_option_override": False,
                    "install_production": False,
                    "force": False,
                    "frozen_lockfile": True,
                }
            },
        )
        self.wrap_context(context, [NodePaths])
        task = self.create_task(context)
        task.execute()

        node_paths = context.products.get_data(NodePaths)
        node_path = node_paths.node_path(target)
        self.assertIsNotNone(node_path)

        script_path = os.path.join(node_path, "util.js")
        out = task.node_distribution.node_command(args=[script_path]).check_output()
        self.assertIn("type of boolean is: boolean", out)

    def test_resolve_simple_graph(self):
        typ1 = self.make_target(
            spec="3rdparty/node:typ1",
            target_type=NodeRemoteModule,
            package_name="typ",
            version="0.6.x",
        )
        typ2 = self.make_target(
            spec="3rdparty/node:typ2",
            target_type=NodeRemoteModule,
            package_name="typ",
            version="0.6.1",
        )

        self.create_file(
            "src/node/util/package.json",
            contents=dedent(
                """
                {
                  "name": "util",
                  "version": "0.0.1"
                }
                """
            ),
        )
        self.create_file(
            "src/node/util/typ.js",
            contents=dedent(
                """
                var typ = require('typ');
                module.exports = {
                  BOOL: typ.BOOLEAN
                };
                """
            ),
        )
        util = self.make_target(
            spec="src/node/util",
            target_type=NodeModule,
            sources=["typ.js", "package.json"],
            dependencies=[typ1],
        )

        self.create_file(
            "src/node/leaf/package.json",
            contents=dedent(
                """
                {
                  "name": "leaf",
                  "version": "0.0.1"
                }
                """
            ),
        )
        self.create_file(
            "src/node/leaf/leaf.js",
            contents=dedent(
                """
                var typ = require('typ');
                var util_typ = require('util/typ');
                console.log("type of boolean is: " + typ.BOOLEAN);
                console.log("type of bool is: " + util_typ.BOOL);
                """
            ),
        )
        leaf = self.make_target(
            spec="src/node/leaf",
            target_type=NodeModule,
            sources=["leaf.js", "package.json"],
            dependencies=[util, typ2],
        )
        context = self.context(
            target_roots=[leaf],
            options={
                "npm-resolver": {
                    "install_optional": False,
                    "force_option_override": False,
                    "install_production": False,
                    "force": False,
                    "frozen_lockfile": True,
                }
            },
        )
        self.wrap_context(context, [NodePaths])
        task = self.create_task(context)
        task.execute()

        node_paths = context.products.get_data(NodePaths)

        self.assertIsNotNone(node_paths.node_path(util))

        node_path = node_paths.node_path(leaf)
        self.assertIsNotNone(node_paths.node_path(leaf))

        # Verify the 'typ' package is not duplicated under leaf. The target dependency tree is:
        # leaf
        #   typ2 (0.6.1)
        #   util
        #     typ1 (0.6.x)
        # If we install leaf normally, NPM will install the typ2 target (typ version 0.6.1) at the top
        # level under leaf, and then not install the typ1 target (typ version 0.6.x) under util
        # because the dependency is already satisfied.
        typ_packages = []
        for root, _, files in os.walk(node_path):
            for f in files:
                if "package.json" == f:
                    with open(os.path.join(root, f), "r") as fp:
                        package = json.load(fp)
                        if "typ" == package["name"]:
                            typ_packages.append(os.path.relpath(os.path.join(root, f), node_path))
                            self.assertEqual(
                                1,
                                len(typ_packages),
                                "Expected to find exactly 1 de-duped `typ` package, but found these:"
                                "\n\t{}".format("\n\t".join(sorted(typ_packages))),
                            )

        script_path = os.path.join(node_path, "leaf.js")
        out = task.node_distribution.node_command(args=[script_path]).check_output()
        lines = {line.strip() for line in out.splitlines()}
        self.assertIn("type of boolean is: boolean", lines)
        self.assertIn("type of bool is: boolean", lines)

    def test_resolve_preserves_package_json(self):
        self.create_file(
            "src/node/util/package.json",
            contents=dedent(
                """
                {
                  "name": "util",
                  "version": "0.0.1"
                }
                """
            ),
        )
        util = self.make_target(
            spec="src/node/util", target_type=NodeModule, sources=["package.json"], dependencies=[]
        )

        self.create_file(
            "src/node/scripts_project/package.json",
            contents=dedent(
                """
                {
                  "name": "scripts_project",
                  "version": "1.2.3",
                  "dependencies": { "A": "file://A" },
                  "devDependencies": { "B": "file://B" },
                  "peerDependencies": { "C": "file://C" },
                  "optionalDependencies": { "D": "file://D" },
                  "scripts": {
                    "test": "mocha */dist.js"
                  }
                }
                """
            ),
        )
        scripts_project = self.make_target(
            spec="src/node/scripts_project",
            target_type=NodeModule,
            sources=["package.json"],
            dependencies=[util],
        )
        context = self.context(
            target_roots=[scripts_project],
            options={
                "npm-resolver": {
                    "install_optional": False,
                    "force_option_override": False,
                    "install_production": False,
                    "force": False,
                    "frozen_lockfile": True,
                }
            },
        )
        self.wrap_context(context, [NodePaths])
        task = self.create_task(context)
        task.execute()

        node_paths = context.products.get_data(NodePaths)
        node_path = node_paths.node_path(scripts_project)
        self.assertIsNotNone(node_paths.node_path(scripts_project))

        package_json_path = os.path.join(node_path, "package.json")
        with open(package_json_path, "r") as fp:
            package = json.load(fp)
            self.assertEqual(
                "scripts_project",
                package["name"],
                "Expected to find package name of `scripts_project`, but found: {}".format(
                    package["name"]
                ),
            )
            self.assertEqual(
                "1.2.3",
                package["version"],
                "Expected to find package version of `1.2.3`, but found: {}".format(
                    package["version"]
                ),
            )
            self.assertEqual(
                "mocha */dist.js",
                package["scripts"]["test"],
                "Expected to find package test script of `mocha */dist.js`, but found: {}".format(
                    package["scripts"]["test"]
                ),
            )
            self.assertEqual(node_paths.node_path(util), package["dependencies"]["util"])
            self.assertNotIn("A", package["dependencies"])
            self.assertNotIn("devDependencies", package)
            self.assertNotIn("peerDependencies", package)
            self.assertNotIn("optionalDependencies", package)

    @contextmanager
    def _mock_successful_package_manager_run_command(self, package_manager_obj):
        with unittest.mock.patch.object(package_manager_obj, "run_command") as exec_call:
            exec_call.return_value.run.return_value.wait.return_value = 0
            yield exec_call

    def _make_context_for_target(
        self,
        target,
        install_optional=False,
        force_option_override=False,
        install_production=False,
        force=False,
        frozen_lockfile=False,
    ):
        context = self.context(
            target_roots=[target],
            options={
                "npm-resolver": dict(
                    install_optional=install_optional,
                    force_option_override=force_option_override,
                    install_production=install_production,
                    force=force,
                    frozen_lockfile=frozen_lockfile,
                )
            },
        )
        self.wrap_context(context, [NodePaths])
        return context

    def test_node_resolve_invalidation(self):
        self.create_file(
            "src/node/util/package.json",
            contents=dedent(
                """\
                {
                  "name": "util",
                  "version": "0.0.1"
                }
                """
            ),
        )
        self.create_file(
            "src/node/util/util.js",
            contents=dedent(
                """\
                console.log('2 + 2 = 4');
                """
            ),
        )
        target = self.make_target(
            spec="src/node/util", target_type=NodeModule, sources=["util.js", "package.json"]
        )
        initial_fingerprint = target.transitive_invalidation_hash()

        context = self._make_context_for_target(target)
        task = self.create_task(context)

        package_manager_obj = task.get_package_manager(target=target)
        with self._mock_successful_package_manager_run_command(package_manager_obj) as exec_call:
            task.execute()
            exec_call.assert_called_once()

        # Allow target state, including fingerprints, to be reset. This does *not* invalidate the target
        # itself, but editing the source file will do that, causing the task to be re-run.
        self.reset_build_graph()

        self.create_file(
            "src/node/util/util.js",
            contents=dedent(
                """\
                console.log('2 + 2 = 5');
                """
            ),
        )

        target = self.make_target(
            spec="src/node/util", target_type=NodeModule, sources=["util.js", "package.json"]
        )
        next_fingerprint = target.transitive_invalidation_hash()
        self.assertNotEqual(initial_fingerprint, next_fingerprint)

        context = self._make_context_for_target(target)
        task = self.create_task(context)

        package_manager_obj = task.get_package_manager(target=target)
        with self._mock_successful_package_manager_run_command(package_manager_obj) as exec_call:
            task.execute()
            # Because the target was modified, the task should re-run.
            exec_call.assert_called_once()

    def _test_resolve_options_helper(
        self,
        install_optional,
        force_option_override,
        install_production,
        force,
        frozen_lockfile,
        package_manager,
        product_types,
        has_lock_file,
        expected_params,
    ):
        self.create_file(
            "src/node/util/package.json",
            contents=dedent(
                """
                {
                  "name": "util",
                  "version": "0.0.1"
                }
                """
            ),
        )
        self.create_file(
            "src/node/util/util.js",
            contents=dedent(
                """
                var typ = require('typ');
                console.log("type of boolean is: " + typ.BOOLEAN);
                """
            ),
        )
        sources = ["util.js", "package.json"]
        # yarn execution path requires yarn.lock unless it's installing locally
        self.create_file("src/node/util/yarn.lock")
        if has_lock_file:
            self.create_file("src/node/util/yarn.lock")
            sources.append("yarn.lock")
        target = self.make_target(
            spec="src/node/util",
            target_type=NodeModule,
            sources=sources,
            dependencies=[],
            package_manager=package_manager,
        )

        context = self.context(
            target_roots=[target],
            options={
                "npm-resolver": {
                    "install_optional": install_optional,
                    "force_option_override": force_option_override,
                    "install_production": install_production,
                    "force": force,
                    "frozen_lockfile": frozen_lockfile,
                }
            },
        )
        self.wrap_context(context, product_types)
        task = self.create_task(context)

        package_manager_obj = task.get_package_manager(target=target)
        with self._mock_successful_package_manager_run_command(package_manager_obj) as exec_call:
            task.execute()
            exec_call.assert_called_once_with(args=expected_params, node_paths=None)

    def test_resolve_default_no_options_npm(self):
        self._test_resolve_options_helper(
            install_optional=False,
            force_option_override=False,
            install_production=False,
            force=False,
            frozen_lockfile=True,
            package_manager="npm",
            product_types=[NodePaths],
            has_lock_file=False,
            expected_params=["install", "--no-optional"],
        )

    def test_resolve_options_npm(self):
        self._test_resolve_options_helper(
            install_optional=True,
            force_option_override=True,
            install_production=True,
            force=True,
            frozen_lockfile=False,
            package_manager="npm",
            product_types=[NodePaths],
            has_lock_file=False,
            expected_params=["install", "--production", "--force"],
        )

    def test_resolve_default_no_options_yarn(self):
        self._test_resolve_options_helper(
            install_optional=False,
            force_option_override=False,
            install_production=False,
            force=False,
            frozen_lockfile=True,
            package_manager="yarnpkg",
            product_types=[NodePaths],
            has_lock_file=True,
            expected_params=["--non-interactive", "--ignore-optional", "--frozen-lockfile"],
        )

    def test_resolve_options_yarn(self):
        self._test_resolve_options_helper(
            install_optional=True,
            force_option_override=True,
            install_production=True,
            force=True,
            frozen_lockfile=False,
            package_manager="yarnpkg",
            product_types=[NodePaths],
            has_lock_file=True,
            expected_params=["--non-interactive", "--production=true", "--force"],
        )

    def test_resolve_default_no_options_yarn_local(self):
        self._test_resolve_options_helper(
            install_optional=False,
            force_option_override=False,
            install_production=False,
            force=False,
            frozen_lockfile=True,
            package_manager="yarnpkg",
            product_types=[NodePathsLocal],
            has_lock_file=True,
            expected_params=["--non-interactive"],
        )

        def test_resolve_default_no_options_yarn_no_lock_local(self):
            self._test_resolve_options_helper(
                install_optional=False,
                force_option_override=False,
                install_production=False,
                force=False,
                frozen_lockfile=True,
                package_manager="yarnpkg",
                product_types=[NodePathsLocal],
                has_lock_file=False,
                expected_params=["--non-interactive", "--force"],
            )

        def test_resolve_options_yarn_local(self):
            self._test_resolve_options_helper(
                install_optional=True,
                force_option_override=False,
                install_production=True,
                force=True,
                frozen_lockfile=False,
                package_manager="yarnpkg",
                product_types=[NodePathsLocal],
                has_lock_file=True,
                expected_params=["--non-interactive", "--production=true", "--force"],
            )

        def test_resolve_options_yarn_force_override_local(self):
            self._test_resolve_options_helper(
                install_optional=False,
                force_option_override=True,
                install_production=True,
                force=False,
                frozen_lockfile=False,
                package_manager="yarnpkg",
                product_types=[NodePathsLocal],
                has_lock_file=True,
                expected_params=["--non-interactive", "--ignore-optional", "--production=true"],
            )

        def test_resolve_default_no_options_npm_local(self):
            unsupported = "not supported for NPM"
            with self.assertRaisesRegex(TaskError, unsupported):
                self._test_resolve_options_helper(
                    install_optional=False,
                    force_option_override=False,
                    install_production=False,
                    force=False,
                    frozen_lockfile=True,
                    package_manager="npm",
                    product_types=[NodePathsLocal],
                    has_lock_file=True,
                    expected_params=["--non-interactive", "--force"],
                )
