# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Core goals for Pants to operate correctly.

These are always activated and cannot be disabled.
"""

from pants.core_tasks.bash_completion import BashCompletion
from pants.core_tasks.clean import Clean
from pants.core_tasks.deferred_sources_mapper import DeferredSourcesMapper
from pants.core_tasks.explain_options_task import ExplainOptionsTask
from pants.core_tasks.login import Login
from pants.core_tasks.noop import NoopCompile, NoopTest
from pants.core_tasks.pantsd_kill import PantsDaemonKill
from pants.core_tasks.reporting_server_kill import ReportingServerKill
from pants.core_tasks.reporting_server_run import ReportingServerRun
from pants.core_tasks.run_prep_command import (
    RunBinaryPrepCommand,
    RunCompilePrepCommand,
    RunTestPrepCommand,
)
from pants.core_tasks.substitute_aliased_targets import SubstituteAliasedTargets
from pants.core_tasks.targets_help import TargetsHelp
from pants.goal.goal import Goal
from pants.goal.task_registrar import TaskRegistrar as task


def register_goals():
    # Register descriptions for the standard multiple-task goals.  Single-task goals get
    # their descriptions from their single task.
    Goal.register("buildgen", "Automatically generate BUILD files.")
    Goal.register("bootstrap", "Bootstrap tools needed by subsequent build steps.")
    Goal.register("imports", "Resolve external source dependencies.")
    Goal.register("gen", "Generate code.")
    Goal.register("resolve", "Resolve external binary dependencies.")
    Goal.register("compile", "Compile source code.")
    Goal.register("binary", "Create a runnable binary.")
    Goal.register("resources", "Prepare resources.")
    Goal.register("bundle", "Create a deployable application bundle.")
    Goal.register("bench", "Run benchmarks.")
    Goal.register("repl", "Run a REPL.")
    Goal.register("repl-dirty", "Run a REPL, skipping compilation.")
    Goal.register("run", "Invoke a binary.")
    Goal.register("run-dirty", "Invoke a binary, skipping compilation.")
    Goal.register("doc", "Generate documentation.")
    Goal.register("publish", "Publish a build artifact.")
    Goal.register("dep-usage", "Collect target dependency usage data.")
    Goal.register("lint", "Find formatting errors in source code.")
    Goal.register("fmt", "Autoformat source code.")
    Goal.register("buildozer", "Manipulate BUILD files.")

    # Register tasks.

    # Cleaning.
    task(name="clean-all", action=Clean).install("clean-all")

    # Pantsd.
    kill_pantsd = task(name="kill-pantsd", action=PantsDaemonKill)
    kill_pantsd.install()
    # Kill pantsd/watchman first, so that they're not using any files
    # in .pants.d at the time of removal.
    kill_pantsd.install("clean-all", first=True)

    # Reporting server.
    # TODO: The reporting server should be subsumed into pantsd, and not run via a task.
    task(name="server", action=ReportingServerRun, serialize=False).install()
    task(name="killserver", action=ReportingServerKill, serialize=False).install()

    # Auth.
    task(name="login", action=Login).install()

    # Getting help.
    task(name="options", action=ExplainOptionsTask).install()
    task(name="targets", action=TargetsHelp).install()

    # Stub for other goals to schedule 'compile'. See noop_exec_task.py for why this is useful.
    task(name="compile", action=NoopCompile).install("compile")

    # Prep commands must be the first thing we register under its goal.
    task(name="test-prep-command", action=RunTestPrepCommand).install("test", first=True)
    task(name="binary-prep-command", action=RunBinaryPrepCommand).install("binary", first=True)
    task(name="compile-prep-command", action=RunCompilePrepCommand).install("compile", first=True)

    # Stub for other goals to schedule 'test'. See noop_exec_task.py for why this is useful.
    task(name="legacy", action=NoopTest).install("test")

    # Workspace information.
    task(name="bash-completion", action=BashCompletion).install()

    # Handle sources that aren't loose files in the repo.
    task(name="deferred-sources", action=DeferredSourcesMapper).install()

    # Processing aliased targets has to occur very early.
    task(name="substitute-aliased-targets", action=SubstituteAliasedTargets).install(
        "bootstrap", first=True
    )
