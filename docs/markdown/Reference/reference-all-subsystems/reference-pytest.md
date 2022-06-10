---
title: "pytest"
slug: "reference-pytest"
hidden: false
createdAt: "2022-06-02T21:10:00.801Z"
updatedAt: "2022-06-02T21:10:01.226Z"
---
The pytest Python test framework (https://docs.pytest.org/).

Backend: <span style="color: purple"><code>pants.backend.python</code></span>
Config section: <span style="color: purple"><code>[pytest]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>args</code></h3>
  <code>--pytest-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;, ... -- [&lt;shell_str&gt; [&lt;shell_str&gt; [...]]]</code><br>
  <code>PANTS_PYTEST_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Arguments to pass directly to Pytest, e.g. `--pytest-args='-k test_foo --quiet'`.
</div>
<br>

<div style="color: purple">
  <h3><code>timeouts</code></h3>
  <code>--[no-]pytest-timeouts</code><br>
  <code>PANTS_PYTEST_TIMEOUTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Enable test target timeouts. If timeouts are enabled then test targets with a timeout= parameter set on their target will time out after the given number of seconds if not completed. If no timeout is set, then either the default timeout is used or no timeout is configured.
</div>
<br>

<div style="color: purple">
  <h3><code>export</code></h3>
  <code>--[no-]pytest-export</code><br>
  <code>PANTS_PYTEST_EXPORT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

If true, export a virtual environment with Pytest when running `./pants export`.

This can be useful, for example, with IDE integrations to point your editor to the tool's binary.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--pytest-version=&lt;str&gt;</code><br>
  <code>PANTS_PYTEST_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>pytest==7.0.1</code></span>

<br>

Requirement string for the tool.
</div>
<br>

<div style="color: purple">
  <h3><code>extra_requirements</code></h3>
  <code>--pytest-extra-requirements=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_PYTEST_EXTRA_REQUIREMENTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "pytest-cov&gt;=2.12,!=2.12.1,&lt;3.1"
]</pre></span>

<br>

Any additional requirement strings to use with the tool. This is useful if the tool allows you to install plugins or if you need to constrain a dependency to a certain version.
</div>
<br>

<div style="color: purple">
  <h3><code>lockfile</code></h3>
  <code>--pytest-lockfile=&lt;str&gt;</code><br>
  <code>PANTS_PYTEST_LOCKFILE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>&lt;default&gt;</code></span>

<br>

Path to a lockfile used for installing the tool.

Set to the string `<default>` to use a lockfile provided by Pants, so long as you have not changed the `--version` and `--extra-requirements` options, and the tool's interpreter constraints are compatible with the default. Pants will error or warn if the lockfile is not compatible (controlled by `[python].invalid_lockfile_behavior`). See https://github.com/pantsbuild/pants/blob/release_2.12.0rc2/src/python/pants/backend/python/subsystems/pytest.lock for the default lockfile contents.

Set to the string `<none>` to opt out of using a lockfile. We do not recommend this, though, as lockfiles are essential for reproducible builds.

To use a custom lockfile, set this option to a file path relative to the build root, then run `./pants generate-lockfiles --resolve=pytest`.

As explained at [Third-party dependencies](doc:python-third-party-dependencies), lockfile generation via `generate-lockfiles` does not always work and you may want to manually generate the lockfile. You will want to set `[python].invalid_lockfile_behavior = 'ignore'` so that Pants does not complain about missing lockfile headers.
</div>
<br>

<div style="color: purple">
  <h3><code>console_script</code></h3>
  <code>--pytest-console-script=&lt;str&gt;</code><br>
  <code>PANTS_PYTEST_CONSOLE_SCRIPT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>pytest</code></span>

<br>

The console script for the tool. Using this option is generally preferable to (and mutually exclusive with) specifying an --entry-point since console script names have a higher expectation of staying stable across releases of the tool. Usually, you will not want to change this from the default.
</div>
<br>

<div style="color: purple">
  <h3><code>entry_point</code></h3>
  <code>--pytest-entry-point=&lt;str&gt;</code><br>
  <code>PANTS_PYTEST_ENTRY_POINT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

The entry point for the tool. Generally you only want to use this option if the tool does not offer a --console-script (which this option is mutually exclusive with). Usually, you will not want to change this from the default.
</div>
<br>

<div style="color: purple">
  <h3><code>timeout_default</code></h3>
  <code>--pytest-timeout-default=&lt;int&gt;</code><br>
  <code>PANTS_PYTEST_TIMEOUT_DEFAULT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

The default timeout (in seconds) for a test target if the `timeout` field is not set on the target.
</div>
<br>

<div style="color: purple">
  <h3><code>timeout_maximum</code></h3>
  <code>--pytest-timeout-maximum=&lt;int&gt;</code><br>
  <code>PANTS_PYTEST_TIMEOUT_MAXIMUM</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

The maximum timeout (in seconds) that may be used on a `python_tests` target.
</div>
<br>

<div style="color: purple">
  <h3><code>junit_family</code></h3>
  <code>--pytest-junit-family=&lt;str&gt;</code><br>
  <code>PANTS_PYTEST_JUNIT_FAMILY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>xunit2</code></span>

<br>

The format of generated junit XML files. See https://docs.pytest.org/en/latest/reference.html#confval-junit_family.
</div>
<br>

<div style="color: purple">
  <h3><code>execution_slot_var</code></h3>
  <code>--pytest-execution-slot-var=&lt;str&gt;</code><br>
  <code>PANTS_PYTEST_EXECUTION_SLOT_VAR</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

If a non-empty string, the process execution slot id (an integer) will be exposed to tests under this environment variable name.
</div>
<br>

<div style="color: purple">
  <h3><code>config_discovery</code></h3>
  <code>--[no-]pytest-config-discovery</code><br>
  <code>PANTS_PYTEST_CONFIG_DISCOVERY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

If true, Pants will include all relevant Pytest config files (e.g. `pytest.ini`) during runs. See https://docs.pytest.org/en/stable/customize.html#finding-the-rootdir for where config files should be located for Pytest to discover them.
</div>
<br>


## Deprecated options

None