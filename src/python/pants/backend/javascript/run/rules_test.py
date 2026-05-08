# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
from textwrap import dedent

import pytest

from pants.backend.javascript import package_json
from pants.backend.javascript.run.rules import RunNodeBuildScriptFieldSet, RunNodeScriptFieldSet
from pants.backend.javascript.run.rules import rules as run_rules
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget, JSSourceTarget
from pants.build_graph.address import Address
from pants.core.goals.run import RunRequest
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *run_rules(),
            QueryRule(RunRequest, (RunNodeBuildScriptFieldSet,)),
            QueryRule(RunRequest, (RunNodeScriptFieldSet,)),
        ],
        target_types=[
            *package_json.target_types(),
            JSSourceTarget,
            JSSourcesGeneratorTarget,
        ],
        objects=dict(package_json.build_file_aliases().objects),
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_creates_npm_run_requests_package_json_scripts(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_build_script(entry_point="build", output_directories=["dist"]),
                        node_build_script(entry_point="compile", output_directories=["dist"]),
                        node_build_script(entry_point="transpile", output_directories=["dist"]),
                    ]
                )
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "browser": "lib/index.mjs",
                    "scripts": {
                        "build": "swc ./lib -d dist",
                        "transpile": "babel ./lib -d dist",
                        "compile": "tsc ./lib --emit -d bin",
                    },
                }
            ),
            "src/js/package-lock.json": json.dumps({}),
            "src/js/lib/BUILD": dedent(
                """\
                javascript_sources()
                """
            ),
            "src/js/lib/index.mjs": "",
        }
    )
    for script in ("build", "compile", "transpile"):
        tgt = rule_runner.get_target(Address("src/js", generated_name=script))
        result = rule_runner.request(RunRequest, [RunNodeBuildScriptFieldSet.create(tgt)])

        assert result.args == ("npm", "--prefix", "{chroot}/src/js", "run", script)


def test_creates_yarn_run_requests_package_json_scripts(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_build_script(entry_point="build", output_directories=["dist"]),
                        node_build_script(entry_point="compile", output_directories=["dist"]),
                        node_build_script(entry_point="transpile", output_directories=["dist"]),
                    ]
                )
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "browser": "lib/index.mjs",
                    "scripts": {
                        "build": "swc ./lib -d dist",
                        "transpile": "babel ./lib -d dist",
                        "compile": "tsc ./lib --emit -d bin",
                    },
                    "packageManager": "yarn@1.22.19",
                }
            ),
            "src/js/yarn.lock": "",
            "src/js/lib/BUILD": dedent(
                """\
                javascript_sources()
                """
            ),
            "src/js/lib/index.mjs": "",
        }
    )
    for script in ("build", "compile", "transpile"):
        tgt = rule_runner.get_target(Address("src/js", generated_name=script))
        result = rule_runner.request(RunRequest, [RunNodeBuildScriptFieldSet.create(tgt)])

        assert result.args == ("yarn", "--cwd", "{chroot}/src/js", "run", script)


def test_extra_envs(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--nodejs-extra-env-vars=['FROM_SUBSYSTEM=FIZZ']",
        ],
        env_inherit={"PATH"},
    )
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_build_script(entry_point="build", extra_env_vars=["FOO=BAR"], output_files=["dist/index.cjs"])
                    ],
                    extra_env_vars=["FROM_PACKAGE_JSON=BUZZ"]
                )
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "browser": "lib/index.mjs",
                    "scripts": {"build": "mkdir dist && echo $FOO >> dist/index.cjs"},
                }
            ),
            "src/js/package-lock.json": json.dumps({}),
            "src/js/lib/BUILD": dedent(
                """\
                javascript_sources()
                """
            ),
            "src/js/lib/index.mjs": "",
        }
    )
    tgt = rule_runner.get_target(Address("src/js", generated_name="build"))

    result = rule_runner.request(RunRequest, [RunNodeBuildScriptFieldSet.create(tgt)])
    assert result.extra_env.get("FOO") == "BAR"
    assert result.extra_env.get("FROM_SUBSYSTEM") == "FIZZ"
    assert result.extra_env.get("FROM_PACKAGE_JSON") == "BUZZ"


def test_run_node_script(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_run_script(entry_point="start", extra_env_vars=["PORT=3000"])
                    ]
                )
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "browser": "lib/index.mjs",
                    "scripts": {"start": "node server.js"},
                }
            ),
            "src/js/package-lock.json": json.dumps({}),
            "src/js/lib/BUILD": dedent(
                """\
                javascript_sources()
                """
            ),
            "src/js/lib/index.mjs": "",
        }
    )
    target = rule_runner.get_target(Address("src/js", generated_name="start"))
    run_request = rule_runner.request(RunRequest, [RunNodeScriptFieldSet.create(target)])
    assert "run" in run_request.args
    assert "start" in run_request.args
    assert run_request.extra_env.get("PORT") == "3000"


def test_pnpm_run_node_script_propagates_append_only_caches(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_run_script(entry_point="dev"),
                        node_build_script(entry_point="build", output_directories=["dist"]),
                    ]
                )
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "packageManager": "pnpm@9.5.0",
                    "scripts": {"dev": "vite", "build": "vite build"},
                }
            ),
            "src/js/pnpm-lock.yaml": dedent(
                """\
                lockfileVersion: '9.0'

                settings:
                  autoInstallPeers: true
                  excludeLinksFromLockfile: false

                importers:

                  .:
                    {}

                snapshots: {}
                """
            ),
            "src/js/lib/BUILD": dedent(
                """\
                javascript_sources()
                """
            ),
            "src/js/lib/index.mjs": "",
        }
    )
    run_script_target = rule_runner.get_target(Address("src/js", generated_name="dev"))
    run_request = rule_runner.request(RunRequest, [RunNodeScriptFieldSet.create(run_script_target)])
    assert run_request.append_only_caches is not None
    assert "pnpm_home" in run_request.append_only_caches

    build_script_target = rule_runner.get_target(Address("src/js", generated_name="build"))
    build_run_request = rule_runner.request(
        RunRequest, [RunNodeBuildScriptFieldSet.create(build_script_target)]
    )
    assert build_run_request.append_only_caches is not None
    assert "pnpm_home" in build_run_request.append_only_caches


def test_yarn_run_node_script_propagates_append_only_caches(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_run_script(entry_point="dev"),
                        node_build_script(entry_point="build", output_directories=["dist"]),
                    ]
                )
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "packageManager": "yarn@1.22.0",
                    "scripts": {"dev": "vite", "build": "vite build"},
                }
            ),
            "src/js/yarn.lock": dedent(
                """\
                # THIS IS AN AUTOGENERATED FILE. DO NOT EDIT THIS FILE DIRECTLY.
                # yarn lockfile v1


                """
            ),
            "src/js/lib/BUILD": dedent(
                """\
                javascript_sources()
                """
            ),
            "src/js/lib/index.mjs": "",
        }
    )
    run_script_target = rule_runner.get_target(Address("src/js", generated_name="dev"))
    run_request = rule_runner.request(RunRequest, [RunNodeScriptFieldSet.create(run_script_target)])
    assert run_request.append_only_caches is not None
    assert "yarn_cache" in run_request.append_only_caches

    build_script_target = rule_runner.get_target(Address("src/js", generated_name="build"))
    build_run_request = rule_runner.request(
        RunRequest, [RunNodeBuildScriptFieldSet.create(build_script_target)]
    )
    assert build_run_request.append_only_caches is not None
    assert "yarn_cache" in build_run_request.append_only_caches
