---
title: "Backends"
slug: "enabling-backends"
excerpt: "How to enable specific functionality."
hidden: false
createdAt: "2020-02-21T17:44:27.363Z"
updatedAt: "2022-04-20T22:31:51.974Z"
---
Most Pants functionality is opt-in by adding the relevant _backend_ to the `[GLOBAL].backend_packages` option in `pants.toml`. For example:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nbackend_packages = [\n  \"pants.backend.shell\",\n  \"pants.backend.python\",\n  \"pants.backend.python.lint.black\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]

[block:api-header]
{
  "title": "Available backends"
}
[/block]

[block:parameters]
{
  "data": {
    "h-0": "Backend",
    "h-1": "What it does",
    "17-0": "`pants.backend.python`",
    "17-1": "Core Python support.",
    "h-2": "Docs",
    "17-2": "[Enabling Python support](doc:python-backend)",
    "19-0": "`pants.backend.python.lint.bandit`",
    "19-1": "Enables Bandit, the Python security linter: https://bandit.readthedocs.io/en/latest/.",
    "19-2": "[Linters and formatters](doc:python-linters-and-formatters)",
    "20-0": "`pants.backend.python.lint.black`",
    "20-1": "Enables Black, the Python autoformatter: https://black.readthedocs.io/en/stable/.",
    "20-2": "[Linters and formatters](doc:python-linters-and-formatters)",
    "21-0": "`pants.backend.python.lint.docformatter`",
    "21-1": "Enables Docformatter, the Python docstring autoformatter: https://github.com/myint/docformatter.",
    "21-2": "[Linters and formatters](doc:python-linters-and-formatters)",
    "22-0": "`pants.backend.python.lint.flake8`",
    "23-0": "`pants.backend.python.lint.isort`",
    "24-0": "`pants.backend.python.lint.pylint`",
    "26-0": "`pants.backend.python.typecheck.mypy`",
    "26-2": "[typecheck](doc:python-typecheck-goal)",
    "22-2": "[Linters and formatters](doc:python-linters-and-formatters)",
    "23-2": "[Linters and formatters](doc:python-linters-and-formatters)",
    "24-2": "[Linters and formatters](doc:python-linters-and-formatters)",
    "18-0": "`pants.backend.python.mixed_interpreter_constraints`",
    "18-1": "Adds the `py-constraints` goal for insights on Python interpreter constraints.",
    "18-2": "[Interpreter compatibility](doc:python-interpreter-compatibility)",
    "0-0": "`pants.backend.awslambda.python`",
    "2-0": "`pants.backend.codegen.protobuf.python`",
    "2-1": "Enables generating Python from Protocol Buffers. Includes gRPC support.",
    "2-2": "[Protobuf and gRPC](doc:protobuf-python)",
    "0-1": "Enables generating an AWS Lambda zip file from Python code.",
    "0-2": "[AWS Lambda](doc:awslambda-python)",
    "22-1": "Enables Flake8, the Python linter: https://flake8.pycqa.org/en/latest/.",
    "23-1": "Enables isort, the Python import autoformatter: https://timothycrosley.github.io/isort/.",
    "24-1": "Enables Pylint, the Python linter: https://www.pylint.org",
    "26-1": "Enables MyPy, the Python type checker: https://mypy.readthedocs.io/en/stable/.",
    "27-0": "`pants.backend.shell`",
    "27-1": "Core Shell support, including shUnit2 test runner.",
    "27-2": "[Shell overview](doc:shell)",
    "28-0": "`pants.backend.shell.lint.shfmt`",
    "28-1": "Enables shfmt, a Shell autoformatter: https://github.com/mvdan/sh.",
    "28-2": "[Shell overview](doc:shell)",
    "29-0": "`pants.backend.shell.lint.shellcheck`",
    "29-1": "Enables Shellcheck, a Shell linter: https://www.shellcheck.net/.",
    "29-2": "[Shell overview](doc:shell)",
    "7-0": "`pants.backend.experimental.go`",
    "7-1": "Enables Go support.",
    "7-2": "[Go overview](doc:go)",
    "4-0": "`pants.backend.docker`",
    "4-1": "Enables building, running, and publishing Docker images.",
    "5-0": "`pants.backend.docker.lint.hadolint`",
    "5-1": "Enables Hadolint, a Docker linter: https://github.com/hadolint/hadolint",
    "5-2": "[Docker overview](doc:docker)",
    "4-2": "[Docker overview](doc:docker)",
    "12-0": "`pants.backend.experimental.python.lint.autoflake`",
    "25-0": "`pants.backend.python.lint.yapf`",
    "25-1": "Enables Yapf, the Python formatter: https://pypi.org/project/yapf/",
    "25-2": "[Linters and formatters](doc:python-linters-and-formatters)",
    "12-1": "Enables Autoflake, which removes unused Python imports: https://pypi.org/project/autoflake/",
    "12-2": "[Linters and formatters](doc:python-linters-and-formatters)",
    "13-0": "`pants.backend.experimental.python.lint.pyupgrade`",
    "13-1": "Enables Pyupgrade, which upgrades to new Python syntax: https://pypi.org/project/pyupgrade/",
    "13-2": "[Linters and formatters](doc:python-linters-and-formatters)",
    "15-0": "`pants.backend.google_cloud_function.python`",
    "15-1": "Enables generating a Google Cloud Function from Python code.",
    "15-2": "[Google Cloud Function](doc:google-cloud-function-python)",
    "3-2": "[Thrift](doc:thrift-python)",
    "3-1": "Enables generating Python from Apache Thrift.",
    "3-0": "`pants.backend.codegen.thrift.apache.python`",
    "8-0": "`pants.backend.experimental.java`",
    "8-1": "Enables core Java support.",
    "8-2": "[Java & Scala overview](doc:jvm-overview)",
    "10-0": "`pants.backend.experimental.scala`",
    "10-2": "[Java & Scala overview](doc:jvm-overview)",
    "10-1": "Enables core Scala support.",
    "9-0": "`pants.backend.experimental.java.lint.google_java_format`",
    "11-0": "`pants.backend.experimental.scala.lint.scalafmt`",
    "11-1": "Enables the Scalafmt formatter.",
    "11-2": "[Java & Scala overview](doc:jvm-overview)",
    "9-2": "[Java & Scala overview](doc:jvm-overview)",
    "9-1": "Enables Google Java Format.",
    "1-0": "`pants.backend.codegen.protobuf.lint.buf`",
    "1-2": "[Protobuf](doc:protobuf-python)",
    "1-1": "Activate the Buf formatter and linter for Protocol Buffers.",
    "6-0": "`pants.backend.experimental.codegen.protobuf.go`",
    "6-1": "Enables generating Go from Protocol Buffers.",
    "14-0": "`pants.backend.experimental.python.packaging.pyoxidizer`",
    "14-2": "[PyOxidizer](doc:pyoxidizer)",
    "14-1": "Enables `pyoxidizer_binary` target.",
    "16-0": "`pants.backend.plugin_devoplment`",
    "16-1": "Enables `pants_requirements` target.",
    "16-2": "[Plugins overview](doc:plugins-overview)"
  },
  "cols": 3,
  "rows": 30
}
[/block]