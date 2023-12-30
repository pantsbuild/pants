# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


def test_code_quality_tool_backend_generation() -> None:
    sources = {
        "src/BUILD": dedent(
            """
        python_source(name="bad_to_good", source="bad_to_good.py")

        code_quality_tool(
            name="bad_to_good_tool",
            runnable=":bad_to_good",
            file_glob_include=["**/*.py"],
            file_glob_exclude=["**/bad_to_good.py"],
        )
        """
        ),
        "src/bad_to_good.py": dedent(
            """
        import sys

        for fpath in sys.argv[1:]:
            with open(fpath) as f:
                contents = f.read()
            if 'badcode' in contents:
                with open(fpath, 'w') as f:
                    f.write(contents.replace('badcode', 'goodcode'))
            """
        ),
        "src/good_fmt.py": "thisisfine = 5\n",
        "src/needs_repair.py": "badcode = 10\n",
    }
    with setup_tmpdir(sources) as tmpdir:
        templated_backends = {
            "badcodefixer": {
                "template": "pants.backend.experimental.adhoc.code_quality_tool_backend_template",
                "goal": "fix",
                "target": f"{tmpdir}/src:bad_to_good_tool",
                "name": "Bad to Good",
            }
        }
        args = [
            "--backend-packages=['pants.backend.python', 'badcodefixer']",
            f"--templated-backends={templated_backends}",
            f"--source-root-patterns=['{tmpdir}/src']",
            "fix",
            f"{tmpdir}/src::",
        ]
        result = run_pants(args)
        assert "badcodefixer made changes" in result.stderr.strip()
        with open(f"{tmpdir}/src/needs_repair.py") as fixed_file:
            assert "goodcode = 10\n" == fixed_file.read()
