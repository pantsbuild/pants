---
title: "relocated_files"
slug: "reference-relocated_files"
hidden: false
createdAt: "2022-06-02T21:10:51.629Z"
updatedAt: "2022-06-02T21:10:52.043Z"
---
Loose files with path manipulation applied.

Allows you to relocate the files at runtime to something more convenient than their actual paths in your project.

For example, you can relocate `src/resources/project1/data.json` to instead be `resources/data.json`. Your other target types can then add this target to their `dependencies` field, rather than using the original `files` target.

To remove a prefix:

    # Results in `data.json`.
    relocated_files(
        files_targets=["src/resources/project1:target"],
        src="src/resources/project1",
        dest="",
    )

To add a prefix:

    # Results in `images/logo.svg`.
    relocated_files(
        files_targets=["//:logo"],
        src="",
        dest="images",
    )

To replace a prefix:

    # Results in `new_prefix/project1/data.json`.
    relocated_files(
        files_targets=["src/resources/project1:target"],
        src="src/resources",
        dest="new_prefix",
    )

Backend: <span style="color: purple"><code>pants.core</code></span>

## <code>description</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A human-readable description of the target.

Use `./pants list --documented ::` to see all targets with descriptions.

## <code>dest</code>

<span style="color: purple">type: <code>str</code></span>
<span style="color: green">required</span>

The new prefix that you want to add to the beginning of the path, such as `data`.

You can set this field to the empty string to avoid adding any new values to the path; the value in the `src` field will then be stripped, rather than replaced.

## <code>files_targets</code>

<span style="color: purple">type: <code>Iterable[str]</code></span>
<span style="color: green">required</span>

Addresses to the original `file` and `files` targets that you want to relocate, such as `['//:json_files']`.

Every target will be relocated using the same mapping. This means that every target must include the value from the `src` field in their original path.

## <code>src</code>

<span style="color: purple">type: <code>str</code></span>
<span style="color: green">required</span>

The original prefix that you want to replace, such as `src/resources`.

You can set this field to the empty string to preserve the original path; the value in the `dest` field will then be added to the beginning of this original path.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.