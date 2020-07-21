# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_dir


class RunPythonBinaryIntegrationTest(PantsRunIntegrationTest):
    def test_sample_script(self) -> None:
        """Test that we properly run a `python_binary` target.

        This checks a few things:
        - We can handle source roots.
        - We properly load third party requirements.
        - We propagate the error code.
        """
        with temporary_dir(root_dir=get_buildroot()) as tmpdir:
            tmpdir_relative = Path(tmpdir).relative_to(get_buildroot())

            src_root1 = Path(tmpdir, "src_root1/project")
            src_root1.mkdir(parents=True)
            (src_root1 / "app.py").write_text(
                dedent(
                    """\
                    import sys
                    from utils.strutil import upper_case


                    if __name__ == "__main__":
                        print(upper_case("Hello world."))
                        print("Hola, mundo.", file=sys.stderr)
                        sys.exit(23)
                    """
                )
            )
            (src_root1 / "BUILD").write_text("python_binary(sources=['app.py'])")

            src_root2 = Path(tmpdir, "src_root2/utils")
            src_root2.mkdir(parents=True)
            (src_root2 / "strutil.py").write_text(
                dedent(
                    """\
                    def upper_case(s):
                        return s.upper()
                    """
                )
            )
            (src_root2 / "BUILD").write_text("python_library()")
            result = self.run_pants(
                [
                    "--dependency-inference",
                    (
                        f"--source-root-patterns=['/{tmpdir_relative}/src_root1', "
                        f"'/{tmpdir_relative}/src_root2']"
                    ),
                    "--pants-ignore=__pycache__",
                    "run",
                    f"{tmpdir_relative}/src_root1/project/app.py",
                ]
            )

        assert result.returncode == 23
        assert result.stdout_data == "HELLO WORLD.\n"
        assert "Hola, mundo.\n" in result.stderr_data
