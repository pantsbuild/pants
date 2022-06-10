---
title: "test"
slug: "reference-test"
hidden: false
createdAt: "2022-06-02T21:09:30.189Z"
updatedAt: "2022-06-02T21:09:30.617Z"
---
```
./pants test [args]
```
Run tests.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[test]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>debug</code></h3>
  <code>--[no-]test-debug</code><br>
  <code>PANTS_TEST_DEBUG</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Run tests sequentially in an interactive process. This is necessary, for example, when you add breakpoints to your code.
</div>
<br>

<div style="color: purple">
  <h3><code>force</code></h3>
  <code>--[no-]test-force</code><br>
  <code>PANTS_TEST_FORCE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Force the tests to run, even if they could be satisfied from cache.
</div>
<br>

<div style="color: purple">
  <h3><code>output</code></h3>
  <code>--test-output=&lt;ShowOutput&gt;</code><br>
  <code>PANTS_TEST_OUTPUT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>all, failed, none</code></span><br>
<span style="color: green">default: <code>failed</code></span>

<br>

Show stdout/stderr for these tests.
</div>
<br>

<div style="color: purple">
  <h3><code>use_coverage</code></h3>
  <code>--[no-]test-use-coverage</code><br>
  <code>PANTS_TEST_USE_COVERAGE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Generate a coverage report if the test runner supports it.
</div>
<br>

<div style="color: purple">
  <h3><code>open_coverage</code></h3>
  <code>--[no-]test-open-coverage</code><br>
  <code>PANTS_TEST_OPEN_COVERAGE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

If a coverage report file is generated, open it on the local system if the system supports this.
</div>
<br>

<div style="color: purple">
  <h3><code>extra_env_vars</code></h3>
  <code>--test-extra-env-vars=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_TEST_EXTRA_ENV_VARS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Additional environment variables to include in test processes. Entries are strings in the form `ENV_VAR=value` to use explicitly; or just `ENV_VAR` to copy the value of a variable in Pants's own environment.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>report</code></h3>
  <code>--[no-]test-report</code><br>
  <code>PANTS_TEST_REPORT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Write test reports to --report-dir.
</div>
<br>

<div style="color: purple">
  <h3><code>report_dir</code></h3>
  <code>--test-report-dir=&lt;str&gt;</code><br>
  <code>PANTS_TEST_REPORT_DIR</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>{distdir}/test/reports</code></span>

<br>

Path to write test reports to. Must be relative to the build root.
</div>
<br>


## Deprecated options

<div style="color: purple">
  <h3><code>xml_dir</code></h3>
  <code>--test-xml-dir=&lt;DIR&gt;</code><br>
  <code>PANTS_TEST_XML_DIR</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>
<p style="color: darkred">Deprecated, is scheduled to be removed in version: 2.13.0.dev0.<br>Set the `report` option in [test] scope to emit reports to a standard location under dist/. Set the `report-dir` option to customize that location.</p>
<br>

Specifying a directory causes Junit XML result files to be emitted under that dir for each test run that supports producing them.
</div>
<br>