---
title: "go_mod"
slug: "reference-go_mod"
hidden: false
createdAt: "2022-06-02T21:10:27.953Z"
updatedAt: "2022-06-02T21:10:28.340Z"
---
A first-party Go module (corresponding to a `go.mod` file).

Generates `go_third_party_package` targets based on the `require` directives in your `go.mod`.

If you have third-party packages, make sure you have an up-to-date `go.sum`. Run `go mod tidy` directly to update your `go.mod` and `go.sum`.

Backend: <span style="color: purple"><code>pants.backend.experimental.go</code></span>

## <code>description</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A human-readable description of the target.

Use `./pants list --documented ::` to see all targets with descriptions.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.