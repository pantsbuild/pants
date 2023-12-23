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

This list is also available via `pants backends --help`, which includes any additional plugins in your repository that aren't built-in to Pants itself.

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
| `pants.backend.python.lint.pydocstyle`               | Enables pydocstyle, a Python docstring convention checker: <https://www.pydocstyle.org/>           | [Linters and formatters](doc:python-linters-and-formatters)       |
| `pants.backend.python.lint.pylint`                   | Enables Pylint, the Python linter: <https://www.pylint.org>                                        | [Linters and formatters](doc:python-linters-and-formatters)       |
| `pants.backend.python.lint.pyupgrade`                | Enables Pyupgrade, which upgrades to new Python syntax: <https://pypi.org/project/pyupgrade/>      | [Linters and formatters](doc:python-linters-and-formatters)       |
| `pants.backend.python.lint.yapf`                     | Enables Yapf, the Python formatter: <https://pypi.org/project/yapf/>                               | [Linters and formatters](doc:python-linters-and-formatters)       |
| `pants.backend.python.typecheck.mypy`                | Enables MyPy, the Python type checker: <https://mypy.readthedocs.io/en/stable/>.                   | [typecheck](doc:python-check-goal)                                |
| `pants.backend.shell`                                | Core Shell support, including shUnit2 test runner.                                                 | [Shell overview](doc:shell-overview)                              |
| `pants.backend.shell.lint.shfmt`                     | Enables shfmt, a Shell autoformatter: <https://github.com/mvdan/sh>.                               | [Shell overview](doc:shell-overview)                              |
| `pants.backend.shell.lint.shellcheck`                | Enables Shellcheck, a Shell linter: <https://www.shellcheck.net/>.                                 | [Shell overview](doc:shell-overview)                              |
| `pants.backend.tools.preamble`                       | Enables "preamble", a Pants fixer for copyright headers and shebang lines                          | [`preamble`](doc:reference-preamble)                              |
| `pants.backend.tools.taplo`                          | Enables Taplo, a TOML autoformatter: <https://taplo.tamasfe.dev>                                   |                                                                   |
| `pants.backend.url_handlers.s3`                      | Enables accessing s3 via credentials in `file(source=http_source(...))`                            |                                                                   |

Available experimental backends
-------------------------------

Pants offers [additional backends as previews](https://blog.pantsbuild.org/quick-feedback-on-new-features-via-experimental-backends/) that are still in development. These backends may still undergo major changes to improve the interface or fix bugs, with fewer (or no) deprecation warnings. If any of these backends are relevant to you, please try them, [ask any questions](doc:getting-help) you have, and [contribute improvements](doc:contributor-overview)! Volunteers like you jumping in to help is how these backends are promoted from preview to fully stable.

The list of all backends (both stable and experimental) is also available via `pants backends --help-advanced`, which includes any additional plugins in your repository that aren't built-in to Pants itself.

| Backend                                                            | What it does                                                                                               | Docs                                                        |
|:-------------------------------------------------------------------|:-----------------------------------------------------------------------------------------------------------|:------------------------------------------------------------|
| `pants.backend.experimental.adhoc`                                 | Enables support for executing arbitrary runnable targets.                                                  | [Integrating new tools without plugins](doc:adhoc-tool)     |
| `pants.backend.experimental.cc`                                    | Enables core C and C++ support.                                                                            |                                                             |
| `pants.backend.experimental.cc.lint.clangformat`                   | Enables clang-format, a C and C++ autoformatter: <https://clang.llvm.org/docs/ClangFormat.html>            |                                                             |
| `pants.backend.experimental.codegen.avro.java`                     | Enables generating Java from Avro                                                                          |                                                             |
| `pants.backend.experimental.codegen.protobuf.go`                   | Enables generating Go from Protocol Buffers.                                                               |                                                             |
| `pants.backend.experimental.codegen.protobuf.java`                 | Enables generating Java from Protocol Buffers.                                                             |                                                             |
| `pants.backend.experimental.codegen.protobuf.scala`                | Enables generating Scala from Protocol Buffers.                                                            |                                                             |
| `pants.backend.experimental.codegen.thrift.apache.java`            | Enables generating Java from Thrift using the Apache Thrift generator.                                     |                                                             |
| `pants.backend.experimental.codegen.thrift.scrooge.java`           | Enables generating Java from Thrift using the Scrooge Thrift IDL compiler.                                 |                                                             |
| `pants.backend.experimental.codegen.thrift.scrooge.scala`          | Enables generating Scala from Thrift using the Scrooge Thrift IDL compiler.                                |                                                             |
| `pants.backend.experimental.cue`                                   | Enables core Cue support: <https://cuelang.org/>                                                           |                                                             |
| `pants.backend.experimental.debian`                                | Enables support for packaging `.deb` files via `dpkg-deb`                                                  |                                                             |
| `pants.backend.experimental.go`                                    | Enables core Go support.                                                                                   | [Go overview](doc:go)                                       |
| `pants.backend.experimental.go.debug_goals`                        | Enables additional goals for introspecting Go targets                                                      | [Go overview](doc:go)                                       |
| `pants.backend.experimental.go.lint.golangci_lint`                 | Enable golangci-lint, a Go linter: <https://golangci-lint.run>                                             | [Go overview](doc:go)                                       |
| `pants.backend.experimental.go.lint.vet`                           | Enables support for running `go vet`                                                                       | [Go overview](doc:go)                                       |
| `pants.backend.experimental.helm`                                  | Enables core Helm support: <https://helm.sh>                                                               | [Helm overview](doc:helm-overview)                          |
| `pants.backend.experimental.helm.check.kubeconfirm`                | Enables Kubeconform, a fast Kubernetes manifest validator: <https://github.com/yannh/kubeconform>          | [Helm overview](doc:helm-overview)                          |
| `pants.backend.experimental.java`                                  | Enables core Java support.                                                                                 | [Java & Scala overview](doc:jvm-overview)                   |
| `pants.backend.experimental.java.debug_goals`                      | Enable additional goals for introspecting Java targets                                                     | [Java & Scala overview](doc:jvm-overview)                   |
| `pants.backend.experimental.java.lint.google_java_format`          | Enables Google Java Format.                                                                                | [Java & Scala overview](doc:jvm-overview)                   |
| `pants.backend.experimental.javascript`                            | Enables core JavaScript support.                                                                           |                                                             |
| `pants.backend.experimental.javascript.lint.prettier`              | Enables Prettier, a JavaScript (and more) autoformatter: <https://prettier.io>                             |                                                             |
| `pants.backend.experimental.kotlin`                                | Enables core Kotlin support                                                                                | [Kotlin](doc:kotlin)                                        |
| `pants.backend.experimental.kotlin.debug_goals`                    | Enables additional goals for introspecting Kotlin targets                                                  | [Kotlin](doc:kotlin)                                        |
| `pants.backend.experimental.kotlin.lint.ktlint`                    | Enables ktlint, an anti-bikeshedding linter with built-in formatter: <https://pinterest.github.io/ktlint/> | [Kotlin](doc:kotlin)                                        |
| `pants.backend.experimental.openapi`                               | Enables core OpenAPI support: <https://swagger.io/specification/>                                          | [`openapi`](doc:reference-openapi)                          |
| `pants.backend.experimental.openapi.codegen.java`                  | Enables generating Java from OpenAPI                                                                       |                                                             |
| `pants.backend.experimental.openapi.lint.openapi_format`           | Enables openapi-format: <https://github.com/thim81/openapi-format>                                         |                                                             |
| `pants.backend.experimental.openapi.lint.spectral`                 | Enables spectral: <https://github.com/stoplightio/spectral>                                                | [`spectral`](doc:reference-spectral)                        |
| `pants.backend.experimental.python`                                | Enables experimental rules for Python                                                                      |                                                             |
| `pants.backend.experimental.python.framework.django`               | Enables better support for projects using Django: <https://www.djangoproject.com>                          |                                                             |
| `pants.backend.experimental.python.framework.stevedore`            | Enables better support for projects using stevedore: <https://docs.openstack.org/stevedore/>               |                                                             |
| `pants.backend.experimental.python.lint.add_trailing_comma`        | Enables add-trailing-comma, a Python code formatter: <https://github.com/asottile/add-trailing-comma>      | [`add-trailing-comma`](doc:reference-add-trailing-comma)    |
| `pants.backend.experimental.python.lint.ruff`                      | Enables Ruff, an extremely fast Python linter: <https://beta.ruff.rs/docs/>                                | [Linters and formatters](doc:python-linters-and-formatters) |
| `pants.backend.experimental.python.packaging.pyoxidizer`           | Enables `pyoxidizer_binary` target.                                                                        | [PyOxidizer](doc:pyoxidizer)                                |
| `pants.backend.experimental.python.typecheck.pyright`              | Enables Pyright, a Python type checker: <https://github.com/microsoft/pyright>                             |                                                             |
| `pants.backend.experimental.python.typecheck.pytype`               | Enables Pytype, a Python type checker: <https://google.github.io/pytype/>                                  |                                                             |
| `pants.backend.experimental.rust`                                  | Enables core Rust support.                                                                                 |                                                             |
| `pants.backend.experimental.scala`                                 | Enables core Scala support.                                                                                | [Java & Scala overview](doc:jvm-overview)                   |
| `pants.backend.experimental.scala.debug_goals`                     | Enables additional goals for introspecting Scala targets                                                   | [Java & Scala overview](doc:jvm-overview)                   |
| `pants.backend.experimental.scala.lint.scalafmt`                   | Enables the Scalafmt formatter.                                                                            | [Java & Scala overview](doc:jvm-overview)                   |
| `pants.backend.experimental.swift`                                 | Enables core Swift support.                                                                                |                                                             |
| `pants.backend.experimental.terraform`                             | Enables core Terraform support.                                                                            |                                                             |
| `pants.backend.experimental.terraform.lint.tfsec`                  | Enables tfsec, for static analysis of Terraform: <https://aquasecurity.github.io/tfsec/>                   |                                                             |
| `pants.backend.experimental.tools.semgrep`                         | Enables semgrep, a fast multi-language static analysis engine: <https://semgrep.dev>                       | [`semgrep`](doc:reference-semgrep)                          |
| `pants.backend.experimental.tools.workunit_logger`                 | Enables the workunit logger for debugging pants itself                                                     | [`workunit-logger`](doc:reference-workunit-logger)          |
| `pants.backend.experimental.tools.yamllint`                        | Enables yamllint, a linter for YAML files: <https://yamllint.readthedocs.io/>                              | [`yamllint`](doc:reference-yamllint)                        |
| `pants.backend.experimental.visibility`                            | Enables `__dependencies_rules__` and `__dependents_rules__`                                                | [Visibility](doc:targets#visibility)                        |
| `pants.backend.python.providers.experimental.pyenv`                | Enables Pants to manage appropriate Python interpreters via pyenv                                          |                                                             |
| `pants.backend.python.providers.experimental.pyenv.custom_install` | Enables customising how the pyenv provider builds a Python interpreter                                     |                                                             |
