from pants.testutil.pants_integration_test import run_pants

def test_subsystem_help_is_registered() -> None:
    pants_run = run_pants(
        [
            "--backend-packages=pants.backend.experimental.python.packaging.pyoxidizer",
            "help",
            "pyoxidizer",
        ]
    )
    pants_run.assert_success()
    assert "PANTS_PYOXIDIZER_ARGS" in pants_run.stdout
