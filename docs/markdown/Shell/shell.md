---
title: "Shell overview"
slug: "shell"
excerpt: "Pants's support for Shellcheck, shfmt, and shUnit2."
hidden: false
createdAt: "2021-04-14T04:21:15.028Z"
updatedAt: "2022-05-03T23:52:45.915Z"
---
Pants integrates with these tools to empower you to follow best practices with your Shell scripts:

- [Shellcheck](https://www.shellcheck.net): lint for common Shell mistakes. 
- [shfmt](https://github.com/mvdan/sh): autoformat Shell code so that you can instead focus on the logic.
- [shUnit2](https://github.com/kward/shunit2/): write light-weight unit tests for your Shell code.

Pants installs these tools deterministically and integrates them into the workflows you already use: `./pants fmt`, `./pants lint`, and `./pants test`.
[block:api-header]
{
  "title": "Initial setup: add `shell_sources` targets"
}
[/block]
Pants uses [`shell_source`](doc:reference-shell_source) and [`shunit2_test`](doc:reference-shunit2_test) [targets](doc:targets) to know which Shell files you want to operate on and to set any metadata.

To reduce boilerplate, the [`shell_sources`](doc:reference-shell_sources) target generates a `shell_source` target for each file in its `sources` field, and [`shunit2_tests`](doc:reference-shunit2_tests) generates a `shunit2_test` target for each file in its `sources` field.
[block:code]
{
  "codes": [
    {
      "code": "shell_sources(name=\"lib\", sources=[\"deploy.sh\", \"changelog.sh\"])\nshell_tests(name=\"tests\", sources=[\"changelog_test.sh\"])\n\n# Spiritually equivalent to:\nshell_source(name=\"deploy\", source=\"deploy.sh\")\nshell_source(name=\"changelog\", source=\"changelog.sh\")\nshell_test(name=\"changelog_test\", source=\"changelog_test.sh\")\n\n# Thanks to the default `sources` values, spiritually equivalent to:\nshell_sources(name=\"lib\")\nshell_tests(name=\"tests\")",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
First, activate the Shell backend in your `pants.toml`:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nbackend_packages = [\n  \"pants.backend.shell\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
Then, run [`./pants tailor ::`](doc:create-initial-build-files) to generate BUILD files:

```
$ ./pants tailor ::
Created scripts/BUILD:
  - Add shell_sources target scripts
Created scripts/subdir/BUILD:
  - Add shell_sources target subdir
```

You can also manually add targets, which is necessary if you have any scripts that don't end in `.sh`:

```python
shell_source(name="script_without_a_extension", source="script_without_an_extension")
```
[block:callout]
{
  "type": "info",
  "title": "Shell dependency inference",
  "body": "Pants will [infer dependencies](doc:dependencies-and-dependency-inference) by looking for imports like `source script.sh` and `. script.sh`. You can check that the correct dependencies are inferred by running `./pants dependencies path/to/script.sh` and `./pants dependencies --transitive path/to/script.sh`.\n\nNormally, Pants will not understand dynamic sources, e.g. using variable expansion. However, Pants uses Shellcheck for parsing, so you can use Shellcheck's syntax to give a hint to Pants:\n\n```shell\nanother_script=\"dir/some_script.sh\"\n\n# Normally Pants couldn't infer this, but we can give a hint like this:\n# shellcheck source=dir/some_script.sh\nsource \"${another_script}\"\n```\n\nAlternatively, you can explicitly add `dependencies` in the relevant BUILD file.\n\n```python\nshell_sources(dependencies=[\"path/to:shell_source_tgt\"])\n```"
}
[/block]

[block:api-header]
{
  "title": "shfmt autoformatter"
}
[/block]
To activate, add this to your `pants.toml`:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nbackend_packages = [\n  \"pants.backend.shell\",\n  \"pants.backend.shell.lint.shfmt\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
Make sure that you also have set up `shell_source`/`shell_sources` or `shunit2_test`/`shunit2_tests` targets so that Pants knows to operate on the relevant files.

Now you can run `./pants fmt` and `./pants lint`:

```
$ ./pants lint scripts/my_script.sh
13:05:56.34 [WARN] Completed: lint - shfmt failed (exit code 1).
--- scripts/my_script.sh.orig
+++ scripts/my_script.sh
@@ -9,7 +9,7 @@

 set -eo pipefail

-HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && \
+HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" &&
   pwd)

𐄂 shfmt failed.
```

Use `./pants fmt lint dir:` to run on all files in the directory, and `./pants fmt lint dir::` to run on all files in the directory and subdirectories.

Pants will automatically include any relevant `.editorconfig` files in the run. You can also pass command line arguments with `--shfmt-args='-ci -sr'` or permanently set them in `pants.toml`:

```toml
[shfmt]
args = ["-i 2", "-ci", "-sr"]
```

Temporarily disable shfmt with `--shfmt-skip`:

```bash
./pants --shfmt-skip fmt ::
```

Only run shfmt with `--lint-only` and `--fmt-only`:

```bash
./pants fmt --only=shfmt ::
```
[block:callout]
{
  "type": "success",
  "title": "Benefit of Pants: shfmt runs in parallel with Python, Java, Scala, and Go formatters",
  "body": "Normally, Pants runs formatters sequentially so that it can pipe the results of one formatter into the next. However, Pants will run shfmt in parallel to formatters for other languages, [like Python](doc:python-linters-and-formatters), because shfmt does not operate on those languages.\n\nYou can see this concurrency through Pants's dynamic UI."
}
[/block]

[block:api-header]
{
  "title": "Shellcheck linter"
}
[/block]
To activate, add this to your `pants.toml`:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nbackend_packages = [\n  \"pants.backend.shell\",\n  \"pants.backend.shell.lint.shellcheck\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
Make sure that you also have set up `shell_source` / `shell_sources` or `shunit2_test` / `shunit_tests` targets so that Pants knows to operate on the relevant files.

Now you can run `./pants lint`:

```
$ ./pants lint scripts/my_script.sh
13:09:10.49 [WARN] Completed: lint - Shellcheck failed (exit code 1).

In scripts/my_script.sh line 12:
HERE=$(cd $(dirname ${BASH_SOURCE[0]}) && pwd)
          ^--------------------------^ SC2046: Quote this to prevent word splitting.
                    ^---------------^ SC2086: Double quote to prevent globbing and word splitting.

Did you mean:
...

𐄂 Shellcheck failed.
```

Use `./pants fmt lint dir:` to run on all files in the directory, and `./pants fmt lint dir::` to run on all files in the directory and subdirectories.

Pants will automatically include any relevant `.shellcheckrc` and `shellcheckrc` files in the run. You can also pass command line arguments with `--shellcheck-args='-x -W 3'` or permanently set them in `pants.toml`:

```toml
[shellcheck]
args = ["--external-sources", "--wiki-link-count=3"]
```

Temporarily disable Shellcheck with `--shellcheck-skip`:

```bash
./pants --shellcheck-skip lint ::
```

Only run Shellcheck with `--lint-only`:

```bash
./pants lint --only=shellcheck ::
```
[block:callout]
{
  "type": "success",
  "title": "Benefit of Pants: Shellcheck runs in parallel with other linters",
  "body": "Pants will attempt to run all activated linters and formatters at the same time for improved performance, including [Python](doc:python-linters-and-formatters), Go, Java, and Scala linters. You can see this through Pants's dynamic UI."
}
[/block]

[block:api-header]
{
  "title": "shUnit2 test runner"
}
[/block]
[shUnit2](https://github.com/kward/shunit2/) allows you to write lightweight unit tests for your Shell code.

To use shunit2 with Pants:

1. Create a test file like `tests.sh`, `test_foo.sh`, or `foo_test.sh`.
      - Refer to https://github.com/kward/shunit2/ for how to write shUnit2 tests.
2. Create a `shunit2_test` or `shunit2_tests` target in the directory's BUILD file.
    - You can run [`./pants tailor`](doc:create-initial-build-files) to automate this step.
3. Specify which shell to run your tests with, either by setting a shebang directly in the test file or by setting the field `shell` on the `shunit2_test` / `shunit2_tests` target.
     - See [here](doc:reference-shunit2_tests#codeshellcode) for all supported shells.
[block:code]
{
  "codes": [
    {
      "code": "#!/usr/bin/env bash\n\ntestEquality() {\n  assertEquals 1 1\n}",
      "language": "shell",
      "name": "scripts/tests.sh"
    },
    {
      "code": "shunit2_tests(name=\"tests\")",
      "language": "python",
      "name": "scripts/BUILD"
    }
  ]
}
[/block]
You can then run your tests like this:

```bash
# Run all tests in the repository.
./pants test ::

# Run all the tests in the folder.
./pants test scripts:

# Run just the tests in this file.
./pants test scripts/tests.sh
```

Pants will download the `./shunit2` script and will add `source ./shunit2` with the correct relpath for you.

You can import your production code by using `source`. Make sure the code belongs to a `shell_source` or `shell_sources` target. Pants's [dependency inference](doc:targets) will add the relevant dependencies, which you can confirm by running `./pants dependencies scripts/tests.sh`. You can also manually add to the `dependencies` field of your `shunit2_tests` target.
[block:code]
{
  "codes": [
    {
      "code": "#!/usr/bin/bash\n\nsource scripts/lib.sh\n\ntestAdd() {\n    assertEquals $(add_one 4) 5\n}",
      "language": "shell",
      "name": "scripts/tests.sh"
    },
    {
      "code": "add_one() {\n    echo $(($1 + 1))\n}",
      "language": "shell",
      "name": "scripts/lib.sh"
    },
    {
      "code": "shell_sources(name=\"lib\")\nshell_tests(name=\"tests\")",
      "language": "shell",
      "name": "scripts/BUILD"
    }
  ]
}
[/block]

[block:callout]
{
  "type": "success",
  "title": "Running your tests with multiple shells",
  "body": "Pants allows you to run the same tests against multiple shells, e.g. Bash and Zsh, to ensure your code works with each shell. \n\nTo test multiple shells, use the `parametrize` mechanism, like this:\n\n```python\nshunit2_tests(\n    name=\"tests\",\n    shell=parametrize(\"bash\", \"zsh\"),\n)\n```\n\nThen, use `./pants test`:\n\n```bash\n# Run tests with both shells.\n./pants test scripts/tests.sh\n\n# Run tests with only Zsh.\n./pants test scripts/tests.sh:tests@shell=zsh\n```"
}
[/block]
### Controlling output

By default, Pants only shows output for failed tests. You can change this by setting `--test-output` to one of `all`, `failed`, or `never`, e.g. `./pants test --output=all ::`.

You can permanently set the output format in your `pants.toml` like this:
[block:code]
{
  "codes": [
    {
      "code": "[test]\noutput = \"all\"",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
### Force reruns with `--force`

To force your tests to run again, rather than reading from the cache, run `./pants test --force path/to/test.sh`.

### Setting environment variables

Test runs are _hermetic_, meaning that they are stripped of the parent `./pants` process's environment variables. This is important for reproducibility, and it also increases cache hits.

To add any arbitrary environment variable back to the process, use the option `extra_env_vars` in the `[test]` options scope. You can hardcode a value for the option, or leave off a value to "allowlist" it and read from the parent `./pants` process's environment.
[block:code]
{
  "codes": [
    {
      "code": "[test]\nextra_env_vars = [\"VAR1\", \"VAR2=hardcoded_value\"]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
Use `[bash-setup].executable_search_paths` to change the `$PATH` env var used during test runs. You can use the special string `"<PATH>"` to read the value from the parent `./pants` process's environment.
[block:code]
{
  "codes": [
    {
      "code": "[bash-setup]\nexecutable_search_paths = [\"/usr/bin\", \"<PATH>\"]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
### Timeouts

Pants can cancel tests that take too long, which is useful to prevent tests from hanging indefinitely.

To add a timeout, set the `timeout` field to an integer value of seconds, like this:
[block:code]
{
  "codes": [
    {
      "code": "shunit2_test(name=\"tests\", source=\"tests.sh\", timeout=120)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
When you set `timeout` on the `shunit2_tests` target generator, the same timeout will apply to every generated `shunit2_test` target. Instead, you can use the `overrides` field:
[block:code]
{
  "codes": [
    {
      "code": "shunit2_tests(\n    name=\"tests\",\n    overrides={\n        \"test_f1.sh\": {\"timeout\": 20},\n        (\"test_f2.sh\", \"test_f3.sh\"): {\"timeout\": 35},\n    },\n)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
Unlike [with Python](doc:python-test-goal#timeouts), you cannot yet set a default or maximum timeout value, nor temporarily disable all timeouts. Please [let us know](doc:getting-help) if you would like this feature.

### Testing your packaging pipeline

You can include the result of `./pants package` in your test through the `runtime_package_dependencies field`. Pants will run the equivalent of `./pants package` beforehand and copy the built artifact into the test's chroot, allowing you to test things like that the artifact has the correct files present and that it's executable.

This allows you to test your packaging pipeline by simply running `./pants test ::`, without needing custom integration test scripts.

To depend on a built package, use the `runtime_package_dependencies` field on the `shunit2_test` / `shunit2_tests` targets, which is a list of addresses to targets that can be built with `./pants package`, such as [`pex_binary`](doc:python-package-goal), [`python_awslambda`](doc:awslambda-python), and [`archive`](doc:resources) targets. Pants will build the package before running your test, and insert the file into the test's chroot. It will use the same name it would normally use with `./pants package`, except without the `dist/` prefix.

For example:
[block:code]
{
  "codes": [
    {
      "code": "python_source(name=\"py_src\", source=\"say_hello.py\")\npex_binary(name=\"pex\", entry_point=\"say_hello.py\")\n\nshunit2_test(\n    name=\"tests\",\n    source=\"tests.sh\",\n    runtime_package_dependencies=[\":pex\"],\n)",
      "language": "python",
      "name": "helloworld/BUILD"
    },
    {
      "code": "print(\"Hello, test!\")",
      "language": "python",
      "name": "helloworld/say_hello.py"
    },
    {
      "code": "#!/usr/bin/bash\n\ntestArchiveCreated() {\n  assertTrue \"[[ -f helloworld/say_hello.pex ]]\"\n}",
      "language": "shell",
      "name": "helloworld/tests.sh"
    }
  ]
}
[/block]