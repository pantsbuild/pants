---
title: "Add a linter"
slug: "plugins-lint-goal"
excerpt: "How to add a new linter to the `lint` goal."
hidden: false
createdAt: "2020-07-01T04:51:55.583Z"
updatedAt: "2022-04-07T14:48:36.791Z"
---
This guide assumes that you are running a linter that already exists outside of Pants as a stand-alone binary, such as running Shellcheck, Pylint, Checkstyle, or ESLint. 

If you are instead writing your own linting logic inline, you can skip Step 1. In Step 3, you will not need to use `Process`. You may find Pants's [`regex-lint` implementation](https://github.com/pantsbuild/pants/blob/main/src/python/pants/backend/project_info/regex_lint.py) helpful for how to integrate custom linting logic into Pants.

1. Install your linter
----------------------

There are several ways for Pants to install your linter. See [Installing tools](doc:rules-api-installing-tools). This example will use `ExternalTool` because there is already a pre-compiled binary for Shellcheck.

You will also likely want to register some options, like `--config`, `--skip`, and `--args`. Options are registered through a [`Subsystem`](doc:rules-api-subsystems). If you are using `ExternalTool`, this is already a subclass of `Subsystem`. Otherwise, create a subclass of `Subsystem`. Then, set the class property `options_scope` to the name of the tool, e.g. `"shellcheck"` or `"eslint"`. Finally, add options from `pants.option.option_types`.

```python
from pants.core.util_rules.external_tool import ExternalTool
from pants.engine.platform import Platform
from pants.option.option_types import ArgsListOption, SkipOption


class Shellcheck(ExternalTool):
    """A linter for shell scripts."""

    options_scope = "shellcheck"
    default_version = "v0.8.0"
    default_known_versions = [
        "v0.8.0|macos_arm64 |e065d4afb2620cc8c1d420a9b3e6243c84ff1a693c1ff0e38f279c8f31e86634|4049756",
        "v0.8.0|macos_x86_64|e065d4afb2620cc8c1d420a9b3e6243c84ff1a693c1ff0e38f279c8f31e86634|4049756",
        "v0.8.0|linux_arm64 |9f47bbff5624babfa712eb9d64ece14c6c46327122d0c54983f627ae3a30a4ac|2996468",
        "v0.8.0|linux_x86_64|ab6ee1b178f014d1b86d1e24da20d1139656c8b0ed34d2867fbb834dad02bf0a|1403852",
    ]

    skip = SkipOption("lint")
    args = ArgsListOption(example="-e SC20529")

    def generate_url(self, plat: Platform) -> str:
        plat_str = {
            "macos_arm64": "darwin.x86_64",
            "macos_x86_64": "darwin.x86_64",
            "linux_arm64": "linux.aarch64",
            "linux_x86_64": "linux.x86_64",
        }[plat.value]
        return (
            f"https://github.com/koalaman/shellcheck/releases/download/{self.version}/"
            f"shellcheck-{self.version}.{plat_str}.tar.xz"
        )

    def generate_exe(self, _: Platform) -> str:
        return f"./shellcheck-{self.version}/shellcheck"

```

Lastly, register your Subsystem with the engine:

```python
from pants.engine.rules import collect_rules

...

def rules():
    return collect_rules()
```

2. Set up a `FieldSet` and `LintRequest`
----------------------------------------

As described in [Rules and the Target API](doc:rules-api-and-target-api), a `FieldSet` is a way to tell Pants which `Field`s you care about targets having for your plugin to work.

Usually, you should add a subclass of the `Sources` field to the class property `required_fields`, such as `BashSources` or `PythonSources`. This means that your linter will run on any target with that sources field or a subclass of it.

Create a new dataclass that subclasses `FieldSet`:

```python
from dataclasses import dataclass

from pants.engine.target import Dependencies, FieldSet

...

@dataclass(frozen=True)
class ShellcheckFieldSet(FieldSet):
    required_fields = (BashSources,)

    sources: BashSources
    dependencies: Dependencies
```

Then, hook this up to a new subclass of `LintTargetsRequest`:

```python
from pants.core.goals.lint import LintTargetsRequest

...

class ShellcheckRequest(LintTargetsRequest):
    field_set_type = ShellcheckFieldSet
    name = "shellcheck"
```

Finally, register your new `LintTargetsRequest ` with a [`UnionRule`](doc:rules-api-unions) so that Pants knows your linter exists:

```python
from pants.engine.unions import UnionRule

...

def rules():
    return [
      	*collect_rules(),
        UnionRule(LintTargetsRequest, ShellcheckRequest),
    ]
```

3. Create a rule for your linter logic
--------------------------------------

Your rule should take as a parameter the `LintRequest` from step 2 and the `Subsystem` (or `ExternalTool`) from step 1. It should return `LintResults`:

```python
from pants.engine.rules import rule
from pants.core.goals.lint import LintTargetsRequest, LintResult, LintResults

...

@rule
async def run_shellcheck(
    request: ShellcheckRequest, shellcheck: Shellcheck
) -> LintResults:
    return LintResults(linter_name=request.name)
```

The `LintTargetsRequest ` has a property called `.field_sets`, which stores a collection of the `FieldSet`s defined in step 2. Each `FieldSet` corresponds to a single target. Pants will have already validated that there is at least one valid `FieldSet`, so you can expect `LintRequest.field_sets` to have 1-n `FieldSet` instances. 

The rule should return `LintResults`, which is a collection of multiple `LintResult` objects. Normally, you will only have one single `LintResult`. Sometimes, however, you may want to group your targets in a certain way and return a `LintResult` for each group, such as grouping Python targets by their interpreter compatibility.

If you have a `--skip` option, you should check if it was used at the beginning of your rule and, if so, to early return an empty `LintResults()`.

If you used `ExternalTool` in step 1, you will use `Get(DownloadedExternalTool, ExternalToolRequest)` to install the tool.

Typically, you will use `Get(SourceFiles, SourceFilesRequest)` to get all the sources you want to run your linter on.

If you have a `--config` option, you should use `Get(Digest, PathGlobs)` to find the config file and include it in the `input_digest`.

Use `Get(Digest, MergeDigests)` to combine the different inputs together, such as merging the source files, config file, and downloaded tool.

Usually, you will use `Get(FallibleProcessResult, Process)` to run a subprocess (see [Processes](doc:rules-api-process)). We use `Fallible` because Pants should not throw an exception if the linter returns a non-zero exit code. Then, you can use `LintResult.from_fallible_process_result()` to convert this into a `LintResult`.

```python
from pants.core.goals.lint import LintTargetsRequest, LintResult, LintResults
from pants.core.util_rules.source_files import (
    SourceFilesRequest,
    SourceFiles,
)
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalTool,
    ExternalToolRequest,
)
from pants.engine.fs import (
    Digest,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
)
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

...

@rule
async def run_shellcheck(
    request: ShellcheckRequest, shellcheck: Shellcheck
) -> LintResults:
    if shellcheck.skip:
        return LintResults([], linter_name=request.name)

    download_shellcheck_request = Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        shellcheck.get_request(Platform.current),
    )

    sources_request = Get(
        SourceFiles,
        SourceFilesRequest(field_set.sources for field_set in request.field_sets),
    )

    # If the user specified `--shellcheck-config`, we must search for the file they specified with
    # `PathGlobs` to include it in the `input_digest`. We error if the file cannot be found.
    config_digest_request = Get(
        Digest,
        PathGlobs(
            globs=[shellcheck.config] if shellcheck.config else [],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `[shellcheck].config`",
        ),
    )

    downloaded_shellcheck, sources, config_digest = await MultiGet(
        download_shellcheck_request, sources_request, config_digest_request
    )

    # The Process needs one single `Digest`, so we merge everything together.
    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                downloaded_shellcheck.digest,
                sources.snapshot.digest,
                config_digest,
            )
        ),
    )

    process_result = await Get(
        FallibleProcessResult,
        Process(
            argv=[
                downloaded_shellcheck.exe,
                *shellcheck.args,
                *sources.snapshot.files,
            ],
            input_digest=input_digest,
            description=f"Run Shellcheck on {pluralize(len(request.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    result = LintResult.from_fallible_process_result(process_result)
    return LintResults([result], linter_name=request.name)

```

Finally, update your plugin's `register.py` to activate this file's rules.

```python pants-plugins/bash/register.py
from bash import shellcheck


def rules():
    return [*shellcheck.rules()]
```

Now, when you run `./pants lint ::`, your new linter should run.

4. Add tests (optional)
-----------------------

Refer to [Testing rules](doc:rules-api-testing).
