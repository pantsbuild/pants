---
title: "Run programs"
slug: "plugins-run-goal"
excerpt: "How to add a new implementation to the `run` goal."
hidden: true
createdAt: "2020-07-01T04:55:11.390Z"
---
The `run` goal runs a single interactive process in the foreground, such as running a script or a program.

> 📘 Example repository
> 
> This guide walks through adding a simple `run` implementation for Bash that runs the equivalent `/bin/bash ./script.sh`. See [here](https://github.com/pantsbuild/example-plugin/blob/main/pants-plugins/examples/bash/run_binary.py) for the final implementation.

1. Set up a binary target type
------------------------------

Usually, you will want to add a "binary" target type for your language, such as `bash_binary` or `python_binary`. Typically, both the `run` and `package` goals operate on binary target types.

When creating a binary target, you should usually subclass the `Sources` field and set the class property `expected_num_files = 1`.

See [Creating new targets](doc:target-api-new-targets) for a guide on how to define new target types. 

```python
from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, Sources, Target

class BashSources(Sources):
    expected_file_extensions = (".sh",)


class BashBinarySources(BashSources):
     required = True
     expected_num_files = 1


 class BashBinary(Target):
     """A Bash file that may be directly run."""

     alias = "bash_binary"
     core_fields = (*COMMON_TARGET_FIELDS, Dependencies, BashBinarySources)
```

2. Set up a subclass of `RunFieldSet`
-------------------------------------

As described in [Rules and the Target API](doc:rules-api-and-target-api), a `FieldSet` is a way to tell Pants which `Field`s you care about targets having for your plugin to work.

Usually, you will require the binary target's `Sources` subclass from Step 1, such as `BashBinarySources` or `PythonBinarySources`. Add this `Sources` subclass to the class property `required_fields` of your new `FieldSet`. This means that your binary implementation will run on any target with that sources field or a subclass of it.

Create a new dataclass that subclasses `RunFieldSet`:

```python
from dataclasses import dataclass

from pants.core.goals.run import RunFieldSet

@dataclass(frozen=True)
class BashRunFieldSet(RunFieldSet):
    required_fields = (BashBinarySources,)

    sources: BashBinarySources
```

Then, register your new `BashRunFieldSet` with a [`UnionRule`](doc:rules-api-unions) so that Pants knows your binary implementation exists:

```python
from pants.engine.rules import collect_rules
from pants.engine.unions import UnionRule

...

def rules():
    return [
      	*collect_rules(),
        *BashRunFieldSet.rules(),
    ]
```

3. Create a rule for your logic
-------------------------------

Your rule should take as a parameter the `BashRunFieldSet` from Step 2. It should return `RunRequest`, which has the fields `digest: Digest`, `args: Iterable[str]`, and `extra_env: Optional[Mapping[str, str]]`. 

The `RunRequest` will get converted into an `InteractiveProcess` that will run in the foreground.

The process will run in a temporary directory in the build root, which means that the script/program can access files that would normally need to be declared by adding a `files` or `resources` target to the `dependencies` field.

The process will not be hermetic, meaning that it will inherit the environment variables used by the `pants` process. Any values you set in `extra_env` will add or update the specified environment variables.

```python
from dataclasses import dataclass

from pants.core.goals.run import RunFieldSet, RunRequest
from pants.core.target_types import FilesSources, ResourcesSources
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.rules import Get, MultiGet, rule
from pants.engine.target import Sources, TransitiveTargets
from pants.util.logging import LogLevel

from examples.bash.target_types import BashBinarySources, BashSources

...

@rule(level=LogLevel.DEBUG)
async def run_bash_binary(field_set: BashRunFieldSet) -> RunRequest:
    # First, we find the `bash` program.
    bash_program_paths =  await Get(
        BinaryPaths, BinaryPathRequest(binary_name="bash", search_path=("/bin", "/usr/bin")),
    )
    if not bash_program_paths.first_path:
        raise EnvironmentError("Could not find the `bash` program on /bin or /usr/bin.")
    bash_program = bash_program_paths.first_path

    # We need to include all relevant transitive dependencies in the environment. We also get the
    # binary's sources so that we know the script name.
    transitive_targets = await Get(TransitiveTargets, Addresses([field_set.address]))
    binary_sources_request = Get(SourceFiles, SourceFilesRequest([field_set.sources]))
    all_sources_request = Get(
        SourceFiles,
        SourceFilesRequest(
            (tgt.get(Sources) for tgt in transitive_targets.closure),
            for_sources_types=(BashSources, FilesSources, ResourcesSources),
        ),
    )
    binary_sources, all_sources = await MultiGet(
        binary_sources_request, all_sources_request
    )

    # We join the relative path to our program with the template string "{chroot}", which will get
    # substituted with the path to the temporary directory where our program runs. This ensures
    # that we run the correct file.
    # Note that `BashBinarySources` will have already validated that there is exactly one file in
    # the sources field.
    script_name = os.path.join("{chroot}", binary_sources.files[0])

    return RunRequest(
        digest=all_sources.snapshot.digest,
        args=[bash_program.exe, script_name],
    )
```

In this example, we run the equivalent of `/bin/bash ./my_script.sh`. Typically, your `args` will include the program you're running, like `/bin/bash`, and the relative path to the binary file. For some languages, you may use values other than the file name; for example, Pants's `python_binary` target has an `entry_point` field, and the `run` implementation sets `args` to the equivalent of `python -m entry_point`.

When using relative paths in `args` or `extra_env`, you should join the values with the template string `"{chroot}"`, e.g. `os.path.join("{chroot}", binary_sources.files[0])`. This ensures that you run on the correct file in the temporary directory created by Pants.

Finally, update your plugin's `register.py` to activate this file's rules.

```python pants-plugins/bash/register.py
from bash import run_binary


def rules():
    return [*run_binary.rules()]
```

Now, when you run `pants run path/to/binary.sh`, Pants should run the program.

4. Define `@rule`s for debugging
------------------------------------

`pants run` exposes `--debug-adapter` options for debugging code. To hook into this behavior, opt-in in your `RunRequest` subclass and define an additional rule:

```python
from pants.core.goals.run import RunDebugAdapterRequest
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem

@dataclass(frozen=True)
class BashRunFieldSet(RunFieldSet):
    ...  # Fields from earlier
    supports_debug_adapter = True  # Supports --debug-adapter


@rule
async def run_bash_binary_debug_adapter(
    field_set: BashRunFieldSet,
    debug_adapter: DebugAdapterSubsystem,
) -> RunDebugAdapterRequest:
    ...
```

Your rule should be configured to wait for client connection before continuing.

5. Add tests (optional)
-----------------------

Refer to [Testing rules](doc:rules-api-testing). TODO
