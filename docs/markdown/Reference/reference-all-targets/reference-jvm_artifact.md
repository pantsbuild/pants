---
title: "jvm_artifact"
slug: "reference-jvm_artifact"
hidden: false
createdAt: "2022-06-02T21:10:35.732Z"
updatedAt: "2022-06-02T21:10:36.174Z"
---
A third-party JVM artifact, as identified by its Maven-compatible coordinate.

That is, an artifact identified by its `group`, `artifact`, and `version` components.

Each artifact is associated with one or more resolves (a logical name you give to a lockfile). For this artifact to be used by your first-party code, it must be associated with the resolve(s) used by that code. See the `resolve` field.

Backend: <span style="color: purple"><code>pants.backend.experimental.java</code></span>

## <code>artifact</code>

<span style="color: purple">type: <code>str</code></span>
<span style="color: green">required</span>

The 'artifact' part of a Maven-compatible coordinate to a third-party JAR artifact.

For the JAR coordinate `com.google.guava:guava:30.1.1-jre`, the artifact is `guava`.

## <code>description</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A human-readable description of the target.

Use `./pants list --documented ::` to see all targets with descriptions.

## <code>excludes</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

A list of unversioned coordinates (i.e. `group:artifact`) that should be excluded as dependencies when this artifact is resolved.

This does not prevent this artifact from being included in the resolve as a dependency of other artifacts that depend on it, and is currently intended as a way to resolve version conflicts in complex resolves.

These values are passed directly to Coursier, and if specified incorrectly will show a parse error from Coursier.

## <code>group</code>

<span style="color: purple">type: <code>str</code></span>
<span style="color: green">required</span>

The 'group' part of a Maven-compatible coordinate to a third-party JAR artifact.

For the JAR coordinate `com.google.guava:guava:30.1.1-jre`, the group is `com.google.guava`.

## <code>jar</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A local JAR file that provides this artifact to the lockfile resolver, instead of a Maven repository.

Path is relative to the BUILD file.

Use the `url` field for remote artifacts.

## <code>packages</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

The JVM packages this artifact provides for the purposes of dependency inference.

For example, the JVM artifact `junit:junit` might provide `["org.junit.**"]`.

Usually you can leave this field off. If unspecified, Pants will fall back to the `[java-infer].third_party_import_mapping`, then to a built in mapping (https://github.com/pantsbuild/pants/blob/release_2.12.0rc2/src/python/pants/jvm/dependency_inference/jvm_artifact_mappings.py), and then finally it will default to the normalized `group` of the artifact. For example, in the absence of any other mapping the artifact `io.confluent:common-config` would default to providing `["io.confluent.**"]`.

The package path may be made recursive to match symbols in subpackages by adding `.**` to the end of the package path. For example, specify `["org.junit.**"]` to infer a dependency on the artifact for any file importing a symbol from `org.junit` or its subpackages.

## <code>resolve</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

The resolve from `[jvm].resolves` that this artifact should be included in.

If not defined, will default to `[jvm].default_resolve`.

When generating a lockfile for a particular resolve via the `coursier-resolve` goal, it will include all artifacts that are declared compatible with that resolve. First-party targets like `java_source` and `scala_source` also declare which resolve they use via the `resolve` field; so, for your first-party code to use a particular `jvm_artifact` target, that artifact must be included in the resolve used by that code.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.

## <code>url</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A URL that points to the location of this artifact.

If specified, Pants will not fetch this artifact from default Maven repositories, and will instead fetch the artifact from this URL. To use default maven repositories, do not set this value.

Note that `file:` URLs are not supported. Instead, use the `jar` field for local artifacts.

## <code>version</code>

<span style="color: purple">type: <code>str</code></span>
<span style="color: green">required</span>

The 'version' part of a Maven-compatible coordinate to a third-party JAR artifact.

For the JAR coordinate `com.google.guava:guava:30.1.1-jre`, the version is `30.1.1-jre`.