---
title: "helm_chart"
slug: "reference-helm_chart"
hidden: false
createdAt: "2022-06-02T21:10:30.812Z"
updatedAt: "2022-06-02T21:10:31.475Z"
---
A Helm chart.

Backend: <span style="color: purple"><code>pants.backend.experimental.helm</code></span>

## <code>chart</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>&#x27;Chart.yaml&#x27;</code></span>

The chart definition file.

## <code>dependencies</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Addresses to other targets that this target depends on, e.g. ['helloworld/subdir:lib', 'helloworld/main.py:lib', '3rdparty:reqs#django'].

This augments any dependencies inferred by Pants, such as by analyzing your imports. Use `./pants dependencies` or `./pants peek` on this target to get the final result.

See [Targets and BUILD files](doc:targets)#target-addresses and [Targets and BUILD files](doc:targets)#target-generation for more about how addresses are formed, including for generated targets. You can also run `./pants list ::` to find all addresses in your project, or `./pants list dir:` to find all addresses defined in that directory.

If the target is in the same BUILD file, you can leave off the BUILD file path, e.g. `:tgt` instead of `helloworld/subdir:tgt`. For generated first-party addresses, use `./` for the file path, e.g. `./main.py:tgt`; for all other generated targets, use `:tgt#generated_name`.

You may exclude dependencies by prefixing with `!`, e.g. `['!helloworld/subdir:lib', '!./sibling.txt']`. Ignores are intended for false positives with dependency inference; otherwise, simply leave off the dependency from the BUILD file.

## <code>description</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

A human-readable description of the target.

Use `./pants list --documented ::` to see all targets with descriptions.

## <code>lint_strict</code>

<span style="color: purple">type: <code>bool | None</code></span>
<span style="color: green">default: <code>None</code></span>

If set to true, enables strict linting of this Helm chart.

## <code>output_path</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

Where the built directory tree should be located.

If undefined, this will use the path to the BUILD file, For example, `src/charts/mychart:tgt_name` would be `src.charts.mychart/tgt_name/`.

Regardless of whether you use the default or set this field, the path will end with Helms's file format of `<chart_name>-<chart_version>.tgz`, where `chart_name` and `chart_version` are the values extracted from the Chart.yaml file. So, using the default for this field, the target `src/charts/mychart:tgt_name` might have a final path like `src.charts.mychart/tgt_name/mychart-0.1.0.tgz`.

When running `./pants package`, this path will be prefixed by `--distdir` (e.g. `dist/`).

Warning: setting this value risks naming collisions with other package targets you may have.

## <code>registries</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>(&#x27;&lt;ALL DEFAULT HELM REGISTRIES&gt;&#x27;,)</code></span>

List of addresses or configured aliases to any OCI registries to use for the built chart.

The address is an `oci://` prefixed domain name with optional port for your registry, and any registry aliases are prefixed with `@` for addresses in the [helm].registries configuration section.

By default, all configured registries with `default = true` are used.

Example:

    # pants.toml
    [helm.registries.my-registry-alias]
    address = "oci://myregistrydomain:port"
    default = false # optional

    # example/BUILD
    helm_chart(
        registries = [
            "@my-registry-alias",
            "oci://myregistrydomain:port",
        ],
    )

The above example shows two valid `registry` options: using an alias to a configured registry and the address to a registry verbatim in the BUILD file.

## <code>repository</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

Repository to use in the Helm registry where this chart is going to be published.

If no value is given and `[helm].default-registry-repository` is undefined too, then the chart will be pushed to the root of the OCI registry.

## <code>skip_push</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>

If set to true, do not push this helm chart to registries when running `./pants publish`.

## <code>sources</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>(&#x27;values.yaml&#x27;, &#x27;templates/&ast;.yaml&#x27;, &#x27;templates/&ast;.tpl&#x27;)</code></span>

A list of files and globs that belong to this target.

Paths are relative to the BUILD file's directory. You can ignore files/globs by prefixing them with `!`.

Example: `sources=['example.ext', 'test_*.ext', '!test_ignore.ext']`.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.