# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from pants.backend.python.util_rules.pex import PexRequest
from pants.testutil.pants_integration_test import run_pants, setup_tmpdir

# @rule
# async def get_browser(request: BrowserRequest, open_binary: OpenBinary) -> Browser:
#     return Browser(open_binary, request.protocol, request.server)


# def rules():
#     return (
#         *collect_rules(),
#         QueryRule(ProcessResult, (Process, EnvironmentName)),
#     )

FILE_1 = dedent(
    """\
    from pants.engine.rules import Get, rule

    @rule
    async def setup_foo(subsystem: FooSubsystem) -> Foo:
        pex = await Get(VenvPex, PexRequest, subsystem.to_pex_request())

    @rule(desc="Ensure multi-line calls are migrated")
    async def setup_bar(bar: BarSubsystem) -> Bar:
        pex = await Get(
            VenvPex, 
            PexRequest, 
            bar.to_pex_request()
        )

    @rule(desc="Ensure calls with embedded comments are ignored")
    async def setup_baz(baz: BazSubsystem) -> Baz:
        pex = await Get(
            VenvPex, 
            PexRequest, 
            # Some comment that the AST parse wipes out, so we can't migrate this call safely
            bar.to_pex_request()
        )
    """
)

FILE_2 = dedent(
    """\
    from pants.engine.rules import Get, rule

    @rule(desc="Ensure assignment name is not shadowed by new syntax")
    async def setup_foo(subsystem: FooSubsystem) -> Foo:
        create_venv_pex = await Get(VenvPex, PexRequest, subsystem.to_pex_request())
    """
)

REGISTER_FILE = dedent(
    """\
    from src.py.app import rules as app_rules

    def rules():
        return app_rules()
    """
)
                
def test_migrate_call_by_name_syntax():
    with setup_tmpdir(
        {"src/py/register.py": REGISTER_FILE,  "src/py/app.py": FILE_1, "src/py/BUILD": "python_sources()"}
    ) as tmpdir:
        argv = [
            "--backend-packages=['src/py']",
            "migrate-call-by-name",
            f"{tmpdir}::",
        ]
        run_pants(argv).assert_success()
        result = run_pants(argv)
        print(result.stdout)
        print(result.stderr)
        # print content of FILE_1's changes
        with open(Path(tmpdir, "src/py/app.py")) as f:
            print(f.read())
        assert False
    