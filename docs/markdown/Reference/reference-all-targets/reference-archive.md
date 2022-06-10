---
title: "archive"
slug: "reference-archive"
hidden: false
createdAt: "2022-06-02T21:10:22.472Z"
updatedAt: "2022-06-02T21:10:22.839Z"
---
A ZIP or TAR file containing loose files and code packages.

Backend: <span style="color: purple"><code>pants.core</code></span>

## <code>description</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A human-readable description of the target.

Use `./pants list --documented ::` to see all targets with descriptions.

## <code>files</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Addresses to any `file`, `files`, or `relocated_files` targets to include in the archive, e.g. `["resources:logo"]`.

This is useful to include any loose files, like data files, image assets, or config files.

This will ignore any targets that are not `file`, `files`, or `relocated_files` targets.

If you instead want those files included in any packages specified in the `packages` field for this target, then use a `resource` or `resources` target and have the original package depend on the resources.

## <code>format</code>

<span style="color: purple">type: <code>'tar' | 'tar.bz2' | 'tar.gz' | 'tar.xz' | 'zip'</code></span>
<span style="color: green">required</span>

The type of archive file to be generated.

## <code>output_path</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

Where the built asset should be located.

If undefined, this will use the path to the BUILD file, followed by the target name. For example, `src/python/project:app` would be `src.python.project/app.ext`.

When running `./pants package`, this path will be prefixed by `--distdir` (e.g. `dist/`).

Warning: setting this value risks naming collisions with other package targets you may have.

## <code>packages</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Addresses to any targets that can be built with `./pants package`, e.g. `["project:app"]`.

Pants will build the assets as if you had run `./pants package`. It will include the results in your archive using the same name they would normally have, but without the `--distdir` prefix (e.g. `dist/`).

You can include anything that can be built by `./pants package`, e.g. a `pex_binary`, `python_awslambda`, or even another `archive`.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.