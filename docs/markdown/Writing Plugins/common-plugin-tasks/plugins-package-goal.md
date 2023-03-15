---
title: "Package code"
slug: "plugins-package-goal"
excerpt: "How to add a new implementation to the `package` goal."
hidden: true
createdAt: "2020-07-01T04:54:11.398Z"
---
The `package` goal bundles all the relevant code and third-party dependencies into a single asset, such as a JAR, PEX, or zip file. 

Often, the asset is executable, but it need not be.

> 📘 Example repository
> 
> This guide walks through adding a simple `package` implementation for Bash that simply puts all the relevant source files into a `.zip` file.
> 
> This duplicates the `archive` target type, and is solely implemented for instructional purposes. See [here](https://github.com/pantsbuild/example-plugin/blob/main/pants-plugins/examples/bash/package_bash_binary.py) for the final implementation.

1. Set up a package target type (recommended)
---------------------------------------------

Usually, you will want to add a new target type for your implementation, such as `pex_binary` or `python_distribution`.

The fields depend on what makes sense for the package format you're adding support for. For example, when wrapping a binary format like Pex or PyInstaller, you may want a field corresponding to each of the tool's option, like `zip_safe` and `ignore_errors`. Often, you will want a field for the entry point.

Usually, you should include `OutputPathField` from `pants.core.goals.package` in your target's fields, which will allow the user to change where the package is built to.

See [Creating new targets](doc:target-api-new-targets) for a guide on how to define new target types. 

```python
from pants.core.goals.package import OutputPathField
from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, Sources, Target

class BashSources(Sources):
    expected_file_extensions = (".sh",)


class BashBinarySources(BashSources):
     required = True
     expected_num_files = 1


 class BashBinary(Target):
     """A Bash file that may be directly run."""

     alias = "bash_binary"
     core_fields = (*COMMON_TARGET_FIELDS, OutputPathField, Dependencies, BashBinarySources)
```

> 🚧 Binary targets and the `sources` field
> 
> We've found that it often works best for targets used by the `package` goal to not have a `sources` field. Instead, use a "library" target to describe the source code, and add the library as a dependency of the binary target. For example, a `pex_binary` target may depend on some `python_library` targets.
> 
> Why do we recommend not having a `sources` field? It can be helpful with modeling to have a clear separation between targets describing first-party code vs. artifacts you want to build. For example, this allows you to use a default value for the `sources` field of your library target without worrying that a user unintentionally set their binary's `sources` to overlap with the library's (things like dependency inference do not work as well when >1 target refer to the same source file.)
> 
> However, sometimes it does make sense to have a `sources` field, such as a `dockerfile` target type. Likewise, this guide uses a `sources` field for simplicity. 
> 
> Warning: If you do have a `sources` field, set `expected_num_files` to `1` or `range(0, 2)`. Because Pants operates on a file-level, it would try to create one distinct package for each source file belonging to your target, even though you probably only wanted a single package built.

2. Set up a subclass of `PackageFieldSet`
-----------------------------------------

As described in [Rules and the Target API](doc:rules-api-and-target-api), a `FieldSet` is a way to tell Pants which `Field`s you care about targets having for your plugin to work.

Create a new dataclass that subclasses `PackageFieldSet`. Set the class property `required_fields` to the fields your target must have registered to work. Usually, this is a field like `BashBinarySources` or `BashBinaryEntryPoint`.

```python
from dataclasses import dataclass

from pants.core.goals.package import OutputPathField, PackageFieldSet

@dataclass(frozen=True)
class BashBinaryFieldSet(PackageFieldSet):
    required_fields = (BashBinarySources,)

    sources: BashBinarySources
    output_path: OutputPathField
```

Then, register your new `PackageFieldSet` with a [`UnionRule`](doc:rules-api-unions) so that Pants knows your binary implementation exists:

```python
from pants.engine.rules import collect_rules
from pants.engine.unions import UnionRule

...

def rules():
    return [
      	*collect_rules(),
        UnionRule(PackageFieldSet, BashBinaryFieldSet),
    ]
```

3. Create a rule for your logic
-------------------------------

Your rule should take as a parameter the `PackageFieldSet` from Step 2. It should return `BuiltPackage`, which has the fields `digest: Digest` and `artifacts: Tuple[BuiltPackageArtifact, ...]`, where each `BuiltPackageArtifact` has the field `relpath: str` and optional `extra_log_lines: Tuple[str, ...]`.

Your package rule can have whatever logic you'd like to create a package. All that Pants cares about is that you return a valid `BuiltPackage` object. 

In this example, we simply create a `.zip` file with the `bash_binary` and all of its dependencies.

```python
from dataclasses import dataclass

from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.process import BinaryPathRequest, BinaryPaths, Process, ProcessResult
from pants.engine.rules import Get, rule
from pants.engine.target import TransitiveTargets
from pants.util.logging import LogLevel

from examples.bash.target_types import BashBinarySources, BashSources

...

@rule(level=LogLevel.DEBUG)
async def package_bash_binary(field_set: BashBinaryFieldSet) -> BuiltPckage:
    zip_program_paths = await Get(
        BinaryPaths,
        BinaryPathRequest(binary_name="zip", search_path=["/bin", "/usr/bin"]),
    )
    if not zip_program_paths.first_path:
        raise ValueError(
            "Could not find the `zip` program on `/bin` or `/usr/bin`, so cannot create a package "
            f"for {field_set.address}."
        )

    transitive_targets = await Get(TransitiveTargets, Addresses([field_set.address]))
    sources = await Get(
        SourceFiles,
        SourceFilesRequest(
            tgt[BashSources]
            for tgt in transitive_targets.closure
            if tgt.has_field(BashSources)
        ),
    )

    output_filename = field_set.output_path.value_or_default(
        field_set.address, file_ending="zip"
    )
    result = await Get(
        ProcessResult,
        Process(
            argv=(
                zip_program_paths.first_path,
                output_filename,
                *sources.snapshot.files,
            ),
            input_digest=sources.snapshot.digest,
            description=f"Zip {field_set.address} and its dependencies.",
            output_files=(output_filename,),
        ),
    )
    return BuiltPackage(
        result.output_digest, artifacts=(BuiltPackageArtifact(output_filename),)
    )

```

Note that we use `field_set.output_path.value_or_default` to determine the output filename, which will use the `output_path` field if defined, and will default to an unambiguous value otherwise.

Finally, update your plugin's `register.py` to activate this file's rules.

```python pants-plugins/bash/register.py
from bash import package_binary


def rules():
    return [*package_binary.rules()]
```

Now, when you run `pants package ::`, Pants should create packages for all your package target types in the `--pants-distdir` (defaults to `dist/`).

4. Add tests (optional)
-----------------------

Refer to [Testing rules](doc:rules-api-testing).
