# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from pathlib import Path
from textwrap import dedent

from pants.testutil.pants_integration_test import ensure_daemon, run_pants, setup_tmpdir
from pants.util.contextutil import temporary_dir


def test_visualize_to():
    # Tests usage of the `--engine-visualize-to=` option, which triggers background
    # visualization of the graph. There are unit tests confirming the content of the rendered
    # results.
    with temporary_dir(root_dir=os.getcwd()) as destdir:
        run_pants(
            [
                f"--engine-visualize-to={destdir}",
                "--backend-packages=pants.backend.python",
                "list",
                "testprojects/src/python/hello/greet",
            ]
        ).assert_success()
        destdir_files = list(Path(destdir).iterdir())
        assert len(destdir_files) > 0


@ensure_daemon
def test_graceful_termination(use_pantsd: bool) -> None:
    sources = {
        "in_repo_plugins/bender/register.py": dedent(
            '''\
            from pants.engine.addresses import Addresses
            from pants.engine.console import Console
            from pants.engine.goal import Goal, GoalSubsystem
            from pants.engine.rules import QueryRule, collect_rules, goal_rule


            class ListAndDieForTestingSubsystem(GoalSubsystem):
                """A fast and deadly variant of `./pants list`."""

                name = "list-and-die-for-testing"
                help = "A fast and deadly variant of `./pants list`."


            class ListAndDieForTesting(Goal):
                subsystem_cls = ListAndDieForTestingSubsystem
                environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


            @goal_rule
            def fast_list_and_die_for_testing(console: Console, addresses: Addresses) -> ListAndDieForTesting:
                for address in addresses:
                    console.print_stdout(address.spec)
                return ListAndDieForTesting(exit_code=42)


            def rules():
                return [
                    *collect_rules(),
                    # NB: Would be unused otherwise.
                    QueryRule(ListAndDieForTestingSubsystem, []),
                ]
            '''
        ),
        "in_repo_plugins/bender/__init__.py": "",
    }

    with setup_tmpdir(sources) as tmpdir:
        result = run_pants(
            [
                f"--pythonpath=['{tmpdir}/in_repo_plugins']",
                "--backend-packages=['pants.backend.python', 'bender']",
                "list-and-die-for-testing",
                "testprojects/src/python/hello/greet:greet",
            ],
            use_pantsd=use_pantsd,
        )
        result.assert_failure()
        assert result.stdout == "testprojects/src/python/hello/greet:greet\n", result.stderr
        assert result.exit_code == 42
