# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.testutil.pants_integration_test import PantsIntegrationTest, setup_tmpdir


class RunPythonBinaryIntegrationTest(PantsIntegrationTest):
    def test_sample_script(self) -> None:
        """Test that we properly run a `python_binary` target.

        This checks a few things:
        - We can handle source roots.
        - We properly load third party requirements.
        - We propagate the error code.
        """
        sources = {
            "src_root1/project/app.py": dedent(
                """\
                import sys
                from utils.strutil import upper_case


                if __name__ == "__main__":
                    print(upper_case("Hello world."))
                    print("Hola, mundo.", file=sys.stderr)
                    sys.exit(23)
                """
            ),
            "src_root1/project/BUILD": "python_binary(sources=['app.py'])",
            "src_root2/utils/strutil.py": dedent(
                """\
                def upper_case(s):
                    return s.upper()
                """
            ),
            "src_root2/utils/BUILD": "python_library()",
        }
        with setup_tmpdir(sources) as tmpdir:
            result = self.run_pants(
                [
                    "--backend-packages=pants.backend.python",
                    f"--source-root-patterns=['/{tmpdir}/src_root1', '/{tmpdir}/src_root2']",
                    "--pants-ignore=__pycache__",
                    "--pants-ignore=/src/python",
                    "run",
                    f"{tmpdir}/src_root1/project/app.py",
                ]
            )

        assert "Hola, mundo.\n" in result.stderr
        assert result.stdout == "HELLO WORLD.\n"
        assert result.exit_code == 23
