---
title: "test"
slug: "python-test-goal"
excerpt: "Run tests with Pytest."
hidden: false
createdAt: "2020-03-16T16:19:56.071Z"
updatedAt: "2022-05-12T05:33:10.060Z"
---
Pants uses the popular [Pytest](https://docs.pytest.org/en/latest/) test runner to run Python tests. You may write your tests in Pytest-style, unittest-style, or mix and match both. 
[block:callout]
{
  "type": "success",
  "body": "Each file gets run as a separate process, which gives you fine-grained caching and better parallelism. Given enough cores, Pants will be able to run all your tests at the same time.\n\nThis also gives you fine-grained invalidation. If you run `./pants test ::`, and then you only change one file, then only tests that depended on that changed file will need to rerun.",
  "title": "Benefit of Pants: runs each file in parallel"
}
[/block]

[block:api-header]
{
  "title": "Examples"
}
[/block]
```bash
 # Run all tests in the repository.
❯ ./pants test ::

# Run all the tests in this directory.
❯ ./pants test helloworld/util:

# Run just the tests in this file.
❯ ./pants test helloworld/util/lang_test.py  

 # Run just one test.
❯ ./pants test helloworld/util/lang_test.py -- -k test_language_translator 
```
[block:api-header]
{
  "title": "Pytest version and plugins"
}
[/block]
To change the Pytest version, set the `version` option in the `[pytest]` scope.

To install any [plugins](https://docs.pytest.org/en/latest/plugins.html), add the pip requirement string to `extra_requirements` in the `[pytest]` scope, like this:
[block:code]
{
  "codes": [
    {
      "code": "[pytest]\nversion = \"pytest>=5.4\"\nextra_requirements.add = [\n  \"pytest-django>=3.9.0,<4\",\n  \"pytest-rerunfailures==9.0\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
If you change either `version` or `extra_requirements`, Pants's default lockfile for Pytest will not work. Either set the `lockfile` option to a custom path or `"<none>"` to opt out. See [Third-party dependencies](doc:python-third-party-dependencies#tool-lockfiles).

Alternatively, if you only want to install the plugin for certain tests, you can add the plugin to the `dependencies` field of your `python_test` / `python_tests` target. See [Third-party dependencies](doc:python-third-party-dependencies) for how to install Python dependencies. For example:
[block:code]
{
  "codes": [
    {
      "code": "pytest-django==3.10.0",
      "language": "text",
      "name": "requirements.txt"
    },
    {
      "code": "python_tests(\n   name=\"tests\",\n   # Normally, Pants infers dependencies based on imports. \n   # Here, we don't actually import our plugin, though, so \n   # we need to explicitly list it.\n   dependencies=[\"//:pytest-django\"],\n)",
      "language": "python",
      "name": "helloworld/util/BUILD"
    }
  ]
}
[/block]

[block:callout]
{
  "type": "warning",
  "title": "Avoid the `pytest-xdist` plugin",
  "body": "We do not recommend using this plugin because its concurrency conflicts with Pants' own parallelism. Using Pants will bring you similar benefits to `pytest-xdist` already: Pants will run each test target in parallel."
}
[/block]

[block:api-header]
{
  "title": "Controlling output"
}
[/block]
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

[block:callout]
{
  "type": "info",
  "title": "Tip: Use Pytest options to make output more or less verbose",
  "body": "See [\"Passing arguments to Pytest\"](doc:test#passing-arguments-to-pytest).\n\nFor example:\n\n```bash\n❯ ./pants test project/app_test.py -- -q\n```\n\nYou may want to permanently set the Pytest option `--no-header` to avoid printing the Pytest version for each test run:\n\n```toml\n[pytest]\nargs = [\"--no-header\"]\n```"
}
[/block]

[block:api-header]
{
  "title": "Passing arguments to Pytest"
}
[/block]
To pass arguments to Pytest, put them at the end after `--`, like this:

```bash
❯ ./pants test project/app_test.py -- -k test_function1 -vv -s
```

You can also use the `args` option in the `[pytest]` scope, like this:
[block:code]
{
  "codes": [
    {
      "code": "[pytest]\nargs = [\"-vv\"]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "Tip: some useful Pytest arguments",
  "body": "See https://docs.pytest.org/en/latest/usage.html for more information.\n\n* `-k expression`: only run tests matching the expression.\n* `-v`: verbose mode.\n* `-s`: always print the stdout and stderr of your code, even if a test passes."
}
[/block]

[block:callout]
{
  "type": "warning",
  "title": "How to use Pytest's `--pdb` option",
  "body": "You must run `./pants test --debug` for this to work properly. See the section \"Running tests interactively\" for more information."
}
[/block]

[block:api-header]
{
  "title": "Config files"
}
[/block]
Pants will automatically include any relevant config files in the process's sandbox: `pytest.ini`, `pyproject.toml`, `tox.ini`, and `setup.cfg`.
[block:api-header]
{
  "title": "`conftest.py`"
}
[/block]
Pytest uses [`conftest.py` files](https://docs.pytest.org/en/stable/fixture.html#conftest-py-sharing-fixture-functions) to share fixtures and config across multiple distinct test files. 

The default `sources` value for the `python_test_utils` target includes `conftest.py`. You can run [`./pants tailor ::`](doc:create-initial-build-files) to automatically add this target:

```
./pants tailor ::
Created project/BUILD:
  - Add python_sources target project
  - Add python_tests target tests
  - Add python_test_utils target test_utils
```

Pants will also infer dependencies on any `confest.py` files in the current directory _and_ any ancestor directories, which mirrors how Pytest behaves. This requires that each `conftest.py` has a target referring to it. You can verify this is working correctly by running `./pants dependencies path/to/my_test.py` and confirming that each `conftest.py` file shows up. (You can turn off this feature by setting `conftests = false` in the `[python-infer]` scope.)
[block:api-header]
{
  "title": "Setting environment variables"
}
[/block]
Test runs are _hermetic_, meaning that they are stripped of the parent `./pants` process's environment variables. This is important for reproducibility, and it also increases cache hits.

To add any arbitrary environment variable back to the process, you can either add the environment variable to the specific tests with the `extra_env_vars` field on `python_test` / `python_tests` targets or to all your tests with the `[test].extra_env_vars` option. Generally, prefer the field `extra_env_vars` field so that more of your tests are hermetic. 

With both `[test].extra_env_vars` and the `extra_env_vars` field, you can either hardcode a value or leave off a value to "allowlist" it and read from the parent `./pants` process's environment.
[block:code]
{
  "codes": [
    {
      "code": "[test]\nextra_env_vars = [\"VAR1\", \"VAR2=hardcoded_value\"]",
      "language": "toml",
      "name": "pants.toml"
    },
    {
      "code": "python_tests(\n    name=\"tests\",\n    # Adds to all generated `python_test` targets, \n    # i.e. each file in the `sources` field.\n    extra_env_vars=[\"VAR3\", \"VAR4=hardcoded\"],\n    # Even better, use `overrides` to be more granular.\n    overrides={\n        \"strutil_test.py\": {\"extra_env_vars\": [\"VAR\"]},\n        (\"dirutil_test.py\", \"osutil_test.py\"): {\"extra_env_vars\": [\"VAR5\"]},\n    },\n)",
      "language": "python",
      "name": "project/BUILD"
    }
  ]
}
[/block]

[block:api-header]
{
  "title": "Force reruns with `--force`"
}
[/block]
To force your tests to run again, rather than reading from the cache, run `./pants test --force path/to/test.py`.
[block:api-header]
{
  "title": "Running tests interactively"
}
[/block]
Because Pants runs multiple test targets in parallel, you will not see your test results appear on the screen until the test has completely finished. This means that you cannot use debuggers normally; the breakpoint will never show up on your screen and the test will hang indefinitely (or timeout, if timeouts are enabled). 

Instead, if you want to run a test interactively—such as to use a debugger like `pdb`—run your tests with `./pants test --debug`. For example:
[block:code]
{
  "codes": [
    {
      "code": "def test_debug():\n    import pdb; pdb.set_trace()\n    assert 1 + 1 == 2",
      "language": "python",
      "name": "test_debug_example.py"
    },
    {
      "code": "❯ ./pants test --debug test_debug_example.py\n\n===================================================== test session starts =====================================================\nplatform darwin -- Python 3.6.10, pytest-5.3.5, py-1.8.1, pluggy-0.13.1\nrootdir: /private/var/folders/sx/pdpbqz4x5cscn9hhfpbsbqvm0000gn/T/.tmpn2li0z\nplugins: cov-2.8.1, timeout-1.3.4\ncollected 6 items\n\ntest_debug_example.py\n>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> PDB set_trace (IO-capturing turned off) >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>\n> /private/var/folders/sx/pdpbqz4x5cscn9hhfpbsbqvm0000gn/T/.tmpn2li0z/test_debug_example.py(11)test_debug()\n-> assert 1 + 1 == 2\n(Pdb) 1 + 1\n2",
      "language": "text",
      "name": "Shell"
    }
  ]
}
[/block]
If you use multiple files with `test --debug`, they will run sequentially rather than in parallel.
[block:callout]
{
  "type": "info",
  "title": "Tip: using `ipdb` in tests",
  "body": "[`ipdb`](https://github.com/gotcha/ipdb) integrates IPython with the normal `pdb` debugger for enhanced features like autocomplete and improved syntax highlighting. `ipdb` is very helpful when debugging tests.\n\nTo be able to access `ipdb` when running tests, add this to your `pants.toml`:\n\n```toml\n[pytest]\nextra_requirements.add = [\"ipdb\"]\n```\n\nThen, you can use `import ipdb; ipdb.set_trace()` in your tests.\n\nTo run the tests you will need to add `-- -s` to the test call since ipdb will need stdin and pytest will capture it. \n\n```bash\n❯ ./pants test --debug  <target>   -- -s\n```"
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "Tip: using the IntelliJ/PyCharm remote debugger in tests",
  "body": "First, add this to your `pants.toml`:\n\n```toml\n[pytest]\nextra_requirements.add = [\"pydevd-pycharm==203.5419.8\"]  # Or whatever version you choose.\n```\n\nNow, use the remote debugger as usual:\n\n1. Start a Python remote debugging session in PyCharm, say on port 5000.\n2. Add the following code at the point where you want execution to pause and connect to the debugger:\n\n```python\nimport pydevd_pycharm\npydevd_pycharm.settrace('localhost', port=5000, stdoutToServer=True, stderrToServer=True)\n```\n\nRun your test with `./pants test --debug` as usual."
}
[/block]

[block:api-header]
{
  "title": "Timeouts"
}
[/block]
Pants can cancel tests which take too long. This is useful to prevent tests from hanging indefinitely.

To add a timeout, set the `timeout` field to an integer value of seconds, like this:
[block:code]
{
  "codes": [
    {
      "code": "python_test(name=\"tests\", source=\"tests.py\", timeout=120)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
When you set timeout on the `python_tests` target generator, the same timeout will apply to every generated `python_test` target.
[block:code]
{
  "codes": [
    {
      "code": "python_tests(\n    name=\"tests\",\n    overrides={\n        \"test_f1.py\": {\"timeout\": 20},\n        (\"test_f2.py\", \"test_f3.py\"): {\"timeout\": 35},\n    },\n)",
      "language": "python",
      "name": "BUILD"
    }
  ]
}
[/block]
You can also set a default value and a maximum value in `pants.toml`:
[block:code]
{
  "codes": [
    {
      "code": "[pytest]\ntimeout_default = 60\ntimeout_maximum = 600",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
If a target sets its `timeout` higher than `[pytest].timeout_maximum`, Pants will use the value in `[pytest].timeout_maximum`.
[block:callout]
{
  "type": "info",
  "title": "Tip: temporarily ignoring timeouts",
  "body": "When debugging locally, such as with `pdb`, you might want to temporarily disable timeouts. To do this, set `--no-pytest-timeouts`:\n\n```bash\n$ ./pants test project/app_test.py --no-pytest-timeouts\n```"
}
[/block]

[block:api-header]
{
  "title": "Test utilities and resources"
}
[/block]
### Test utilities

Use the target type `python_source` for test utilities, rather than `python_test`. 

To reduce boilerplate, you can use either the [`python_sources`](doc:reference-python_sources) or [`python_test_utils`](doc:reference-python_test_utils) targets to generate `python_source` targets. These behave the same, except that `python_test_utils` has a different default `sources` to include `conftest.py` and type stubs for tests (like `test_foo.pyi`). Use [`./pants tailor ::`](doc:create-initial-build-files) to generate both these targets automatically.

For example:
[block:code]
{
  "codes": [
    {
      "code": "# The default `sources` includes all files other than \n# `!*_test.py`, `!test_*.py`, and `tests.py`, and `conftest.py`.\npython_sources(name=\"lib\")\n\n# We leave off the `dependencies` field because Pants will infer \n# it based on import statements.\npython_tests(name=\"tests\")",
      "language": "python",
      "name": "helloworld/BUILD"
    },
    {
      "code": "...\n\n@contextmanager\ndef setup_tmpdir(files: Mapping[str, str]) -> Iterator[str]:\n    with temporary_dir() as tmpdir:\n        ...\n        yield rel_tmpdir",
      "language": "python",
      "name": "helloworld/testutils.py"
    },
    {
      "code": "from helloworld.testutils import setup_tmpdir\n\ndef test_app() -> None:\n    with setup_tmpdir({\"f.py\": \"print('hello')\"}):\n       assert ...",
      "language": "python",
      "name": "helloworld/app_test.py"
    }
  ]
}
[/block]
### Assets

Refer to [Assets](doc:assets) for how to include asset files in your tests by adding to the `dependencies` field.

It's often most convenient to use  `file` / `files` and `relocated_files` targets in your test code, although you can also use `resource` / `resources` targets.  
[block:api-header]
{
  "title": "Testing your packaging pipeline"
}
[/block]
You can include the result of `./pants package` in your test through the `runtime_package_dependencies` field. Pants will run the equivalent of `./pants package` beforehand and copy the built artifact into the test's chroot, allowing you to test things like that the artifact has the correct files present and that it's executable.

This allows you to test your packaging pipeline by simply running `./pants test ::`, without needing custom integration test scripts.

To depend on a built package, use the `runtime_package_dependencies` field on the `python_test` / `python_tests` target, which is a list of addresses to targets that can be built with `./pants package`, such as `pex_binary`, `python_awslambda`, and `archive` targets. Pants will build the package before running your test, and insert the file into the test's chroot. It will use the same name it would normally use with `./pants package`, except without the `dist/` prefix (set by the `output_path` field).

For example:
[block:code]
{
  "codes": [
    {
      "code": "# This target teaches Pants about our non-test Python files.\npython_sources(name=\"lib\")\n\npex_binary(\n    name=\"bin\",\n    entry_point=\"say_hello.py\",\n)\n\npython_tests(\n    name=\"tests\",\n    runtime_package_dependencies=[\":bin\"],\n)",
      "language": "python",
      "name": "helloworld/BUILD"
    },
    {
      "code": "print(\"Hello, test!\")",
      "language": "python",
      "name": "helloworld/say_hello.py"
    },
    {
      "code": "import subprocess\n\ndef test_say_hello():\n    assert  b\"Hello, test!\" in subprocess.check_output(['helloworld/bin.pex'])",
      "language": "python",
      "name": "helloworld/test_binary.py"
    }
  ]
}
[/block]

[block:api-header]
{
  "title": "Coverage"
}
[/block]
To report coverage using [`Coverage.py`](https://coverage.readthedocs.io/en/coverage-5.1/), set the option `--test-use-coverage`:

```bash
❯ ./pants test --use-coverage helloworld/util/lang_test.py
```

Or to permanently use coverage, set in your config file:
[block:code]
{
  "codes": [
    {
      "code": "[test]\nuse_coverage = true",
      "language": "toml",
      "name": "pants.ci.toml"
    }
  ]
}
[/block]

[block:callout]
{
  "type": "warning",
  "body": "Coverage defaults to running with Python 3.6+ when generating a report, which means it may fail to parse Python 2 syntax and Python 3.8+ syntax. You can fix this by changing the interpreter constraints for running Coverage:\n\n```toml\n# pants.toml\n[coverage-py]\ninterpreter_constraints = [\">=3.8\"]\n```\n\nHowever, if your repository has some Python 2-only code and some Python 3-only code, you will not be able to choose an interpreter that works with both versions. So, you will need to set up a `.coveragerc` config file and set `ignore_errors = True` under `[report]`, like this:\n\n```\n# .coveragerc\n[report]\nignore_errors = True\n```\n\n`ignore_errors = True` means that those files will simply be left off of the final coverage report.\n\n(Pants should autodiscover the config file `.coveragerc`. See [coverage-py](https://www.pantsbuild.org/docs/reference-coverage-py#section-config-discovery).)\n\nThere's a proposal for Pants to fix this by generating multiple reports when necessary: https://github.com/pantsbuild/pants/issues/11137. We'd appreciate your feedback.",
  "title": "Failure to parse files?"
}
[/block]
Coverage will report data on any files encountered during the tests. You can filter down the results by using the option `--coverage-py-filter` and passing the name(s) of modules you want coverage data for. Each module name is recursive, meaning submodules will be included. For example:

```bash
❯ ./pants test --use-coverage helloworld/util/lang_test.py --coverage-py-filter=helloworld.util
❯ ./pants test --use-coverage helloworld/util/lang_test.py --coverage-py-filter='["helloworld.util.lang", "helloworld.util.lang_test"]'
```
[block:callout]
{
  "type": "warning",
  "title": "Coverage will not report on unencountered files",
  "body": "Coverage will only report on files encountered during the tests' run. This means that your coverage score may be misleading; even with a score of 100%, you may have files without any tests. You can overcome this as follows:\n```toml\n# pants.toml\n[coverage-py]\nglobal_report = true\n```\n\nIn this case, Coverage will report on [all files it considers importable](https://coverage.readthedocs.io/en/6.3.2/source.html), i.e. files at the root of the tree, or in directories with a `__init__.py` file, possibly omitting files in [implicit namespace packages](https://peps.python.org/pep-0420/) that lack `__init__.py` files. This is a shortcoming of Coverage itself."
}
[/block]
Pants will default to writing the results to the console, but you can also output in HTML, XML, JSON, or the raw SQLite file:
[block:code]
{
  "codes": [
    {
      "code": "[coverage-py]\nreport = [\"raw\", \"xml\", \"html\", \"json\", \"console\"]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
You can change the output dir with the `output_dir` option in the `[coverage-py]` scope.

You may want to set `[coverage-py].fail_under` to cause Pants to gracefully fail if coverage is too low, e.g. `fail_under = 70`.

You may use a Coverage config file, e.g. `.coveragerc` or `pyproject.toml`. Pants will autodiscover the config file for you, and you can also set `[coverage-py].config` in your `pants.toml` to point to a non-standard location. You must include `relative_files = True` in the `[run]` section for Pants to work.
[block:code]
{
  "codes": [
    {
      "code": "[run]\nrelative_files = True\nbranch = True",
      "language": "text",
      "name": ".coveragerc"
    }
  ]
}
[/block]
When generating HTML, XML, and JSON reports, you can automatically open the reports through the option `--test-open-coverage`.
[block:api-header]
{
  "title": "JUnit XML results"
}
[/block]
Pytest can generate [JUnit XML result files](https://docs.pytest.org/en/6.2.x/usage.html#creating-junitxml-format-files). This allows you to hook up your results, for example, to dashboards.

To save JUnit XML result files, set the option `[test].xml_dir`, like this:
[block:code]
{
  "codes": [
    {
      "code": "[test]\nxml_dir = \"dist/test_results\"",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
You may also want to set the option `[pytest].junit_family` to change the format. Run `./pants help-advanced pytest` for more information.