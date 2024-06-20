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

    from migrateme.rules1 import Bar, Foo, Thud, rules as rules1
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
        qux = await Get(Qux, Black, black)
        thud = await Get(Thud, Black, black)

    def rules():
        return [*collect_rules(), *rules1(), *rules2()]
    """
)

MIGRATED_REGISTER_FILE = dedent(
    """\
    from pants.backend.python.lint.black.subsystem import Black
    from pants.engine.rules import collect_rules, Get, rule, goal_rule
    from migrateme.rules1 import variants
    from migrateme.rules1 import multiline
    from migrateme.rules2 import shadowed
    from migrateme.rules1 import multiget
    from pants.engine.rules import implicitly
    from pants.engine.goal import Goal, GoalSubsystem

    from migrateme.rules1 import Bar, Foo, Thud, rules as rules1
    from migrateme.rules2 import Qux, rules as rules2

    class ContrivedGoalSubsystem(GoalSubsystem):
        name = "contrived-goal"
        help = "Need this to get the rule graph to create test migrations."

    class ContrivedGoal(Goal):
        subsystem_cls = ContrivedGoalSubsystem
        environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY

    @goal_rule
    async def setup_migrateme(black: Black) -> ContrivedGoal:
        foo = await variants(**implicitly({black: Black}))
        bar = await multiline(**implicitly({black: Black}))
        qux = await shadowed(**implicitly({black: Black}))
        thud = await multiget(**implicitly({black: Black}))

    def rules():
        return [*collect_rules(), *rules1(), *rules2()]
    """
)

RULES1_FILE = dedent(
    """\
    from pants.backend.python.lint.black.subsystem import Black
    from pants.backend.python.util_rules.pex import PexRequest, VenvPex
    from pants.core.goals.check import CheckRequest, CheckResults
    from pants.core.util_rules.archive import CreateArchive
    from pants.core.util_rules.system_binaries import BinaryPathRequest, BinaryPaths
    from pants.engine.environment import ChosenLocalEnvironmentName, EnvironmentName
    from pants.engine.fs import Digest, EMPTY_SNAPSHOT
    from pants.engine.rules import collect_rules, Get, MultiGet, rule
    from pants.engine.target import AllTargets

    async def non_annotated_rule_helpers():
        await Get(
            VenvPex,
            PexRequest,
            # Some comment that the AST parse wipes out, but CST should keep
            black.to_pex_request()
        )

    class Foo:
        pass

    @rule
    async def variants(black: Black, local_env: ChosenLocalEnvironmentName) -> Foo:
        all_targets = await Get(AllTargets)
        pex = await Get(VenvPex, PexRequest, black.to_pex_request())
        digest = await Get(Digest, CreateArchive(EMPTY_SNAPSHOT))
        paths = await Get(BinaryPaths, {{BinaryPathRequest(binary_name='time', search_path=['/usr/bin']): BinaryPathRequest, local_env.val: EnvironmentName}})
        try:
            try_all_targets_try = await Get(AllTargets)
        except:
            try_all_targets_except = await Get(AllTargets)
        else:
            try_all_targets_else = await Get(AllTargets)
        finally:
            try_all_targets_finally = await Get(AllTargets)
        if True:
            conditional_all_targets_if = await Get(AllTargets)
        elif False:
            conditional_all_targets_elif = await Get(AllTargets)
        else:
            conditional_all_targets_else = await Get(AllTargets)
        await non_annotated_rule_helpers()

    class Bar:
        pass

    @rule(desc="Ensure multi-line calls are migrated")
    async def multiline(black: Black) -> Bar:
        pex = await Get(
            VenvPex,
            PexRequest,
            black.to_pex_request()
        )

    class Thud:
        pass

    @rule(desc="Ensure calls used with multiget are migrated")
    async def multiget(black: Black) -> Thud:
        all_targets_get = Get(AllTargets)
        digest_get = Get(Digest, CreateArchive(EMPTY_SNAPSHOT))
        multigot = await MultiGet(
            Get(AllTargets),
            all_targets_get,
            Get(
                VenvPex,
                PexRequest,
                black.to_pex_request()
            ),
            digest_get
        )
        multigot_sameline = await MultiGet(
            Get(AllTargets), all_targets_get,
            Get(
                VenvPex,
                PexRequest,
                black.to_pex_request()
            ), digest_get
        )
        multigot_forloop = await MultiGet(
            Get(Digest, CreateArchive(EMPTY_SNAPSHOT))
            for i in [0, 1, 2]
        )

    def rules():
        return collect_rules()
    """
)

MIGRATED_RULES1_FILE = dedent(
    """\
    from pants.backend.python.lint.black.subsystem import Black
    from pants.backend.python.util_rules.pex import PexRequest, VenvPex
    from pants.core.goals.check import CheckRequest, CheckResults
    from pants.core.util_rules.archive import CreateArchive
    from pants.core.util_rules.system_binaries import BinaryPathRequest, BinaryPaths
    from pants.engine.environment import ChosenLocalEnvironmentName, EnvironmentName
    from pants.engine.fs import Digest, EMPTY_SNAPSHOT
    from pants.engine.rules import collect_rules, Get, concurrently, rule
    from pants.engine.internals.graph import find_all_targets
    from pants.backend.python.util_rules.pex import create_venv_pex
    from pants.core.util_rules.archive import create_archive
    from pants.core.util_rules.system_binaries import find_binary
    from pants.engine.rules import implicitly
    from pants.engine.target import AllTargets

    async def non_annotated_rule_helpers():
        await create_venv_pex(**implicitly({black.to_pex_request(): PexRequest}))

    class Foo:
        pass

    @rule
    async def variants(black: Black, local_env: ChosenLocalEnvironmentName) -> Foo:
        all_targets = await find_all_targets()
        pex = await create_venv_pex(**implicitly({black.to_pex_request(): PexRequest}))
        digest = await create_archive(CreateArchive(EMPTY_SNAPSHOT), **implicitly())
        paths = await find_binary(**implicitly({BinaryPathRequest(binary_name='time', search_path=['/usr/bin']): BinaryPathRequest, local_env.val: EnvironmentName}))
        try:
            try_all_targets_try = await find_all_targets()
        except:
            try_all_targets_except = await find_all_targets()
        else:
            try_all_targets_else = await find_all_targets()
        finally:
            try_all_targets_finally = await find_all_targets()
        if True:
            conditional_all_targets_if = await find_all_targets()
        elif False:
            conditional_all_targets_elif = await find_all_targets()
        else:
            conditional_all_targets_else = await find_all_targets()
        await non_annotated_rule_helpers()

    class Bar:
        pass

    @rule(desc="Ensure multi-line calls are migrated")
    async def multiline(black: Black) -> Bar:
        pex = await create_venv_pex(**implicitly({black.to_pex_request(): PexRequest}))

    class Thud:
        pass

    @rule(desc="Ensure calls used with multiget are migrated")
    async def multiget(black: Black) -> Thud:
        all_targets_get = find_all_targets()
        digest_get = create_archive(CreateArchive(EMPTY_SNAPSHOT), **implicitly())
        multigot = await concurrently(
            find_all_targets(),
            all_targets_get,
            create_venv_pex(**implicitly({black.to_pex_request(): PexRequest})),
            digest_get
        )
        multigot_sameline = await concurrently(
            find_all_targets(), all_targets_get,
            create_venv_pex(**implicitly({black.to_pex_request(): PexRequest})), digest_get
        )
        multigot_forloop = await concurrently(
            create_archive(CreateArchive(EMPTY_SNAPSHOT), **implicitly())
            for i in [0, 1, 2]
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
    async def shadowed(black: Black) -> Qux:
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
    async def shadowed(black: Black) -> Qux:
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

        # Ensure the JSON output contains the paths to the files we expect to migrate
        assert all(str(p) in result.stdout for p in [register_path, rules1_path, rules2_path])
        with open(register_path) as f:
            assert f.read() == MIGRATED_REGISTER_FILE
        with open(rules1_path) as f:
            assert f.read() == MIGRATED_RULES1_FILE
        with open(rules2_path) as f:
            assert f.read() == MIGRATED_RULES2_FILE
