---
title: "helm_artifact"
slug: "reference-helm_artifact"
hidden: false
createdAt: "2022-06-02T21:10:30.082Z"
updatedAt: "2022-06-02T21:10:30.577Z"
---
A third party Helm artifact.

Backend: <span style="color: purple"><code>pants.backend.experimental.helm</code></span>

## <code>artifact</code>

<span style="color: purple">type: <code>str</code></span>
<span style="color: green">required</span>

Artifact name of the chart, without version number.

## <code>description</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A human-readable description of the target.

Use `./pants list --documented ::` to see all targets with descriptions.

## <code>registry</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

Either registry alias (prefixed by `@`) configured in `[helm.registries]` for the Helm artifact or the full OCI registry URL.

## <code>repository</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

Either a HTTP(S) URL to a classic repository, or a path inside an OCI registry (when `registry` is provided).

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.

## <code>version</code>

<span style="color: purple">type: <code>str</code></span>
<span style="color: green">required</span>

The `version` part of a third party Helm chart.