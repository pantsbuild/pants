---
title: "Run tests"
slug: "plugins-test-goal"
excerpt: "How to add a new test runner to the `test` goal."
hidden: false
createdAt: "2020-07-23T23:20:54.816Z"
---


1. Set up a test target type
----------------------------

Usually, you will want to add a "test" target type for your language, such as `shell_test` or `python_test`. A test target contrasts with a "source" target, such as `shell_source`. A test target is useful so that `pants test ::` doesn't try to run tests on non-test files.

When creating a test target, you should usually subclass `SingleSourceField`. You may also want to create `TimeoutField` (which should subclass `IntField`) and a `SkipField` (which should subclass `BoolField`).

See [Creating new targets](doc:target-api-new-targets) for a guide on how to define new target types.

```python
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    BoolField,
    IntField,
    SingleSourceField,
    Target,
)


class ExampleTestSourceField(SingleSourceField):
    expected_file_extensions = (".example",)


class ExampleTestTimeoutField(IntField):
     alias = "timeout"
     help = "Whether to time out after a certain period of time"


class SkipExampleTestsField(BoolField):
    alias = "skip_example_tests"
    default = False
    help = "If set, don't run tests on this source"


class ExampleTestTarget(Target):
    alias = "example_tests"
    help = "Example tests run by some tool"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        ExampleTestSourceField,
        ExampleTestTimeoutField,
        SkipExampleTestsField,
    )
```

2. Set up a subclass of `TestFieldSet`
--------------------------------------

Your test-runner will need access to some / most of the fields defined on your new target to actually execute the tests within. Collect those fields into a new subclass of `TestFieldSet`, and mark at least your source field as required.

If you have a "skip" field, use it in an `opt_out` method of your subclass:

```python
from pants.core.goals.test import TestFieldSet

@dataclass(frozen=True)
class ExampleTestFieldSet(TestFieldSet):
    required_fields = (ExamleTestSourceField,)
    sources: ExampleTestSourceField
    timeout: ExampleTestTimeoutField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipExampleTestsField).value
```

3. Set up a `Subsystem` for your test runner
--------------------------------------------

Test runners are expected to implement (at least) a `skip` option at a subsystem level.

```python
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem

class ExampleTestSubsystem(Subsystem):
    name = "Example"
    options_scope = "example-test"
    help = "Some tool to run tests"

    skip = SkipOption("test")
```

See [Options and subsystems](doc:rules-api-subsystems) for more information about defining new subsystems.

4. Set up a subclass of `TestRequest`
-------------------------------------

The rules used to drive batching and executing tests come from the `TestRequest` class. To use it, first declare a new subclass pointing at your subclasses of `TestFieldSet` and `Subsystem`:

```python
from pants.core.goals.test import TestRequest

@dataclass(frozen=True)
class ExampleTestRequest(TestRequest):
    field_set_type = ExampleTestFieldSet
    tool_subsystem = ExampleTestSubsystem
```

Then register the rules of your subclass:

```python
def rules():
    return [
        # Add to any other existing rules here:
        *ExampleTestRequest.rules()
    ]
```

In addition to registering your subclass as a valid `TestRequest`, this will automatically register rules to handle splitting your test inputs into single-element batches. If this is the correct behavior for your test runner, you can move on and skip the following section about defining a batching/partitioning rule. On the other hand, if your test runner supports testing multiple files in a single process (i.e. to share expensive setup logic), you can override the default `partitioner_type` on your `TestRequest` subclass:

```python
from pants.core.goals.test import PartitionerType

@dataclass(frozen=True)
class ExampleTestRequest(TestRequest):
    field_set_type = ExampleTestFieldSet
    tool_subsystem = ExampleTestSubsystem
    # Changed from the default:
    partitioner_type = PartitionerType.CUSTOM
```

This will prevent generation of the "default" partitioning rule, allowing you to implement a custom rule for grouping compatible tests into the same process.

5. Define a batching/partitioning `@rule`
-----------------------------------------


> 🚧 This step is optional
> Defining a partitioning rule is only required if you overrode the `partitioner_type` field in your `TestRequest` subclass to be `PartitionerType.CUSTOM`. Skip to the next section if your subclass is using the default `partitioner_type`.
Pants can run tests from multiple targets/files within the same process (for example, to share expensive setup/teardown logic across multiple files). Since it's not always safe/possible to batch test files together, each plugin defining a `test` implementation is expected to define a `@rule` for splitting field-sets into appropriate batches:

```python
from pants.core.goals.test import Partitions
from pants.engine.rules import collect_rules, rule

@rule
async def partition(
    request: ExampleTestRequest.PartitionRequest[ExampleTestFieldSet]
) -> Partitions:
    ...

def rules():
    return [
        # If it isn't already in the list:
        *collect_rules(),
    ]
```

The `Partitions` type is a custom collection of `Partition` objects, and a `Partition` is a `dataclass` containing:

  * A `tuple[TestFieldSetSubclass, ...]` of partition `elements`
  * An optional `metadata` field

Partition metadata can be any type implementing:
```python
@property
def description(self) -> str:
    ...
```

Any metadata returned by the partitioning rule will be passed back to your test runner as an input to the test execution rule, so it can be useful to declare a custom type modeling everything that's constant for a collection of `TestFieldSet` inputs:

```python
@dataclass(frozen=True)
class ExampleTestMetadata:
    common_property: str
    other_common_property: int | None
```

6. Define the main test execution `@rule`
-----------------------------------------

To actually execute your test runner, define a rule like:

```python
from pants.core.goals.test import TestResult

@rule
async def run_example_tests(
    batch: ExampleTestRequest.Batch[ExampleTestFieldSet, ExampleTestMetadata],
    # Any other subsystems/inputs you need.
) -> TestResult:
    ...
```

If you didn't define a custom metadata type, you can use `Any` as the second type argument to the `Batch` type:

```python
from pants.core.goals.test import TestResult

@rule
async def run_example_tests(
    batch: ExampleTestRequest.Batch[ExampleTestFieldSet, Any],
    # Any other subsystems/inputs you need.
) -> TestResult:
    ...
```

The `batch` input will have two properties:

  1. `elements` contains all the field sets that should be tested by your runner
  2. `metadata` contains any (optional) common data about the batch returned by your partitioning rule

If you didn't override the `partitioner_type` in your `TestRequest` subclass, `elements` will be a list of size 1 and `metadata` will be `None`. For convenience, you can use `batch.single_element` in this case to get the single field set. The `single_element` property will raise a `TypeError` if used on a batch with more than one element.

7. Define `@rule`s for debug testing
------------------------------------

`pants test` exposes `--debug` and `--debug-adapter` options for interactive execution of tests. To hook into these execution modes, opt-in in your `TestRequest` subclass and define one/both additional rules:

```python
from pants.core.goals.test import TestDebugAdapterRequest, TestDebugRequest
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem

@dataclass(frozen=True)
class ExampleTestRequest(TestRequest):
    ...  # Fields from earlier
    supports_debug = True  # Supports --debug
    supports_debug_adapter = True  # Supports --debug-adapter

@rule
async def setup_example_debug_test(
    batch: ExampleTestRequest.Batch[ExampleTestFieldSet, ExampleTestMetadata],
) -> TestDebugRequest:
    ...

@rule
async def setup_example_debug_adapter_test(
    batch: ExampleTestRequest.Batch[ExampleTestFieldSet, ExampleTestMetadata],
    debug_adapter: DebugAdapterSubsystem,
) -> TestDebugAdapterRequest:
    ...
```

Automatic retries for tests
---------------------------

Running the process without retries could look like this:

```python
result = await Get(FallibleProcessResult, Process, my_test_process)
```

Simply wrap the process in types that request the retries:
```python
results = await Get(
    ProcessResultWithRetries, ProcessWithRetries(my_test_process, retry_count)
)
last_result = results.last
```
