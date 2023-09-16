---
title: "Docker overview"
slug: "docker"
excerpt: "How to build Docker images containing artifacts built by Pants"
hidden: false
createdAt: "2021-09-03T15:28:55.877Z"
---
Docker images typically bundle build artifacts, such as PEX files, wheels, loose files, and so on, with other runtime requirements, such as a Python interpreter.

Pants [makes it easy to embed the artifacts Pants builds into your Docker images](https://blog.pantsbuild.org/pants-pex-and-docker/), for easy deployment.

Enabling the Docker backend
---------------------------

To use Pants's Docker support you must enable the appropriate backend:

```toml pants.toml
backend_packages = [
  ...
  "pants.backend.docker",
  ...
]
```

Adding `docker_image` targets
-----------------------------

A Docker image is built from a recipe specified by a [Dockerfile](https://docs.docker.com/engine/reference/builder/). When you build Docker images with Pants, instead of running `docker build` on the Dockerfile directly, you let Pants do that for you.

Pants uses [`docker_image`](doc:reference-docker_image) [targets](doc:targets) to indicate which Dockerfiles you want Pants to know about, and to add any necessary metadata. 

You can generate initial BUILD files for your Docker images, using [tailor](doc:initial-configuration#5-generate-build-files):

```
❯ pants tailor ::
Created src/docker/app1/BUILD:
  - Add docker_image target docker
Created src/docker/app2/BUILD:
  - Add docker_image target docker
```

Or you can add them manually, such as:

```python src/docker/app1/BUILD
docker_image(name="docker")
```

Alternatively you may provide the Docker build instructions inline in your BUILD file as [`instructions`](doc:reference-docker_image#codeinstructionscode) on your `docker_image` if you don't want to create a `Dockerfile`.

```python src/docker/app1/BUILD
docker_image(
  name="docker",
  instructions=[
    "FROM python:3.8",
    "RUN ..",
  ]
)
```

> 🚧 The `docker_image` `instructions` field
> 
> Each `docker_image` uses a `Dockerfile` referred to by the `source` field, unless you have provided a value to the `instructions` field.

Adding dependencies to your `docker_image` targets
--------------------------------------------------

A Dockerfile is built in a _context_ - a set of files that the commands in the Dockerfile can reference, e.g., by copying them into the image.

When you run `docker build` directly, the context is usually a directory within your repo containing the Dockerfile (typically at the root of the context) and any files that the build requires. If those files were themselves the product of a build step, or if they were sources from elsewhere in the repo, then you would have to copy them into the context.

Pants, however, takes care of assembling the context for you. It does so using the dependencies of the [`docker_image`](doc:reference-docker_image) target, which can include:

- Loose files specified using  [`file` / `files` targets](doc:assets#files).
- Artifacts packaged from a variety of targets, such as [`pex_binary`](doc:reference-pex_binary) , [`python_distribution`](doc:reference-python_distribution), [`archive`](doc:reference-archive), and any other target that can be built via the [package](doc:reference-package) goal, including other docker images.

The context is assembled as follows:

- The sources of `file` / `files` targets are assembled at their relative path from the repo root.
- The artifacts of any packaged targets are built, as if by running `pants package`, and placed in the context using the artifact's `output_path` field.
  - The `output_path` defaults to the scheme `path.to.directory/tgt_name.ext`, e.g. `src.python.helloworld/bin.pex`.

### Dependency inference support

When you `COPY` PEX binaries into your image, the dependency on the `pex_binary` target will be inferred, so you don't have to add that explicitly to the list of `dependencies` on your `docker_image` target.

For example, the `pex_binary` target `src/python/helloworld/bin.pex` has the default `output_path` of `src.python.helloworld/bin.pex`. So, Pants can infer a dependency based on the line `COPY src.python.helloworld/bin.pex /bin/helloworld`.

Inference for Go binaries and artifacts of other packaged targets is similar.

Inference is also supported for `docker_image` targets specified in build arguments, for example:

```dockerfile
ARG BASE_IMAGE=:base
FROM $BASE_IMAGE
```

In the example, `:base` is the base image target address specified using a relative path. Pants will provide the built Docker image name for that target as the `BASE_IMAGE` build arg to the Docker build command.

Building a Docker image
-----------------------

You build Docker images using the `package` goal:

```
❯ pants package path/to/Dockerfile
```

### Build arguments

To provide values to any [build `ARG`s](https://docs.docker.com/engine/reference/builder/#arg) in the Dockerfile, you can list them in the `[docker].build_args` option, which will apply for all images. You can also list any image-specific build args in the field `extra_build_args` for the `docker_image` target.

The build args use the same syntax as the [docker build --build-arg](https://docs.docker.com/engine/reference/commandline/build/#set-build-time-variables---build-arg) command line option: `VARNAME=VALUE`, where the value is optional, and if left out, the value is taken from the environment instead.

```toml pants.toml
[docker]
build_args = [
  "VAR1=value1",
  "VAR2"
]
```
```python example/BUILD
docker_image(
  name="docker",
  extra_build_args=["VAR1=my_value", "VAR3"]
)
```
```dockerfile example/Dockerfile
FROM python:3.8
ARG VAR1
ARG VAR2
ARG VAR3=default
...
```

### Target build stage

When your `Dockerfile` is a multi-stage build file, you may specify which stage to build with the [`--docker-build-target-stage`](doc:reference-docker#section-build-target-stage) for all images, or provide a per image setting with the `docker_image` field [`target_stage`](doc:reference-docker_image#codetarget_stagecode).

```dockerfile
FROM python:3.8 AS base
RUN <install required tools>

FROM base AS img
COPY files /
```

```
❯ pants package --docker-build-target-stage=base Dockerfile
```

See this [blog post](https://blog.pantsbuild.org/optimizing-python-docker-deploys-using-pants/) for more examples using multi-stage builds.

### Build time secrets

Secrets are supported for `docker_image` targets with the [`secrets`](doc:reference-docker_image#codesecretscode) field. The defined secrets may then be mounted in the `Dockerfile` as [usual](https://docs.docker.com/develop/develop-images/build_enhancements/#new-docker-build-secret-information).

```python BUILD
docker_image(
  secrets={
    "mysecret": "mysecret.txt",
  }
)
```
```dockerfile
FROM python:3.8

# shows secret from default secret location:
RUN --mount=type=secret,id=mysecret cat /run/secrets/mysecret

# shows secret from custom secret location:
RUN --mount=type=secret,id=mysecret,dst=/foobar cat /foobar
```
```text mysecret.txt
very-secret-value
```

> 📘 Secret file path
> 
> Secrets should not be checked into version control. Use absolute paths to reference a file that is not in the project source tree. However, to keep the BUILD file as hermetic as possible, the files may be placed within the project source tree at build time for instance, and referenced with a path relative to the project root by default, or relative to the directory of the BUILD file when prefixed with `./`.
> 
> See the example for the [`secrets`](doc:reference-docker_image#codesecretscode) field.

### Build Docker image example

This example copies both a `file` and `pex_binary`. The file is specified as an explicit dependency in the `BUILD` file, whereas the `pex_binary` dependency is inferred from the path in the `Dockerfile`.

```python src/docker/hw/BUILD
file(name="msg", source="msg.txt")

docker_image(
    name="helloworld",
    dependencies=[":msg"],
)
```
```dockerfile src/docker/hw/Dockerfile
FROM python:3.8
ENTRYPOINT ["/bin/helloworld"]
COPY src/docker/hw/msg.txt /var/msg
COPY src.python.hw/bin.pex /bin/helloworld
```
```text src/docker/hw/msg.txt
Hello, Docker!
```
```python src/python/hw/BUILD
python_sources(name="lib")

pex_binary(name="bin", entry_point="main.py")
```
```python src/python/hw/main.py
import os

msg = "Hello"
if os.path.exists("/var/msg"):
    with open("/var/msg") as fp:
        msg = fp.read().strip()

print(msg)
```

```
❯ pants package src/docker/hw/Dockerfile
08:09:22.86 [INFO] Completed: Building local_dists.pex
08:09:23.80 [INFO] Completed: Building src.python.hw/bin.pex
08:10:42.51 [INFO] Completed: Building docker image helloworld:latest
08:10:42.51 [INFO] Built docker image: helloworld:latest
Docker image ID: 1fe744d52222
```

Running a Docker image
----------------------

You can ask Pants to run a Docker image on your local system with the `run` goal:

```
❯ pants run src/docker/hw/Dockerfile
Hello, Docker!
```

Any arguments for the Docker container may be provided as pass through args to the `run` goal, as usual. That is, use either the `--args` option or after all other arguments after a separating double-dash:

```
❯ pants run src/docker/hw/Dockerfile -- arguments for the container
Hello, Docker!
```

To provide any command line arguments to the `docker run` command, you may use the `--docker-run-args` option:

```
❯ pants run --docker-run-args="-p 8080 --name demo" src/docker/hw/Dockerfile 
```

As with all configuration options, this is not limited to the command line, but may be configured in a Pants rc file (such as `pants.toml`) in the `[docker].run_args` section or as an environment variable, `PANTS_DOCKER_RUN_ARGS` as well.

Publishing images
-----------------

Pants can push your images to registries using `pants publish`:

```shell
❯ pants publish src/docker/hw:helloworld
# Will build the image and push it to all registries, with all tags.
```

Publishing may be skipped per registry or entirely per `docker_image` using `skip_push`.

See [here](doc:tagging-docker-images) for how to set up registries.

Docker configuration
--------------------

To configure the Docker binary, set `[docker].env_vars` in your `pants.toml` configuration file. You use that key to list environment variables such as `DOCKER_CONTEXT` or `DOCKER_HOST`, that will be set in the environment of the `docker` binary when Pants runs it. Each listed value can be of the form `NAME=value`, or just `NAME`, in which case the value will be inherited from the Pants process's own environment.

```toml pants.toml
[docker]
env_vars = [
  "DOCKER_CONTEXT=pants_context",
  "DOCKER_HOST"
]
```

> 📘 Docker environment variables
> 
> See [Docker documentation](https://docs.docker.com/engine/reference/commandline/cli/#environment-variables) for the authoritative table of environment variables for the Docker CLI.

Docker authentication
---------------------

To authenticate, you usually will need to:

1. Set up a Docker config file, e.g. `~/.docker/config.json`.
2. Tell Pants about the config file by setting `[docker].env_vars`.
3. Tell Pants about any tools needed for authentication to work by setting `[docker].tools`.

For example, a config file using the [GCloud helper](https://cloud.google.com/container-registry/docs/advanced-authentication#gcloud-helper) might look like this:

```
{
	"credHelpers": {
		"europe-north1-docker.pkg.dev": "gcloud"
	}
}
```

Then, tell Pants to use this config by setting `[docker].env_vars =  ["DOCKER_CONFIG=%(homedir)s/.docker"]` in `pants.toml`, for example.

Most authentication mechanisms will also require tools exposed on the `$PATH` to work. Teach Pants about those by setting the names of the tools in `[docker].tools`, and ensuring that they show up on your `$PATH`. For example, GCloud authentication requires `dirname`, `readlink` and `python3`.

```toml pants.toml
# Example GCloud authentication.

[docker]
env_vars = ["DOCKER_CONFIG=%(homedir)s/.docker"]
tools = [
  "docker-credential-gcr", # or docker-credential-gcloud when using artifact registry
  "dirname",
  "readlink",
  "python3",
  # These may be necessary if using Pyenv-installed Python.
  "cut",
  "sed",
  "bash",
]
```

You may need to set additional environment variables with `[docker].env_vars`.

> 📘 How to troubleshoot authentication
> 
> It can be tricky to figure out what environment variables and tools are missing, as the output often has indirection.
> 
> It can help to simulate a hermetic environment by using `env -i`. With credential helpers, it also helps to directly invoke the helper without Docker and Pants. For example, you can symlink the tools you think you need into a directory like `/some/isolated/directory`, then run the below:
> 
> ```
> ❯ echo europe-north1-docker.pkg.dev | env -i PATH=/some/isolated/directory docker-credential-gcr get
> {
>   "Secret": "ya29.A0ARrdaM-...-ZhScVscwTVtQ",
>   "Username": "_dcgcloud_token"
> }
> ```

Linting Dockerfiles with Hadolint
---------------------------------

Pants can run [Hadolint](https://github.com/hadolint/hadolint) on your Dockerfiles to check for errors and mistakes:

```
❯ pants lint src/docker/hw/Dockerfile
```

This must first be enabled by activating the Hadolint backend:

```toml pants.toml
[GLOBAL]
backend_packages = ["pants.backend.docker.lint.hadolint"]
```
