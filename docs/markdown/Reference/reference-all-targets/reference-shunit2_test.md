---
title: "shunit2_test"
slug: "reference-shunit2_test"
hidden: false
createdAt: "2022-06-02T21:11:00.551Z"
updatedAt: "2022-06-02T21:11:01.063Z"
---
A single test file for Bourne-based shell scripts using the shunit2 test framework.

To use, add tests to your file per https://github.com/kward/shunit2/. Specify the shell to run with by either setting the field `shell` or including a shebang. To test the same file with multiple shells, create multiple `shunit2_tests` targets, one for each shell.

Pants will automatically download the `shunit2` bash script and add `source ./shunit2` to your test for you. If you already have `source ./shunit2`, Pants will overwrite it to use the correct relative path.

Backend: <span style="color: purple"><code>pants.backend.shell</code></span>

## <code>dependencies</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Addresses to other targets that this target depends on, e.g. ['helloworld/subdir:lib', 'helloworld/main.py:lib', '3rdparty:reqs#django'].

This augments any dependencies inferred by Pants, such as by analyzing your imports. Use `./pants dependencies` or `./pants peek` on this target to get the final result.

See [Targets and BUILD files](doc:targets)#target-addresses and [Targets and BUILD files](doc:targets)#target-generation for more about how addresses are formed, including for generated targets. You can also run `./pants list ::` to find all addresses in your project, or `./pants list dir:` to find all addresses defined in that directory.

If the target is in the same BUILD file, you can leave off the BUILD file path, e.g. `:tgt` instead of `helloworld/subdir:tgt`. For generated first-party addresses, use `./` for the file path, e.g. `./main.py:tgt`; for all other generated targets, use `:tgt#generated_name`.

You may exclude dependencies by prefixing with `!`, e.g. `['!helloworld/subdir:lib', '!./sibling.txt']`. Ignores are intended for false positives with dependency inference; otherwise, simply leave off the dependency from the BUILD file.

## <code>description</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A human-readable description of the target.

Use `./pants list --documented ::` to see all targets with descriptions.

## <code>runtime_package_dependencies</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Addresses to targets that can be built with the `./pants package` goal and whose resulting artifacts should be included in the test run.

Pants will build the artifacts as if you had run `./pants package`. It will include the results in your test's chroot, using the same name they would normally have, but without the `--distdir` prefix (e.g. `dist/`).

You can include anything that can be built by `./pants package`, e.g. a `pex_binary`, `python_awslambda`, or an `archive`.

## <code>shell</code>

<span style="color: purple">type: <code>'bash' | 'dash' | 'ksh' | 'pdksh' | 'sh' | 'zsh' | None</code></span>
<span style="color: green">default: <code>None</code></span>

Which shell to run the tests with. If unspecified, Pants will look for a shebang line.

## <code>skip_shellcheck</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.shell.lint.shellcheck</code></span>

If true, don't run Shellcheck on this target's code.

## <code>skip_shfmt</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.shell.lint.shfmt</code></span>

If true, don't run shfmt on this target's code.

## <code>skip_tests</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>

If true, don't run this target's tests.

## <code>source</code>

<span style="color: purple">type: <code>str</code></span>
<span style="color: green">required</span>

A single file that belongs to this target.

Path is relative to the BUILD file's directory, e.g. `source='example.ext'`.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.

## <code>timeout</code>

<span style="color: purple">type: <code>int | None</code></span>
<span style="color: green">default: <code>None</code></span>

A timeout (in seconds) used by each test file belonging to this target.

If unset, the test will never time out.