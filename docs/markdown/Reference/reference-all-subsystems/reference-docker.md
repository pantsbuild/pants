---
title: "docker"
slug: "reference-docker"
hidden: false
createdAt: "2022-06-02T21:09:40.277Z"
updatedAt: "2022-06-02T21:09:40.693Z"
---
Options for interacting with Docker.

Backend: <span style="color: purple"><code>pants.backend.docker</code></span>
Config section: <span style="color: purple"><code>[docker]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>registries</code></h3>
  <code>--docker-registries=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_DOCKER_REGISTRIES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>{}</code></span>

<br>

Configure Docker registries. The schema for a registry entry is as follows:

    {
        "registry-alias": {
            "address": "registry-domain:port",
            "default": bool,
            "extra_image_tags": [],
            "skip_push": bool,
        },
        ...
    }

If no registries are provided in a `docker_image` target, then all default addresses will be used, if any.

The `docker_image.registries` may be provided with a list of registry addresses and registry aliases prefixed with `@` to be used instead of the defaults.

A configured registry is marked as default either by setting `default = true` or with an alias of `"default"`.

A `docker_image` may be pushed to a subset of registries using the per registry `skip_push` option rather then the all or nothing toggle of the field option `skip_push` on the `docker_image` target.

Any image tags that should only be added for specific registries may be provided as the `extra_image_tags` option. The tags may use value formatting the same as for the `image_tags` field of the `docker_image` target.
</div>
<br>

<div style="color: purple">
  <h3><code>default_repository</code></h3>
  <code>--docker-default-repository=&lt;str&gt;</code><br>
  <code>PANTS_DOCKER_DEFAULT_REPOSITORY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>{name}</code></span>

<br>

Configure the default repository name used in the Docker image tag.

The value is formatted and may reference these variables (in addition to the normal placeheolders derived from the Dockerfile and build args etc):

  * name
  * directory
  * parent_directory

Example: `--default-repository="{directory}/{name}"`.

The `name` variable is the `docker_image`'s target name, `directory` and `parent_directory` are the name of the directory in which the BUILD file is for the target, and its parent directory respectively.

Use the `repository` field to set this value directly on a `docker_image` target.

Any registries or tags are added to the image name as required, and should not be part of the repository name.
</div>
<br>

<div style="color: purple">
  <h3><code>default_context_root</code></h3>
  <code>--docker-default-context-root=&lt;workspace_path&gt;</code><br>
  <code>PANTS_DOCKER_DEFAULT_CONTEXT_ROOT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code></code></span>

<br>

Provide a default Docker build context root path for `docker_image` targets that does not specify their own `context_root` field.

The context root is relative to the build root by default, but may be prefixed with `./` to be relative to the directory of the BUILD file of the `docker_image`.

Examples:

    --default-context-root=src/docker
    --default-context-root=./relative_to_the_build_file
</div>
<br>

<div style="color: purple">
  <h3><code>build_args</code></h3>
  <code>--docker-build-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;</code><br>
  <code>PANTS_DOCKER_BUILD_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Global build arguments (for Docker `--build-arg` options) to use for all `docker build` invocations.

Entries are either strings in the form `ARG_NAME=value` to set an explicit value; or just `ARG_NAME` to copy the value from Pants's own environment.

Example:

    [docker]
    build_args = ["VAR1=value", "VAR2"]

Use the `extra_build_args` field on a `docker_image` target for additional image specific build arguments.
</div>
<br>

<div style="color: purple">
  <h3><code>build_target_stage</code></h3>
  <code>--docker-build-target-stage=&lt;str&gt;</code><br>
  <code>PANTS_DOCKER_BUILD_TARGET_STAGE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Global default value for `target_stage` on `docker_image` targets, overriding the field value on the targets, if there is a matching stage in the `Dockerfile`.

This is useful to provide from the command line, to specify the target stage to build for at execution time.
</div>
<br>

<div style="color: purple">
  <h3><code>build_verbose</code></h3>
  <code>--[no-]docker-build-verbose</code><br>
  <code>PANTS_DOCKER_BUILD_VERBOSE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Whether to log the Docker output to the console. If false, only the image ID is logged.
</div>
<br>

<div style="color: purple">
  <h3><code>run_args</code></h3>
  <code>--docker-run-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;</code><br>
  <code>PANTS_DOCKER_RUN_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Additional arguments to use for `docker run` invocations.

Example:

    $ ./pants run --docker-run-args="-p 127.0.0.1:80:8080/tcp --name demo" src/example:image -- [image entrypoint args]

To provide the top-level options to the `docker` client, use `[docker].env_vars` to configure the [Environment variables](https://docs.docker.com/engine/reference/commandline/cli/#environment-variables) as appropriate.

The arguments for the image entrypoint may be passed on the command line after a double dash (`--`), or using the `--run-args` option.

Defaults to `--interactive --tty` when stdout is connected to a terminal.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>env_vars</code></h3>
  <code>--docker-env-vars=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;</code><br>
  <code>PANTS_DOCKER_ENV_VARS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Environment variables to set for `docker` invocations.

Entries are either strings in the form `ENV_VAR=value` to set an explicit value; or just `ENV_VAR` to copy the value from Pants's own environment.
</div>
<br>

<div style="color: purple">
  <h3><code>executable_search_paths</code></h3>
  <code>--docker-executable-search-paths=&quot;[&lt;binary-paths&gt;, &lt;binary-paths&gt;, ...]&quot;</code><br>
  <code>PANTS_DOCKER_EXECUTABLE_SEARCH_PATHS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "&lt;PATH&gt;"
]</pre></span>

<br>

The PATH value that will be used to find the Docker client and any tools required.

The special string `"<PATH>"` will expand to the contents of the PATH env var.
</div>
<br>

<div style="color: purple">
  <h3><code>tools</code></h3>
  <code>--docker-tools=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_DOCKER_TOOLS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

List any additional executable tools required for Docker to work. The paths to these tools will be included in the PATH used in the execution sandbox, so that they may be used by the Docker client.
</div>
<br>


## Deprecated options

None