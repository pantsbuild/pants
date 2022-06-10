---
title: "pyoxidizer_binary"
slug: "reference-pyoxidizer_binary"
hidden: false
createdAt: "2022-06-02T21:10:44.034Z"
updatedAt: "2022-06-02T21:10:44.452Z"
---
A single-file Python executable with a Python interpreter embedded, built via PyOxidizer.

To use this target, first create a `python_distribution` target with the code you want included in your binary, per [Building distributions](doc:python-distributions). Then add this `python_distribution` target to the `dependencies` field. See the `help` for `dependencies` for more information.

You may optionally want to set the `entry_point` field. For advanced use cases, you can use a custom PyOxidizer config file, rather than what Pants generates, by setting the `template` field. You may also want to set `[pyoxidizer].args` to a value like `['--release']`.

Backend: <span style="color: purple"><code>pants.backend.experimental.python.packaging.pyoxidizer</code></span>

## <code>dependencies</code>

<span style="color: purple">type: <code>Iterable[str]</code></span>
<span style="color: green">required</span>

The addresses of `python_distribution` target(s) to include in the binary, e.g. `['src/python/project:dist']`.

The distribution(s) must generate at least one wheel file. For example, if using `generate_setup=True`, then make sure `wheel=True`. See [Building distributions](doc:python-distributions).

Usually, you only need to specify a single `python_distribution`. However, if that distribution depends on another first-party distribution in your repository, you must specify that dependency too, otherwise PyOxidizer would try installing the distribution from PyPI. Note that a `python_distribution` target might depend on another `python_distribution` target even if it is not included in its own `dependencies` field, as explained at [Building distributions](doc:python-distributions); if code from one distribution imports code from another distribution, then there is a dependency and you must include both `python_distribution` targets in the `dependencies` field of this `pyoxidizer_binary` target.

Target types other than `python_distribution` will be ignored.

## <code>description</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A human-readable description of the target.

Use `./pants list --documented ::` to see all targets with descriptions.

## <code>entry_point</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

Set the entry point, i.e. what gets run when executing `./my_app`, to a module. This represents the content of PyOxidizer's `python_config.run_module` and leaving this field empty will create a REPL binary.

It is specified with the full module declared: 'path.to.module'.

This field is passed into the PyOxidizer config as-is, and does not undergo validation checking.

## <code>filesystem_resources</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Adds support for listing dependencies that MUST be installed to the filesystem (e.g. Numpy). See https://pyoxidizer.readthedocs.io/en/stable/pyoxidizer_packaging_additional_files.html#installing-unclassified-files-on-the-filesystem

## <code>output_path</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

Where the built directory tree should be located.

If undefined, this will use the path to the BUILD file, followed by the target name. For example, `src/python/project:bin` would be `src.python.project/bin/`.

Regardless of whether you use the default or set this field, the path will end with PyOxidizer's file format of `<platform>/{debug,release}/install/<binary_name>`, where `platform` is a Rust platform triplet like `aarch-64-apple-darwin` and `binary_name` is the `name` of the `pyoxidizer_target`. So, using the default for this field, the target `src/python/project:bin` might have a final path like `src.python.project/bin/aarch-64-apple-darwin/release/bin`.

When running `./pants package`, this path will be prefixed by `--distdir` (e.g. `dist/`).

Warning: setting this value risks naming collisions with other package targets you may have.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.

## <code>template</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

If set, will use your custom configuration rather than using Pants's default template.

The path is relative to the BUILD file's directory, and it must end in `.blzt`.

All parameters must be prefixed by $ or surrounded with ${ }.

Available template parameters:

  * RUN_MODULE - The re-formatted entry_point passed to this target (or None).
  * NAME - This target's name.
  * WHEELS - All python distributions passed to this target (or []).
  * UNCLASSIFIED_RESOURCE_INSTALLATION - This will populate a snippet of code to correctly inject the targets filesystem_resources.