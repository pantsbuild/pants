---
title: "docker_image"
slug: "reference-docker_image"
hidden: false
createdAt: "2022-06-02T21:10:23.768Z"
updatedAt: "2022-06-02T21:10:24.213Z"
---
The `docker_image` target describes how to build and tag a Docker image.

Any dependencies, as inferred or explicitly specified, will be included in the Docker build context, after being packaged if applicable.

By default, will use a Dockerfile from the same directory as the BUILD file this target is defined in. Point at another file with the `source` field, or use the `instructions` field to have the Dockerfile contents verbatim directly in the BUILD file.

Dependencies on upstream/base images defined by another `docker_image` are inferred if referenced by a build argument with a default value of the target address.

Example:

    # src/docker/downstream/Dockerfile
    ARG BASE=src/docker/upstream:image
    FROM $BASE
    ...

Backend: <span style="color: purple"><code>pants.backend.docker</code></span>

## <code>context_root</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

Specify which directory to use as the Docker build context root. This affects the file paths to use for the `COPY` and `ADD` instructions. For example, whether `COPY files/f.txt` should look for the file relative to the build root: `<build root>/files/f.txt` vs relative to the BUILD file: `<build root>/path_to_build_file/files/f.txt`.

Specify the `context_root` path as `files` for relative to build root, or as `./files` for relative to the BUILD file.

If `context_root` is not specified, it defaults to `[docker].default_context_root`.

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

## <code>extra_build_args</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>()</code></span>

Build arguments (`--build-arg`) to use when building this image. Entries are either strings in the form `ARG_NAME=value` to set an explicit value; or just `ARG_NAME` to copy the value from Pants's own environment.

Use `[docker].build_args` to set default build args for all images.

## <code>image_labels</code>

<span style="color: purple">type: <code>Dict[str, str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Provide image metadata.

label value may use placeholders in curly braces to be interpolated. The placeholders are derived from various sources, such as the Dockerfile instructions and build args.

See [Docker labels](https://docs.docker.com/config/labels-custom-metadata/#manage-labels-on-objects) for more information.

## <code>image_tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>(&#x27;latest&#x27;,)</code></span>


Any tags to apply to the Docker image name (the version is usually applied as a tag).

tag may use placeholders in curly braces to be interpolated. The placeholders are derived from various sources, such as the Dockerfile instructions and build args.

See [Tagging Docker images](doc:tagging-docker-images).

## <code>instructions</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

The `Dockerfile` content, typically one instruction per list item.

Use the `source` field instead if you prefer having the Dockerfile in your source tree.

Example:

    # example/BUILD
    docker_image(
      instructions=[
        "FROM base/image:1.0",
        "RUN echo example",
      ],
    )

## <code>registries</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>(&#x27;&lt;all default registries&gt;&#x27;,)</code></span>

List of addresses or configured aliases to any Docker registries to use for the built image.

The address is a domain name with optional port for your registry, and any registry aliases are prefixed with `@` for addresses in the [docker].registries configuration section.

By default, all configured registries with `default = true` are used.

Example:

    # pants.toml
    [docker.registries.my-registry-alias]
    address = "myregistrydomain:port"
    default = false # optional

    # example/BUILD
    docker_image(
        registries = [
            "@my-registry-alias",
            "myregistrydomain:port",
        ],
    )

The above example shows two valid `registry` options: using an alias to a configured registry and the address to a registry verbatim in the BUILD file.

## <code>repository</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

The repository name for the Docker image. e.g. "<repository>/<name>".

It uses the `[docker].default_repository` by default.

repository may use placeholders in curly braces to be interpolated. The placeholders are derived from various sources, such as the Dockerfile instructions and build args.

Additional placeholders for the repository field are: `name`, `directory` and `parent_directory`.

See the documentation for `[docker].default_repository` for more information.

## <code>restartable</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>

If true, runs of this target with the `run` goal may be interrupted and restarted when its input files change.

## <code>secrets</code>

<span style="color: purple">type: <code>Dict[str, str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Secret files to expose to the build (only if BuildKit enabled).

Secrets may use absolute paths, or paths relative to your build root, or the BUILD file if prefixed with `./`. The id should be valid as used by the Docker build `--secret` option. See [Docker secrets](https://docs.docker.com/engine/swarm/secrets/) for more information.

Example:

    docker_image(
        secrets={
            "mysecret": "/var/secrets/some-secret",
            "repo-secret": "src/proj/secrets/some-secret",
            "target-secret": "./secrets/some-secret",
        }
    )

## <code>skip_hadolint</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>
backend: <span style="color: green"><code>pants.backend.docker.lint.hadolint</code></span>

If true, don't run hadolint on this target's Dockerfile.

## <code>skip_push</code>

<span style="color: purple">type: <code>bool</code></span>
<span style="color: green">default: <code>False</code></span>

If set to true, do not push this image to registries when running `./pants publish`.

## <code>source</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>&#x27;Dockerfile&#x27;</code></span>

The Dockerfile to use when building the Docker image.

Use the `instructions` field instead if you prefer not having the Dockerfile in your source tree.

## <code>ssh</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>()</code></span>

SSH agent socket or keys to expose to the build (only if BuildKit enabled) (format: default|<id>[=<socket>|<key>[,<key>]])

The exposed agent and/or keys can then be used in your `Dockerfile` by mounting them in your `RUN` instructions:

    RUN --mount=type=ssh ...

See [Docker documentation](https://docs.docker.com/develop/develop-images/build_enhancements/#using-ssh-to-access-private-data-in-builds) for more information.

## <code>tags</code>

<span style="color: purple">type: <code>Iterable[str] | None</code></span>
<span style="color: green">default: <code>None</code></span>

Arbitrary strings to describe a target.

For example, you may tag some test targets with 'integration_test' so that you could run `./pants --tag='integration_test' test ::` to only run on targets with that tag.

## <code>target_stage</code>

<span style="color: purple">type: <code>str | None</code></span>
<span style="color: green">default: <code>None</code></span>

Specify target build stage, rather than building the entire `Dockerfile`.

When using multi-stage build, you may name your stages, and can target them when building to only selectively build a certain stage. See also the `--docker-build-target-stage` option.

Read more about [multi-stage Docker builds](https://docs.docker.com/develop/develop-images/multistage-build/#stop-at-a-specific-build-stage)