---
title: "Integrating new tools without plugins"
slug: "adhoc-tool"
hidden: false
createdAt: "2023-03-20T00:00:00.000Z"
---

# Integrating new tools without plugins

The `adhoc_tool` target allows you to execute "runnable" targets inside the Pants sandbox. Runnable targets include first-party sources that can be run with `pants run`, 3rd-party dependencies like `python_requirement` or `jvm_artifact`, or even executables that exist on your system and managed externally to Pants.

`adhoc_tool` provides you with the building blocks needed to put together a custom build process without needing to develop and maintain a plugin. The level of initial effort involved in using `adhoc_tool` is significantly lower than that of [writing a plugin](doc:plugins-overview), so it's well-suited to consuming one-off scripts, or for rapidly prototyping a process before actually writing a plugin. The tradeoff is that there is more manual work involved in defining build processes that reflect your codebase's structure, and that the targets that define the tools you consume are less easy to reuse.

The `antlr` demo in the [`example-adhoc` respository](https://github.com/pantsbuild/example-adhoc) shows an example of running a JVM-based tool to transparently generate Python code that can be used in another language:

```
adhoc_tool(
    name="run_antlr",
    runnable=":antlr4",
    args=["Expr.g4", "-Dlanguage=Python3", "-o", "expr_parser", "-package", "expr_parser",],
    output_directories=["expr_parser",],
    # These are consumed by `antlr`, but are not relevant to this target's dependents.
    execution_dependencies=[":grammars"],
    # These are needed by the code that is output by this target
    output_dependencies=[":antlr4-python3-runtime",],
    root_output_directory=".",
    log_output=True,
)
```

## `runnable` targets

"Runnable" targets are targets that Pants knows how to execute within its sandbox. Generally, these correspond to targets that can be executed with the `pants run` goal, and include first-party source files, as well as third-party dependencies.

The tool will be run with values from `args` specified as arguments. By default, the process' working directory will be the directory where the `BUILD` file is defined. This can be adjusted using the `workdir` field.

> 🚧 `runnable` targets must be pure functions
> 
> When run by `adhoc_tool`, Pants assumes that the inputs provided to the process -- that is, the values of the `adhoc_tool`'s fields, and the contents of the runnable and execution dependencies -- fully describe the output. Output values will be [cached](doc:how-does-pants-work#caching) by Pants, and future invocations with identical inputs will be retrieved from the cache instead of being re-executed. If your process has behavior that is not fully defined by its inputs, Pants' behavior may be unexpected or inconsistent.

> 🚧 `runnable` targets must be idempotent
> 
> `adhoc_tool` processes may be cancelled or retried any number of times, so it is important that any side effects are idempotent. That is, it should not matter if it is run several times, or only partially.


## Specifying dependencies

`adhoc_tool` has more complexity surrounding dependencies compared with Pants' first-class targets. This is because you need to do manual work to set up the execution environment, which is usually taken care of by plugin code.

`adhoc_tool` has three dependencies fields:

* `output_dependencies`, which defines dependencies that are required to effectively consume the output of the tool, _e.g._ runtime libraries for generated code bindings. Any targets that (transitively) depend on the `adhoc_tool` target will also transitively depend on these dependencies.
* `execution_dependencies`, which define data dependencies required for the tool to produce its output. These are not considered when resolving transitive dependencies that include this `adhoc_tool` target.
* `runnable_dependencies`, which define runnables that the `adhoc_tool` needs on its `PATH` to execute as a subprocess. These are also not considered when resolving transitive dependencies. The discussion of `system_binary` later in this page shows one key use of `runnable_dependencies`.

In the `antlr` example, `output_dependencies` is used because the tool produces Python-based bindings that depend on a runtime library. `execution_dependencies` specifies the sources that are consumed by the tool, but do not need to be consumed by subsequent build steps.


## Specifying outputs

Generally, `adhoc_tool` targets are run to produce outputs that can be supplied to other targets. These can be in the form of files or directories that are output directly by the tools: use the `output_files` field to capture individual files, or `output_directories` to capture entire directories as output. 

Files are captured relative to the build root by default: this is useful when passing results to further `adhoc_tool` targets defined in the same `BUILD` file. If this behavior is not right for you, for example, if you are producing an artifact for packaging, you can change the root of the outputs using the `root_output_directory` field.

Finally, if you want to capture `stdout` or `stderr` from your tool, you can use the `stdout` or `stderr` fields. These specify filenames where those streams will be dumped once the process completes. Note that these files are specified in addition to those from the `output_files` field, and an error will occur if the filename occurs in the outputs arising from `output_files` or `output_directories` and the contents of that file are different.


## Chaining processes together

_Our [JavaScript demo](https://github.com/pantsbuild/example-adhoc/tree/main/javascript) demonstrates a string of `adhoc_tool` targets that's used to produce a resource file._

To get the best cache efficiency, it can make sense to break your `adhoc_tool` into smaller incremental steps. For example, if your process needs to fetch dependencies and then build a library based on those dependencies and some first-party source files, having one `adhoc_tool` for each of those steps means that the dependency-fetching stage will only be re-run when your requirements change, and not when the first-party source files change.

Generally, if you are chaining `adhoc_tool` targets together , it will be easier to use the default `workdir` and `root_output_directory` fields for each step that will be consumed by an `adhoc_tool` in the same `BUILD` file. Change the `root_output_directory` only for targets that are intended to be used in other places or ways.


## Wrapping generated sources for use by other targets

_Our [Antlr demo](https://github.com/pantsbuild/example-adhoc/tree/main/antlr) demonstrates wrapping the outputs of `adhoc_tool` targets for use as Python sources._

`adhoc_tool` generates `file` sources by default. This can be acceptable if generating assets that do not need to be consumed as source files for another Pants backend. Other Pants backends need generated sources to be marked as actual source files.

There are several targets included in Pants with the prefix `experimental_wrap_as_`. These act as a source target that can be used as a dependency in a given language backend, with the caveat that dependency inference is not available.


## Using externally-managed tools

_Our [JavaScript demo](https://github.com/pantsbuild/example-adhoc/tree/main/javascript) demonstrates the use of externally-managed binaries._

Some build processes need to make use of tools that can't be modeled within a Pants codebase. The `system_binary` target lets you make use of a binary that is installed on the system. `system_binary` targets may be specified as `runnable` or `runnable_dependency` values for `adhoc_tool`.

`system_binary` will search for a binary in pre-defined or user-supplied search paths with a given `binary_name`. To improve reproducibility, it's possible to test matching binaries with sample arguments, to see if its output matches a given regular expression. This can be used to match against version strings. If a such a binary does not exist on the system where Pants is being run, any build involving this `system_binary` target will fail.

When specified as a `runnable_dependency`, the binary will be available on the `PATH` with the target name of the dependency. This can be important if the `runnable` field invokes a subprocess (for example, `yarn` tries to invoke a binary called `node` as its interpreter).


## Running shell scripts

Currently, `shell_source` targets are not runnable. In the meantime, it is possible to run a shell script as an `adhoc_tool` through the following approach:

* Declare a `system_binary` target referring to your preferred shell (e.g. `bash`, `zsh`, `fish`)
* Declare an `adhoc_tool`, with the `runnable` field pointing at your `system_binary` target, add your `shell_source` as an `execution_dependency`, and provide your script's path relative to the buildroot as the first value in `args`

This is clearly not as convenient as directly running a `shell_source` target, and we anticipate adding support in a future version of Pants.
