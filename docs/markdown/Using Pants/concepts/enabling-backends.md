---
title: "Backends"
slug: "enabling-backends"
excerpt: "How to enable specific functionality."
hidden: false
createdAt: "2020-02-21T17:44:27.363Z"
---
Most Pants functionality is opt-in by adding the relevant _backend_ to the `[GLOBAL].backend_packages` option in `pants.toml`. For example:

```toml pants.toml
[GLOBAL]
backend_packages = [
  "pants.backend.shell",
  "pants.backend.python",
  "pants.backend.python.lint.black",
]
```

Available stable backends
-------------------------

| Backend                                              | What it does                                                                                       | Docs                                                              |
|:-----------------------------------------------------|:---------------------------------------------------------------------------------------------------|:------------------------------------------------------------------|
| `pants.backend.build_files.fmt.black`                | Enables autoformatting `BUILD` files using `black`.                                                |                                                                   |
| `pants.backend.build_files.fmt.buildifier`           | Enables autoformatting `BUILD` files using `buildifier`.                                           |                                                                   |
| `pants.backend.build_files.fmt.yapf`                 | Enables autoformatting `BUILD` files using `yapf`.                                                 |                                                                   |
| `pants.backend.awslambda.python`                     | Enables generating an AWS Lambda zip file from Python code.                                        | [AWS Lambda](doc:awslambda-python)                                |
| `pants.backend.codegen.protobuf.lint.buf`            | Activate the Buf formatter and linter for Protocol Buffers.                                        | [Protobuf](doc:protobuf-python)                                   |
| `pants.backend.codegen.protobuf.python`              | Enables generating Python from Protocol Buffers. Includes gRPC support.                            | [Protobuf and gRPC](doc:protobuf-python)                          |
| `pants.backend.codegen.thrift.apache.python`         | Enables generating Python from Apache Thrift.                                                      | [Thrift](doc:thrift-python)                                       |
| `pants.backend.docker`                               | Enables building, running, and publishing Docker images.                                           | [Docker overview](doc:docker)                                     |
| `pants.backend.docker.lint.hadolint`                 | Enables Hadolint, a Docker linter: <https://github.com/hadolint/hadolint>                          | [Docker overview](doc:docker)                                     |
| `pants.backend.google_cloud_function.python`         | Enables generating a Google Cloud Function from Python code.                                       | [Google Cloud Function](doc:google-cloud-function-python)         |
| `pants.backend.plugin_development`                   | Enables `pants_requirements` target.                                                               | [Plugins overview](doc:plugins-overview)                          |
| `pants.backend.python`                               | Core Python support.                                                                               | [Enabling Python support](doc:python-backend)                     |
| `pants.backend.python.mixed_interpreter_constraints` | Adds the `py-constraints` goal for insights on Python interpreter constraints.                     | [Interpreter compatibility](doc:python-interpreter-compatibility) |
| `pants.backend.python.lint.autoflake`                | Enables Autoflake, which removes unused Python imports: <https://pypi.org/project/autoflake/>      | [Linters and formatters](doc:python-linters-and-formatters)       |
| `pants.backend.python.lint.bandit`                   | Enables Bandit, the Python security linter: <https://bandit.readthedocs.io/en/latest/>.            | [Linters and formatters](doc:python-linters-and-formatters)       |
| `pants.backend.python.lint.black`                    | Enables Black, the Python autoformatter: <https://black.readthedocs.io/en/stable/>.                | [Linters and formatters](doc:python-linters-and-formatters)       |
| `pants.backend.python.lint.docformatter`             | Enables Docformatter, the Python docstring autoformatter: <https://github.com/myint/docformatter>. | [Linters and formatters](doc:python-linters-and-formatters)       |
| `pants.backend.python.lint.flake8`                   | Enables Flake8, the Python linter: <https://flake8.pycqa.org/en/latest/>.                          | [Linters and formatters](doc:python-linters-and-formatters)       |
| `pants.backend.python.lint.isort`                    | Enables isort, the Python import autoformatter: <https://timothycrosley.github.io/isort/>.         | [Linters and formatters](doc:python-linters-and-formatters)       |
| `pants.backend.python.lint.pylint`                   | Enables Pylint, the Python linter: <https://www.pylint.org>                                        | [Linters and formatters](doc:python-linters-and-formatters)       |
| `pants.backend.python.lint.pyupgrade`                | Enables Pyupgrade, which upgrades to new Python syntax: <https://pypi.org/project/pyupgrade/>      | [Linters and formatters](doc:python-linters-and-formatters)       |
| `pants.backend.python.lint.yapf`                     | Enables Yapf, the Python formatter: <https://pypi.org/project/yapf/>                               | [Linters and formatters](doc:python-linters-and-formatters)       |
| `pants.backend.python.typecheck.mypy`                | Enables MyPy, the Python type checker: <https://mypy.readthedocs.io/en/stable/>.                   | [typecheck](doc:python-check-goal)                                |
| `pants.backend.shell`                                | Core Shell support, including shUnit2 test runner.                                                 | [Shell overview](doc:shell)                                       |
| `pants.backend.shell.lint.shfmt`                     | Enables shfmt, a Shell autoformatter: <https://github.com/mvdan/sh>.                               | [Shell overview](doc:shell)                                       |
| `pants.backend.shell.lint.shellcheck`                | Enables Shellcheck, a Shell linter: <https://www.shellcheck.net/>.                                 | [Shell overview](doc:shell)                                       |

Available experimental backends
-------------------------------

Pants supports numerous extra backends that aren't as stable as the backends above, due to less extensive documentation, testing and sometimes missing features that inhibit usability. If any of these backends are relevant to you, please try them, [ask any questions](doc:getting-help) you have, and [contribute improvements](doc:contributor-overview)!

| Backend                                                   | What it does                                                                | Docs                                                        |
|:----------------------------------------------------------|:----------------------------------------------------------------------------|:------------------------------------------------------------|
| `pants.backend.experimental.codegen.protobuf.go`          | Enables generating Go from Protocol Buffers.                                |                                                             |
| `pants.backend.experimental.go`                           | Enables Go support.                                                         | [Go overview](doc:go)                                       |
| `pants.backend.experimental.java`                         | Enables core Java support.                                                  | [Java & Scala overview](doc:jvm-overview)                   |
| `pants.backend.experimental.java.lint.google_java_format` | Enables Google Java Format.                                                 | [Java & Scala overview](doc:jvm-overview)                   |
| `pants.backend.experimental.scala`                        | Enables core Scala support.                                                 | [Java & Scala overview](doc:jvm-overview)                   |
| `pants.backend.experimental.scala.lint.scalafmt`          | Enables the Scalafmt formatter.                                             | [Java & Scala overview](doc:jvm-overview)                   |
| `pants.backend.experimental.python.lint.ruff`             | Enables Ruff, an extremely fast Python linter: <https://beta.ruff.rs/docs/> | [Linters and formatters](doc:python-linters-and-formatters) |
| `pants.backend.experimental.python.packaging.pyoxidizer`  | Enables `pyoxidizer_binary` target.                                         | [PyOxidizer](doc:pyoxidizer)                                |
| `pants.backend.experimental.visibility`                   | Enables `__dependencies_rules__` and `__dependents_rules__`                 | [Visibility](doc:targets#visibility)                        |
