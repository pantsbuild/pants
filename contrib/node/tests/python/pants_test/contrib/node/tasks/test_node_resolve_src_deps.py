# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from textwrap import dedent

from pants.base.exceptions import TaskError
from pants.testutil.task_test_base import TaskTestBase

from pants.contrib.node.subsystems.resolvers.node_preinstalled_module_resolver import (
    NodePreinstalledModuleResolver,
)
from pants.contrib.node.subsystems.resolvers.npm_resolver import NpmResolver
from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.targets.node_preinstalled_module import NodePreinstalledModule
from pants.contrib.node.tasks.node_paths import NodePaths
from pants.contrib.node.tasks.node_resolve import NodeResolve


class NodeResolveSourceDepsTest(TaskTestBase):
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

    def _create_trans_dep(self, node_scope=None):
        """Create a transitive dependency target."""
        self.create_file("src/node/trans_dep/yarn.lock")
        self.create_file(
            "src/node/trans_dep/package.json",
            contents=dedent(
                """
                {
                  "name": "trans_dep",
                  "version": "0.0.1"
                }
                """
            ),
        )
        self.create_file(
            "src/node/trans_dep/index.js",
            contents=dedent(
                """
                const add = (num1, num2) => {
                  return num1 + num2;
                };
                module.exports.add = add;
                """
            ),
        )
        trans_dep = self.make_target(
            spec="src/node/trans_dep:trans_dep",
            target_type=NodeModule,
            sources=["index.js", "package.json", "yarn.lock"],
            package_name="trans_dep",
            package_manager="yarn",
            node_scope=node_scope,
        )
        return trans_dep

    def _create_dep(
        self,
        trans_dep=None,
        provide_bin=None,
        use_bin_dict=None,
        src_root=None,
        make_target=True,
        node_scope=None,
    ):
        """Create a dependency target."""

        src_root = src_root or "src/node"
        bin_field = ""
        bin_executables = None
        if provide_bin:
            if use_bin_dict:
                bin_field = ', "bin": "./cli.js"'
                bin_executables = {"dep_cli": "./cli.js"}
            else:
                bin_field = ', "bin": {"dep_cli": "./cli.js"}'
                bin_executables = "./cli.js"

        self.create_file(os.path.join(src_root, "dep/yarn.lock"))
        self.create_file(
            os.path.join(src_root, "dep/cli.js"),
            contents=dedent(
                """#!/usr/bin/env node
                console.log('Hello world!');
                """
            ),
        )
        if trans_dep:
            require_dep = "trans_dep"
            if node_scope:
                require_dep = os.path.join(f"@{node_scope}", require_dep)
            self.create_file(
                os.path.join(src_root, "dep/index.js"),
                contents=dedent(
                    """
                    const trans_dep = require('{require_dep}');
                    const addOne = (num) => {{
                      return trans_dep.add(num, 1);
                    }};
                    module.exports.addOne = addOne;
                    """.format(
                        require_dep=require_dep
                    )
                ),
            )
            self.create_file(
                os.path.join(src_root, "dep/package.json"),
                contents=dedent(
                    """
                    {{
                      "name": "dep",
                      "version": "0.0.1",
                      "dependencies": {{
                        "trans_dep": "file:../trans_dep"
                      }}{bin_field}
                    }}
                    """.format(
                        bin_field=bin_field
                    )
                ),
            )

            if make_target:
                dep = self.make_target(
                    spec=os.path.join(src_root, "dep:dep"),
                    target_type=NodeModule,
                    sources=["index.js", "package.json", "yarn.lock", "cli.js"],
                    package_name="dep",
                    package_manager="yarn",
                    dependencies=[trans_dep],
                    bin_executables=bin_executables,
                    node_scope=node_scope,
                )
            else:
                dep = None
        else:
            self.create_file(
                os.path.join(src_root, "dep/package.json"),
                contents=dedent(
                    """
                    {{
                      "name": "dep",
                      "version": "0.0.1"{bin_field}
                    }}
                    """.format(
                        bin_field=bin_field
                    )
                ),
            )
            self.create_file(
                os.path.join(src_root, "dep/index.js"),
                contents=dedent(
                    """
                    const addOne = (num) => {
                      return num + 1;
                    };
                    module.exports.addOne = addOne;
                    """
                ),
            )
            if make_target:
                dep = self.make_target(
                    spec=os.path.join(src_root, "dep:dep"),
                    target_type=NodeModule,
                    sources=["index.js", "package.json", "yarn.lock", "cli.js"],
                    package_name="dep",
                    package_manager="yarn",
                    bin_executables=bin_executables,
                    node_scope=node_scope,
                )
            else:
                dep = None
        return dep

    def _create_app(
        self, dep, dep_not_found=None, package_manager=None, src_root=None, node_scope=None
    ):
        src_root = src_root or "src/node"
        dependencies = '"dep": "file:../dep"'
        if dep_not_found:
            dependencies = '"dep_not_found": "file:../dep_not_found"'

        package_manager = package_manager or "yarn"
        self.create_file(os.path.join(src_root, "app/yarn.lock"))
        self.create_file(
            os.path.join(src_root, "app/package.json"),
            contents=dedent(
                """
                {{
                  "name": "app",
                  "version": "0.0.1",
                  "dependencies": {{
                    {dependencies}
                  }},
                  "bin": {{
                    "app": "./cli.js",
                    "app2": "./cli2.js"
                  }}
                }}
                """.format(
                    dependencies=dependencies
                )
            ),
        )

        require_dep = "dep"
        if node_scope:
            require_dep = os.path.join(f"@{node_scope}", require_dep)
        self.create_file(
            os.path.join(src_root, "app/index.js"),
            contents=dedent(
                """
                const dep = require('{require_dep}');
                console.log(dep.addOne(1));
                """.format(
                    require_dep=require_dep
                )
            ),
        )
        self.create_file(
            os.path.join(src_root, "app/cli.js"),
            contents=dedent(
                """#!/usr/bin/env node
                console.log('cli');
                """
            ),
        )
        self.create_file(
            os.path.join(src_root, "app/cli2.js"),
            contents=dedent(
                """#!/usr/bin/env node
                console.log('cli2');
                """
            ),
        )
        app = self.make_target(
            spec=os.path.join(src_root, "app:app"),
            target_type=NodeModule,
            sources=["index.js", "package.json", "yarn.lock", "cli.js", "cli2.js"],
            package_name="app",
            package_manager=package_manager,
            dependencies=[dep],
            bin_executables={"app": "./cli.js", "app2": "./cli2.js"},
            node_scope=node_scope,
        )
        return app

    def _create_basic_app(self, src_root=None):
        src_root = src_root or "src/node"
        self.create_file(os.path.join(src_root, "app/yarn.lock"))
        self.create_file(
            os.path.join(src_root, "app/package.json"),
            contents=dedent(
                """
                {
                  "name": "app",
                  "version": "0.0.1",
                  "bin": "index.js"
                }
                """
            ),
        )
        self.create_file(
            os.path.join(src_root, "app/index.js"),
            contents=dedent(
                """
                console.log('hello');
                """
            ),
        )
        app = self.make_target(
            spec=os.path.join(src_root, "app:app"),
            target_type=NodeModule,
            sources=["index.js", "package.json", "yarn.lock"],
            package_name="app",
            package_manager="yarn",
            bin_executables="index.js",
        )
        return app

    def _create_workspace(self, with_trans_dep=None):
        self._create_dep(
            provide_bin=True, src_root="src/node/workspace/projects", make_target=False
        )
        if with_trans_dep:
            trans_dep = self._create_trans_dep()
            dep = self._create_dep(trans_dep=trans_dep, provide_bin=True, use_bin_dict=True)
            app = self._create_app(dep)
        else:
            app = self._create_basic_app()

        self.create_file("src/node/workspace/yarn.lock")

        # Workspaces can only be enabled in private projects.
        self.create_file(
            "src/node/workspace/package.json",
            contents=dedent(
                """
                {
                  "name": "workspace",
                  "version": "1.0.0",
                  "private": true,
                  "workspaces": [
                    "./projects/dep"
                  ],
                  "dependencies": {
                    "app": "file:../app"
                  }
                }
                """
            ),
        )

        workspace = self.make_target(
            spec="src/node/workspace:workspace",
            target_type=NodeModule,
            sources=["package.json", "yarn.lock", "projects/**/*"],
            package_name="workspace",
            package_manager="yarn",
            dependencies=[app],
        )
        return workspace

    def _resolve_target(self, target, node_scope=None):
        context = self.context(
            target_roots=[target],
            options={
                "npm-resolver": {
                    "install_optional": False,
                    "force_option_override": False,
                    "install_production": False,
                    "force": False,
                    "frozen_lockfile": True,
                },
                "node-distribution": {"node_scope": node_scope},
            },
        )
        self.wrap_context(context, [NodePaths])
        task = self.create_task(context)
        task.execute()

        node_paths = context.products.get_data(NodePaths)
        return task, node_paths

    def test_resolve_simple_dep_graph(self):
        dep = self._create_dep(provide_bin=True)
        app = self._create_app(dep)
        _, node_paths = self._resolve_target(app)

        dep_node_path = node_paths.node_path(dep)
        app_node_path = node_paths.node_path(app)
        self.assertIsNotNone(dep_node_path)
        self.assertIsNotNone(app_node_path)

        # Verify that 'app/node_modules' has a correct symlink to 'dep'
        app_node_modules_path = os.path.join(app_node_path, "node_modules")
        link_dep_path = os.path.join(app_node_modules_path, "dep")
        self.assertTrue(os.path.exists(app_node_modules_path))
        self.assertTrue(os.path.islink(link_dep_path))

        expected = os.path.relpath(dep_node_path, app_node_modules_path)
        self.assertEqual(os.readlink(link_dep_path), expected)

        # Verify that 'app/node_modules/.bin' has a correct symlink to 'dep'
        app_bin_dep_path = os.path.join(dep_node_path, "cli.js")
        dep_bin_path = os.path.join(app_node_path, "node_modules", ".bin")
        link_dep_bin_path = os.path.join(dep_bin_path, "dep")

        self.assertTrue(os.path.islink(link_dep_bin_path))
        relative_path = os.readlink(link_dep_bin_path)
        expected = os.path.relpath(app_bin_dep_path, dep_bin_path)
        self.assertEqual(relative_path, expected)

    def test_resolve_symlink_bin_dict(self):
        dep = self._create_dep(provide_bin=True, use_bin_dict=True)
        app = self._create_app(dep)
        _, node_paths = self._resolve_target(app)

        dep_node_path = node_paths.node_path(dep)
        app_node_path = node_paths.node_path(app)
        self.assertIsNotNone(dep_node_path)
        self.assertIsNotNone(app_node_path)

        # Verify that 'app/node_modules/.bin' has a correct symlink to 'dep_cli'
        app_bin_dep_path = os.path.join(dep_node_path, "cli.js")
        dep_bin_path = os.path.join(app_node_path, "node_modules", ".bin")
        link_dep_bin_path = os.path.join(dep_bin_path, "dep_cli")
        self.assertTrue(os.path.islink(link_dep_bin_path))
        relative_path = os.readlink(link_dep_bin_path)
        expected = os.path.relpath(app_bin_dep_path, dep_bin_path)
        self.assertEqual(relative_path, expected)

    def test_resolve_and_run_transitive_deps(self):
        trans_dep = self._create_trans_dep()
        dep = self._create_dep(trans_dep=trans_dep, provide_bin=True, use_bin_dict=True)
        app = self._create_app(dep)
        task, node_paths = self._resolve_target(app)

        trans_dep_node_path = node_paths.node_path(trans_dep)
        dep_node_path = node_paths.node_path(dep)
        app_node_path = node_paths.node_path(app)
        self.assertIsNotNone(trans_dep_node_path)
        self.assertIsNotNone(dep_node_path)
        self.assertIsNotNone(app_node_path)

        script_path = os.path.join(app_node_path, "index.js")
        out = task.node_distribution.node_command(args=[script_path]).check_output()
        lines = {line.strip() for line in out.splitlines()}
        self.assertIn("2", lines)

    def test_file_dependency_not_found_in_build_graph(self):
        dep = self._create_dep()
        app = self._create_app(dep, dep_not_found=True)
        error_msg = "Local dependency in package.json not found in the build graph."
        with self.assertRaisesRegex(TaskError, error_msg):
            self._resolve_target(app)

    def test_file_dependency_not_supported_npm(self):
        dep = self._create_dep()
        app = self._create_app(dep, package_manager="npm")
        _, node_paths = self._resolve_target(app)

    def test_yarn_workspaces_with_transitive_source_deps(self):
        workspace = self._create_workspace(with_trans_dep=True)
        task, node_paths = self._resolve_target(workspace)
        workspace_node_path = node_paths.node_path(workspace)

        # Test transitive source deps is correctly installed
        script_path = os.path.join(workspace_node_path, "node_modules", ".bin", "app")
        out = task.node_distribution.node_command(args=[script_path]).check_output()
        lines = {line.strip() for line in out.splitlines()}
        self.assertIn("cli", lines)
        script_path = os.path.join(workspace_node_path, "node_modules", "app", "index.js")
        out = task.node_distribution.node_command(args=[script_path]).check_output()
        lines = {line.strip() for line in out.splitlines()}
        self.assertIn("2", lines)

        # Test workspace deps is correctly installed
        script_path = os.path.join(workspace_node_path, "node_modules", ".bin", "dep_cli")
        out = task.node_distribution.node_command(args=[script_path]).check_output()
        lines = {line.strip() for line in out.splitlines()}
        self.assertIn("Hello world!", lines)

    def test_yarn_workspaces_with_direct_source_deps(self):
        workspace = self._create_workspace()
        task, node_paths = self._resolve_target(workspace)
        workspace_node_path = node_paths.node_path(workspace)

        # Test source deps is correctly installed
        script_path = os.path.join(workspace_node_path, "node_modules", ".bin", "app")
        out = task.node_distribution.node_command(args=[script_path]).check_output()
        lines = {line.strip() for line in out.splitlines()}
        self.assertIn("hello", lines)

        # Test workspace deps is correctly installed
        script_path = os.path.join(workspace_node_path, "node_modules", ".bin", "dep_cli")
        out = task.node_distribution.node_command(args=[script_path]).check_output()
        lines = {line.strip() for line in out.splitlines()}
        self.assertIn("Hello world!", lines)

    def test_node_scope_installed_successfully(self):
        dep = self._create_dep(node_scope="pants")
        app = self._create_app(dep, node_scope="pants")
        task, node_paths = self._resolve_target(app)

        dep_node_path = node_paths.node_path(dep)
        app_node_path = node_paths.node_path(app)
        self.assertIsNotNone(dep_node_path)
        self.assertIsNotNone(app_node_path)

        # Verify that 'app/node_modules' has a correct symlink to '@pants/dep'
        app_node_modules_path = os.path.join(app_node_path, "node_modules")
        link_dep_path = os.path.join(app_node_modules_path, "@pants", "dep")
        self.assertTrue(os.path.exists(app_node_modules_path))
        self.assertTrue(os.path.islink(link_dep_path))

        expected = os.path.relpath(dep_node_path, os.path.dirname(link_dep_path))
        self.assertEqual(os.readlink(link_dep_path), expected)

        # Imports are working correctly
        script_path = os.path.join(app_node_path, "index.js")
        out = task.node_distribution.node_command(args=[script_path]).check_output()
        lines = {line.strip() for line in out.splitlines()}
        self.assertIn("2", lines)

    def test_transitive_node_scope(self):
        trans_dep = self._create_trans_dep(node_scope="pants")
        dep = self._create_dep(
            trans_dep=trans_dep, provide_bin=True, use_bin_dict=True, node_scope="pants"
        )
        app = self._create_app(dep, node_scope="pants")
        task, node_paths = self._resolve_target(app)

        trans_dep_node_path = node_paths.node_path(trans_dep)
        dep_node_path = node_paths.node_path(dep)
        app_node_path = node_paths.node_path(app)
        self.assertIsNotNone(trans_dep_node_path)
        self.assertIsNotNone(dep_node_path)
        self.assertIsNotNone(app_node_path)

        script_path = os.path.join(app_node_path, "index.js")
        out = task.node_distribution.node_command(args=[script_path]).check_output()
        lines = {line.strip() for line in out.splitlines()}
        self.assertIn("2", lines)

    def test_node_scope_override_successfully(self):
        node_scope = "pants"
        self.create_file("src/node/dep/yarn.lock")
        self.create_file(
            "src/node/dep/package.json",
            contents=dedent(
                """
                {
                  "name": "@shorts/dep",
                  "version": "0.0.1"
                }
                """
            ),
        )
        self.create_file(
            "src/node/dep/index.js",
            contents=dedent(
                """
                const addOne = (num) => {
                  return num + 1;
                };
                module.exports.addOne = addOne;
                """
            ),
        )
        dep = self.make_target(
            spec="src/node/dep:dep",
            target_type=NodeModule,
            sources=["index.js", "package.json", "yarn.lock", "cli.js"],
            package_name="dep",
            package_manager="yarn",
            node_scope=node_scope,
        )
        app = self._create_app(dep, node_scope=node_scope)
        task, node_paths = self._resolve_target(app)

        dep_node_path = node_paths.node_path(dep)
        app_node_path = node_paths.node_path(app)
        self.assertIsNotNone(dep_node_path)
        self.assertIsNotNone(app_node_path)

        # Verify that 'app/node_modules' has a correct symlink to '@pants/dep' and not '@shorts/dep'
        app_node_modules_path = os.path.join(app_node_path, "node_modules")
        link_dep_path = os.path.join(app_node_modules_path, "@pants", "dep")
        self.assertTrue(os.path.exists(app_node_modules_path))
        self.assertTrue(os.path.islink(link_dep_path))

        expected = os.path.relpath(dep_node_path, os.path.dirname(link_dep_path))
        self.assertEqual(os.readlink(link_dep_path), expected)

        # Imports are working correctly
        script_path = os.path.join(app_node_path, "index.js")
        out = task.node_distribution.node_command(args=[script_path]).check_output()
        lines = {line.strip() for line in out.splitlines()}
        self.assertIn("2", lines)

    def test_import_fails_with_node_scope(self):
        dep = self._create_dep(node_scope="pants")
        # In the require('dep') statement, won't include the node_scope
        app = self._create_app(dep)
        task, node_paths = self._resolve_target(app)

        dep_node_path = node_paths.node_path(dep)
        app_node_path = node_paths.node_path(app)
        self.assertIsNotNone(dep_node_path)
        self.assertIsNotNone(app_node_path)

        # Verify that 'app/node_modules' has a correct symlink to '@pants/dep'
        app_node_modules_path = os.path.join(app_node_path, "node_modules")
        link_dep_path = os.path.join(app_node_modules_path, "@pants", "dep")
        self.assertTrue(os.path.exists(app_node_modules_path))
        self.assertTrue(os.path.islink(link_dep_path))

        expected = os.path.relpath(dep_node_path, os.path.dirname(link_dep_path))
        self.assertEqual(os.readlink(link_dep_path), expected)

        # Imports should fail
        script_path = os.path.join(app_node_path, "index.js")
        with self.assertRaises(subprocess.CalledProcessError):
            task.node_distribution.node_command(args=[script_path]).check_output()

    def test_scoped_only_in_package_json(self):
        self.create_file("src/node/dep/yarn.lock")

        # Scoped to @shorts in package.json, but if not specified in pants, will not be Scoped
        self.create_file(
            "src/node/dep/package.json",
            contents=dedent(
                """
                {
                  "name": "@shorts/dep",
                  "version": "0.0.1"
                }
                """
            ),
        )
        self.create_file(
            "src/node/dep/index.js",
            contents=dedent(
                """
                const addOne = (num) => {
                  return num + 1;
                };
                module.exports.addOne = addOne;
                """
            ),
        )
        dep = self.make_target(
            spec="src/node/dep:dep",
            target_type=NodeModule,
            sources=["index.js", "package.json", "yarn.lock", "cli.js"],
            package_name="dep",
            package_manager="yarn",
        )
        app = self._create_app(dep)
        task, node_paths = self._resolve_target(app)

        dep_node_path = node_paths.node_path(dep)
        app_node_path = node_paths.node_path(app)
        self.assertIsNotNone(dep_node_path)
        self.assertIsNotNone(app_node_path)

        # Verify that 'app/node_modules' has a correct symlink to 'dep'
        app_node_modules_path = os.path.join(app_node_path, "node_modules")
        link_dep_path = os.path.join(app_node_modules_path, "dep")
        self.assertTrue(os.path.exists(app_node_modules_path))
        self.assertTrue(os.path.islink(link_dep_path))

        expected = os.path.relpath(dep_node_path, app_node_modules_path)
        self.assertEqual(os.readlink(link_dep_path), expected)

        # Imports are working correctly
        script_path = os.path.join(app_node_path, "index.js")
        out = task.node_distribution.node_command(args=[script_path]).check_output()
        lines = {line.strip() for line in out.splitlines()}
        self.assertIn("2", lines)

    def test_global_node_scope_installed_successfully(self):
        dep = self._create_dep()
        app = self._create_app(dep, node_scope="pants")
        task, node_paths = self._resolve_target(app, node_scope="pants")

        dep_node_path = node_paths.node_path(dep)
        app_node_path = node_paths.node_path(app)
        self.assertIsNotNone(dep_node_path)
        self.assertIsNotNone(app_node_path)

        # Verify that 'app/node_modules' has a correct symlink to '@pants/dep'
        app_node_modules_path = os.path.join(app_node_path, "node_modules")
        link_dep_path = os.path.join(app_node_modules_path, "@pants", "dep")
        self.assertTrue(os.path.exists(app_node_modules_path))
        self.assertTrue(os.path.islink(link_dep_path))

        expected = os.path.relpath(dep_node_path, os.path.dirname(link_dep_path))
        self.assertEqual(os.readlink(link_dep_path), expected)

        # Imports are working correctly
        script_path = os.path.join(app_node_path, "index.js")
        out = task.node_distribution.node_command(args=[script_path]).check_output()
        lines = {line.strip() for line in out.splitlines()}
        self.assertIn("2", lines)

    def test_target_node_scope_overrides_global_successfully(self):
        dep = self._create_dep(node_scope="shorts")
        app = self._create_app(dep, node_scope="shorts")
        task, node_paths = self._resolve_target(app, node_scope="pants")

        dep_node_path = node_paths.node_path(dep)
        app_node_path = node_paths.node_path(app)
        self.assertIsNotNone(dep_node_path)
        self.assertIsNotNone(app_node_path)

        # Verify that 'app/node_modules' has a correct symlink to '@shorts/dep'
        app_node_modules_path = os.path.join(app_node_path, "node_modules")
        link_dep_path = os.path.join(app_node_modules_path, "@shorts", "dep")
        self.assertTrue(os.path.exists(app_node_modules_path))
        self.assertTrue(os.path.islink(link_dep_path))

        expected = os.path.relpath(dep_node_path, os.path.dirname(link_dep_path))
        self.assertEqual(os.readlink(link_dep_path), expected)

        # Imports are working correctly
        script_path = os.path.join(app_node_path, "index.js")
        out = task.node_distribution.node_command(args=[script_path]).check_output()
        lines = {line.strip() for line in out.splitlines()}
        self.assertIn("2", lines)
