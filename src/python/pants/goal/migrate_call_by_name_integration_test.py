# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir

REGISTER_FILE = dedent(
    """\
    from pants.backend.python.lint.black.subsystem import Black
    from pants.engine.rules import collect_rules, Get, rule, goal_rule
    from pants.engine.goal import Goal, GoalSubsystem

    from migrateme.rules1 import Bar, Baz, Foo, rules as rules1
    from migrateme.rules2 import Qux, rules as rules2

    class ContrivedGoalSubsystem(GoalSubsystem):
        name = "contrived-goal"
        help = "Need this to get the rule graph to create test migrations."

    class ContrivedGoal(Goal):
        subsystem_cls = ContrivedGoalSubsystem
        environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY

    @goal_rule
    async def setup_migrateme(black: Black) -> ContrivedGoal:
        foo = await Get(Foo, Black, black)
        bar = await Get(Bar, Black, black)
        baz = await Get(Baz, Black, black)
        qux = await Get(Qux, Black, black)

    def rules():
        return [*collect_rules(), *rules1(), *rules2()]
    """
)

MIGRATED_REGISTER_FILE = dedent(
    """\
    TODO!!!!
    from pants.backend.python.lint.black.subsystem import Black
    from pants.engine.rules import collect_rules, Get, rule, goal_rule
    from pants.engine.goal import Goal, GoalSubsystem

    from migrateme.rules1 import Bar, Baz, Foo, rules as rules1
    from migrateme.rules2 import Qux, rules as rules2

    class ContrivedGoalSubsystem(GoalSubsystem):
        name = "contrived-goal"
        help = "Need this to get the rule graph to create test migrations."

    class ContrivedGoal(Goal):
        subsystem_cls = ContrivedGoalSubsystem
        environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY

    @goal_rule
    async def setup_migrateme(black: Black) -> ContrivedGoal:
        foo = await Get(Foo, Black, black)
        bar = await Get(Bar, Black, black)
        baz = await Get(Baz, Black, black)
        qux = await Get(Qux, Black, black)

    def rules():
        return [*collect_rules(), *rules1(), *rules2()]
    """
)

RULES1_FILE = dedent(
    """\
    from pants.backend.python.lint.black.subsystem import Black
    from pants.backend.python.util_rules.pex import PexRequest, VenvPex
    from pants.engine.rules import collect_rules, Get, rule

    class Foo:
        pass

    @rule
    async def setup_black(black: Black) -> Foo:
        pex = await Get(VenvPex, PexRequest, black.to_pex_request())

    class Bar:
        pass

    @rule(desc="Ensure multi-line calls are migrated")
    async def setup_black_multiline(black: Black) -> Bar:
        pex = await Get(
            VenvPex,
            PexRequest,
            black.to_pex_request()
        )

    class Baz:
        pass

    @rule(desc="Ensure calls with embedded comments are ignored")
    async def setup_black_embedded_comments(black: Black) -> Baz:
        pex = await Get(
            VenvPex,
            PexRequest,
            # Some comment that the AST parse wipes out, so we can't migrate this call safely
            black.to_pex_request()
        )

    def rules():
        return collect_rules()
    """
)

MIGRATED_RULES1_FILE = dedent(
    """\
    from pants.backend.python.lint.black.subsystem import Black
    from pants.backend.python.util_rules.pex import PexRequest, VenvPex
    from pants.engine.rules import collect_rules, Get, rule
    from pants.engine.rules import implicitly
    from pants.backend.python.util_rules.pex import create_venv_pex

    class Foo:
        pass

    @rule
    async def setup_black(black: Black) -> Foo:
        pex = await create_venv_pex(**implicitly({black.to_pex_request(): PexRequest}))

    class Bar:
        pass

    @rule(desc="Ensure multi-line calls are migrated")
    async def setup_black_multiline(black: Black) -> Bar:
        pex = await create_venv_pex(**implicitly({black.to_pex_request(): PexRequest}))

    class Baz:
        pass

    @rule(desc="Ensure calls with embedded comments are ignored")
    async def setup_black_embedded_comments(black: Black) -> Baz:
        pex = await Get(
            VenvPex,
            PexRequest,
            # Some comment that the AST parse wipes out, so we can't migrate this call safely
            black.to_pex_request()
        )

    def rules():
        return collect_rules()
    """
)

RULES2_FILE = dedent(
    """\
    from pants.backend.python.lint.black.subsystem import Black
    from pants.backend.python.util_rules.pex import PexRequest, VenvPex
    from pants.engine.rules import collect_rules, Get, rule

    class Qux:
        pass

    @rule(desc="Ensure assignment name is not shadowed by new syntax")
    async def setup_black_shadowed(black: Black) -> Qux:
        create_venv_pex = await Get(VenvPex, PexRequest, black.to_pex_request())

    def rules():
        return collect_rules()
    """
)

MIGRATED_RULES2_FILE = dedent(
    """\
    from pants.backend.python.lint.black.subsystem import Black
    from pants.backend.python.util_rules.pex import PexRequest, VenvPex
    from pants.engine.rules import collect_rules, Get, rule
    from pants.backend.python.util_rules.pex import create_venv_pex as create_venv_pex_get
    from pants.engine.rules import implicitly

    class Qux:
        pass

    @rule(desc="Ensure assignment name is not shadowed by new syntax")
    async def setup_black_shadowed(black: Black) -> Qux:
        create_venv_pex = await create_venv_pex_get(**implicitly({black.to_pex_request(): PexRequest}))

    def rules():
        return collect_rules()
    """
)


def test_migrate_call_by_name_syntax():
    with setup_tmpdir(
        {
            "src/migrateme/__init__.py": "",
            "src/migrateme/BUILD": "python_sources()",
            "src/migrateme/register.py": REGISTER_FILE,
            "src/migrateme/rules1.py": RULES1_FILE,
            "src/migrateme/rules2.py": RULES2_FILE,
        }
    ) as tmpdir:
        argv = [
            f"--source-root-patterns=['{tmpdir}/src']",
            f"--pythonpath=['{tmpdir}/src']",
            "--backend-packages=['pants.backend.python.lint.black', 'migrateme']",
            "migrate-call-by-name",
            "--json",
            f"{tmpdir}::",
        ]

        result = run_pants(argv)
        result.assert_success()

        register_path = Path(tmpdir, "src/migrateme/register.py")
        rules1_path = Path(tmpdir, "src/migrateme/rules1.py")
        rules2_path = Path(tmpdir, "src/migrateme/rules2.py")

        # Ensure the JSON output contains the paths to the files we expect to migrate.
        assert all(str(p) in result.stdout for p in [register_path, rules1_path, rules2_path])

        with open(rules1_path) as f:
            assert f.read() == MIGRATED_RULES1_FILE
        with open(rules2_path) as f:
            assert f.read() == MIGRATED_RULES2_FILE
        with open(register_path) as f:
            assert f.read() == MIGRATED_REGISTER_FILE
