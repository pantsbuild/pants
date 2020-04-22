# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from textwrap import dedent

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_dir


class PythonAWSLambdaIntegrationTest(PantsRunIntegrationTest):
    @classmethod
    def hermetic(cls):
        return True

    def test_awslambda_bundle(self):
        with temporary_dir(cleanup=False) as distdir:
            with self.temporary_sourcedir() as src:
                pkg_dir = os.path.join(src, "src", "python", "helloworld")
                os.makedirs(pkg_dir)

                def create_file(name, content):
                    with open(os.path.join(pkg_dir, name), "w") as fp:
                        fp.write(content)

                create_file("__init__.py", "")
                create_file(
                    "handler.py",
                    dedent(
                        """
                    def handler(event, context):
                        print("Hello, world!")
                """
                    ),
                )
                create_file(
                    "BUILD",
                    dedent(
                        """
                    python_binary(
                      name='hello-bin',
                      sources=['handler.py'],
                    )
                    python_awslambda(
                      name='hello-lambda',
                      binary=':hello-bin',
                      handler='helloworld.handler:handler'
                    )
                """
                    ),
                )
                config = {
                    "GLOBAL": {
                        "pants_distdir": distdir,
                        "pythonpath": ["%(buildroot)s/contrib/awslambda/python/src/python"],
                        "backend_packages": [
                            "pants.backend.python",
                            "pants.contrib.awslambda.python",
                        ],
                    },
                }

                command = ["bundle", f"{pkg_dir}:hello-lambda"]
                pants_run = self.run_pants(command=command, config=config)
                self.assert_success(pants_run)

            # Now run the lambda via the wrapper handler injected by lambdex (note that this
            # is distinct from the pex's entry point - a handler must be a function with two arguments,
            # whereas the pex entry point is a module).
            awslambda = os.path.join(distdir, "hello-lambda.pex")
            result = subprocess.run(
                f'{awslambda} -c "from lambdex_handler import handler; handler(None, None)"',
                shell=True,
                env={"PEX_INTERPRETER": "1", "PATH": os.environ["PATH"]},
                stdout=subprocess.PIPE,
                encoding="utf-8",
                check=True,
            )
            self.assertEqual("Hello, world!", result.stdout.strip())
