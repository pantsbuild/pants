import logging
from textwrap import dedent

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir

def test_local_dist(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    sources = {
        "hellotest/main.py": "print('Hello test')",
        "hellotest/BUILD": dedent(
            """\
            python_sources(name="libtest")

            python_distribution(
                name="dist",
                dependencies=[":libtest"],
                provides=python_artifact(name="dist", version="0.0.1"),
                wheel=True,
                sdist=False,
            )

            pyoxidizer_binary(
                name="bin",
                entry_point="hellotest.main",
                dependencies=[":dist"],
            )
            """
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=['pants.backend.python', 'pants.backend.experimental.python.packaging.pyoxidizer']",
            f"--source-root-patterns=['/{tmpdir}']",
            "package",
            f"{tmpdir}/hellotest:bin",
        ]
        result = run_pants(args)
        result.assert_success(f"{result.command} failed with {result.exit_code} -> {result.stderr}")
