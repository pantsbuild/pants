---
title: "Add a formatter"
slug: "plugins-fmt-goal"
excerpt: "How to add a new formatter to the `fmt` and `lint` goals."
hidden: false
createdAt: "2020-07-01T04:52:28.820Z"
updatedAt: "2022-04-27T18:37:11.334Z"
---
In Pants, every formatter is (typically) also a linter, meaning that if you can run a tool with `./pants fmt`, you can run the same tool in check-only mode with `./pants lint`. Start by skimming [Add a linter](doc:plugins-lint-goal) to familiarize yourself with how linters work. 

This guide assumes that you are running a formatter that already exists outside of Pants as a stand-alone binary, such as running Black or Prettier.

If you are instead writing your own formatting logic inline, you can skip Step 1. In Step 4, you will not need to use `Process`.

1. Install your formatter
-------------------------

There are several ways for Pants to install your formatter. See [Installing tools](doc:rules-api-installing-tools). This example will use `ExternalTool` because there is already a pre-compiled binary for shfmt.

You will also likely want to register some options, like `--config`, `--skip`, and `--args`. Options are registered through a [`Subsystem`](doc:rules-api-subsystems). If you are using `ExternalTool`, this is already a subclass of `Subsystem`. Otherwise, create a subclass of `Subsystem`. Then, set the class property `options_scope` to the name of the tool, e.g. `"shfmt"` or `"prettier"`. Finally, add options from `pants.option.option_types`.

```python
from pants.core.util_rules.external_tool import ExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import ArgsListOption, SkipOption


class Shfmt(ExternalTool):
    """An autoformatter for shell scripts (https://github.com/mvdan/sh)."""

    options_scope = "shfmt"
    name = "Shfmt"
    default_version = "v3.2.4"
    default_known_versions = [
        "v3.2.4|macos_arm64 |e70fc42e69debe3e400347d4f918630cdf4bf2537277d672bbc43490387508ec|2998546",
        "v3.2.4|macos_x86_64|43a0461a1b54070ddc04fbbf1b78f7861ee39a65a61f5466d15a39c4aba4f917|2980208",
        "v3.2.4|linux_arm64 |6474d9cc08a1c9fe2ef4be7a004951998e3067d46cf55a011ddd5ff7bfab3de6|2752512",
        "v3.2.4|linux_x86_64|3f5a47f8fec27fae3e06d611559a2063f5d27e4b9501171dde9959b8c60a3538|2797568",
    ]

    # We set this because we need the mapping for both `generate_exe` and `generate_url`.
    platform_mapping = {
        "macos_arm64": "darwin_arm64",
        "macos_x86_64": "darwin_amd64",
        "linux_arm64": "linux_arm64",
        "linux_x86_64": "linux_amd64",
    }

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="-i 2")

    def generate_url(self, plat: Platform) -> str:
        plat_str = self.platform_mapping[plat.value]
        return (
            f"https://github.com/mvdan/sh/releases/download/{self.version}/"
            f"shfmt_{self.version}_{plat_str}"
        )

    def generate_exe(self, plat: Platform) -> str:
        plat_str = self.platform_mapping[plat.value]
        return f"./shfmt_{self.version}_{plat_str}"
```

2. Set up a `FieldSet` and `FmtRequest`/`LintTargetsRequest`
------------------------------------------------------------

As described in [Rules and the Target API](doc:rules-api-and-target-api), a `FieldSet` is a way to tell Pants which `Field`s you care about targets having for your plugin to work.

Usually, you should add a subclass of `SourcesField` to the class property `required_fields`, such as `ShellSourceField` or `PythonSourceField`. This means that your linter will run on any target with that sources field or a subclass of it.

Create a new dataclass that subclasses `FieldSet`:

```python
from dataclasses import dataclass

from pants.engine.target import FieldSet

...

@dataclass(frozen=True)
class ShfmtFieldSet(FieldSet):
    required_fields = (ShellSourceField,)

    sources: ShellSourceField
```

Then, hook this up to a new subclass of both `LintTargetsRequest` and `FmtRequest`.

```python
from pants.core.goals.fmt import FmtRequest
from pants.core.goals.lint import LintTargetsRequest

class ShfmtRequest(FmtRequest, LintRequest):
    field_set_type = ShfmtFieldSet
    name = "shfmt"
```

Finally, register your new `LintTargetsRequest`/`FmtRequest` with two [`UnionRule`s](doc:rules-api-unions) so that Pants knows your formatter exists:

```python
from pants.engine.unions import UnionRule

...

def rules():
    return [
      	*collect_rules(),
        UnionRule(FmtRequest, ShfmtRequest),
        UnionRule(LintTargetsRequest, ShfmtRequest),
    ]
```

3. Create `fmt` and `lint` rules
--------------------------------

You will need rules for both `fmt` and `lint`. Both rules should take the `LintTargetsRequest`/`FmtRequest` from step 3  (e.g. `ShfmtRequest`) as a parameter. The `fmt` rule should return `FmtResult`, and the `lint` rule should return `LintResults`.

```python
@rule(desc="Format with shfmt")
async def shfmt_fmt(request: ShfmtRequest, shfmt: Shfmt) -> FmtResult:
    ...
    return FmtResult(..., formatter_name=request.name)


@rule(desc="Lint with shfmt")
async def shfmt_lint(request: ShfmtRequest, shfmt: Shfmt) -> LintResults:
    ...
    return LintResults([], linter_name=request.name)
```

The `fmt` and `lint` rules will be very similar, except that a) the `argv` to your `Process` will be different, b) for `lint`, you should use `await Get(FallibleProcessResult, Process)` so that you tolerate failures, whereas `fmt` should use `await Get(ProcessResult, Process)`. To avoid duplication between the `fmt` and `lint` rules, you should set up a helper `setup` rule, along with dataclasses for `SetupRequest` and `Setup`.

```python
@dataclass(frozen=True)
class SetupRequest:
    request: ShfmtRequest
    check_only: bool


@dataclass(frozen=True)
class Setup:
    process: Process
    original_digest: Digest


@rule(level=LogLevel.DEBUG)
async def setup_shfmt(setup_request: SetupRequest, shfmt: Shfmt) -> Setup:
    download_shfmt_get = Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        shfmt.get_request(Platform.current),
    )

    # If the user specified `--shfmt-config`, we must search for the file they specified with
    # `PathGlobs` to include it in the `input_digest`. We error if the file cannot be found.
    config_digest_get = Get(
        Digest,
        PathGlobs(
            globs=[shfmt.config] if shfmt.config else [],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--shfmt-config`",
        ),
    )

    source_files_get= Get(
        SourceFiles,
        SourceFilesRequest(
            field_set.source for field_set in setup_request.request.field_sets
        ),
    )

    downloaded_shfmt, source_files = await MultiGet(
        download_shfmt_get, source_files_get
    )

    # If we were given an input digest from a previous formatter for the source files, then we
    # should use that input digest instead of the one we read from the filesystem.
    source_files_snapshot = (
        source_files.snapshot
        if setup_request.request.prior_formatter_result is None
        else setup_request.request.prior_formatter_result
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (source_files_snapshot.digest, downloaded_shfmt.digest)
        ),
    )

    argv = [
        downloaded_shfmt.exe,
        "-d" if setup_request.check_only else "-w",
        *shfmt.args,
        *source_files_snapshot.files,
    ]
    process = Process(
        argv=argv,
        input_digest=input_digest,
        output_files=source_files_snapshot.files,
        description=f"Run shfmt on {pluralize(len(setup_request.request.field_sets), 'file')}.",
        level=LogLevel.DEBUG,
    )
    return Setup(process, original_digest=source_files_snapshot.digest)


@rule(desc="Format with shfmt", level=LogLevel.DEBUG)
async def shfmt_fmt(request: ShfmtRequest, shfmt: Shfmt) -> FmtResult:
    if shfm.skip:
        return FmtResult.skip(formatter_name=request.name)
    setup = await Get(Setup, SetupRequest(request, check_only=False))
    result = await Get(ProcessResult, Process, setup.process)
    return FmtResult.from_process_result(
        result, original_digest=setup.original_digest, formatter_name=request.name
    )


@rule(desc="Lint with shfmt", level=LogLevel.DEBUG)
async def shfmt_lint(request: ShfmtRequest, shfmt: Shfmt) -> LintResults:
    if shfmt..skip:
        return LintResults([], linter_name=request.name)
    setup = await Get(Setup, SetupRequest(request, check_only=True))
    result = await Get(FallibleProcessResult, Process, setup.process)
    return LintResults(
        [LintResult.from_fallible_process_result(result)], linter_name=request.name
    )
```

The `FmtRequest`/`LintRequest` has a property called `.field_sets`, which stores a collection of the `FieldSet`s defined in step 2. Each `FieldSet` corresponds to a single target. Pants will have already validated that there is at least one valid `FieldSet`, so you can expect `ShfmtRequest.field_sets` to have 1-n `FieldSet` instances. 

If you have a `--skip` option, you should check if it was used at the beginning of your `fmt` and `lint` rules and, if so, to early return an empty `LintResults()` and return `FmtResult.skip()`.

Use `Get(SourceFiles, SourceFilesRequest)` to get all the sources you want to run your linter on. However, you should check if the `FmtRequest.prior_formatter_result` is set, and if so, use that value instead. This ensures that the result of any previous formatters is used, rather than the original source files. 

If you used `ExternalTool` in step 1, you will use `Get(DownloadedExternalTool, ExternalToolRequest)` in the `setup` rule to install the tool.

Use `Get(Digest, MergeDigests)` to combine the different inputs together, such as merging the source files and downloaded tool.

Finally, update your plugin's `register.py` to activate this file's rules. Note that we must register the rules added in Step 2, as well.

```python pants-plugins/shell/register.py
from shell import shfmt


def rules():
    return [*shfmt.rules()]
```

Now, when you run `./pants fmt ::` or `./pants lint ::`, your new formatter should run. 

5. Add tests (optional)
-----------------------

Refer to [Testing rules](doc:rules-api-testing).
