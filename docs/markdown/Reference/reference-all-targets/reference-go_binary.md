---
title: "go_binary"
slug: "reference-go_binary"
hidden: false
createdAt: "2022-06-02T21:10:27.193Z"
updatedAt: "2022-06-02T21:10:27.728Z"
---
A Go binary.

Backend: <span style="color: purple"><code>pants.backend.experimental.go</code></span>

## <code>description</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A human-readable description of the target.

Use `./pants list --documented ::` to see all targets with descriptions.

## <code>main</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

Address of the `go_package` with the `main` for this binary.

If not specified, will default to the `go_package` for the same directory as this target's BUILD file. You should usually rely on this default.

## <code>output_path</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

Where the built asset should be located.

If undefined, this will use the path to the BUILD file, followed by the target name. For example, `src/python/project:app` would be `src.python.project/app.ext`.

When running `./pants package`, this path will be prefixed by `--distdir` (e.g. `dist/`).

Warning: setting this value risks naming collisions with other package targets you may have.

## <code>restartable</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>

If true, runs of this target with the `run` goal may be interrupted and restarted when its input files change.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.