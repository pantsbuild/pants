# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir

FILE_1 = dedent(
    """\
    from pants.backend.python.lint.black.subsystem import Black
    from pants.backend.python.util_rules.pex import PexRequest, VenvPex
    from pants.engine.rules import collect_rules, Get, rule

    @rule
    async def setup_black(black: Black) -> int:
        pex = await Get(VenvPex, PexRequest, black.to_pex_request())

    @rule(desc="Ensure multi-line calls are migrated")
    async def setup_black_multiline(black: Black) -> int:
        pex = await Get(
            VenvPex,
            PexRequest,
            black.to_pex_request()
        )

    @rule(desc="Ensure calls with embedded comments are ignored")
    async def setup_black_embedded_comments(black: Black) -> int:
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

# FILE_2 = dedent(
#     """\
#     from pants.engine.rules import collect_rules, Get, rule

#     @rule(desc="Ensure assignment name is not shadowed by new syntax")
#     async def setup_foo(subsystem: FooSubsystem) -> Foo:
#         create_venv_pex = await Get(VenvPex, PexRequest, subsystem.to_pex_request())

#     def rules():
#         return collect_rules()
#     """
# )

REGISTER_FILE = dedent(
    """\
    from migrateme.app import rules as app_rules

    def rules():
        return app_rules()
    """
)


def test_migrate_call_by_name_syntax():
    with setup_tmpdir(
        {
            "src/migrateme/__init__.py": "",
            "src/migrateme/BUILD": "python_sources()",
            "src/migrateme/register.py": REGISTER_FILE,
            "src/migrateme/app.py": FILE_1,
        }
    ) as tmpdir:
        argv = [
            f"--pythonpath=['{tmpdir}/src']",
            "--backend-packages=['pants.backend.python', 'pants.backend.python.lint.black', 'migrateme']",
            "migrate-call-by-name",
            "--json",
            f"{tmpdir}::",
        ]
        run_pants(argv).assert_success()
        result = run_pants(argv)
        print(result.stdout)
        print(result.stderr)
        # print content of FILE_1's changes
        # with open(Path(tmpdir, "src/migrateme/app.py")) as f:
        #     print(f.read())
        assert False
