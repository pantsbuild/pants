---
title: "Run tests"
slug: "plugins-test-goal"
excerpt: "How to add a new test runner to the `test` goal."
hidden: true
createdAt: "2020-07-23T23:20:54.816Z"
updatedAt: "2021-12-07T23:14:31.220Z"
---
[block:callout]
{
  "type": "info",
  "title": "Example repository",
  "body": "This guide walks through adding a simple `test` implementation for Bash that runs the `shunit2` test runner. See [here](https://github.com/pantsbuild/example-plugin/blob/main/pants-plugins/examples/bash/shunit2_test_runner.py) for the final implementation."
}
[/block]

[block:api-header]
{
  "title": "1. Set up a test target type"
}
[/block]
Usually, you will want to add a "test" target type for your language, such as `shell_test` or `python_test`. A test target contrasts with a "source" target, such as `shell_source`. A test target is useful so that `./pants test ::` doesn't try to run tests on non-test files.

When creating a test target, you should usually subclass `SingleSourceField`. You may also want to create `TimeoutField`, which should subclass `IntField`.

See [Creating new targets](doc:target-api-new-targets) for a guide on how to define new target types. 

```python
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    IntField,
    SingleSourceField,
    Target,
)

class ShellSourceField(SingleSourceField):
    expected_file_extensions = (".sh",)


class ShellTestSourceField(SingleSourceField):
    pass


class ShellTestTimeoutField(IntField):
     alias = "timeout"
     help = "Whether to time out after a certain period of time."


class ShellTestTarget(Target):
    alias = "bash_tests"
    help = "Shell tests that are run via `shunit2`."
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, ShellTestSourceField, ShellTestTimeoutField)
```
[block:api-header]
{
  "title": "2. Set up a subclass of `TestFieldSet`"
}
[/block]