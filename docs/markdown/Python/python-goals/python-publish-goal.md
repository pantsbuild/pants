---
title: "publish"
slug: "python-publish-goal"
excerpt: "How to distribute packages to a PyPi repository"
hidden: true
createdAt: "2021-10-05T08:10:25.568Z"
updatedAt: "2022-01-11T16:09:21.278Z"
---
The `publish` goal is currently in the experimental Python backend. Activate with this config:

```toml pants.toml
[GLOBAL]
backend_packages.add = [
  "pants.backend.experimental.python",
]
```

This will register a new `repositories` field for the `python_distribution` target, so when you run `pants publish` for those targets, they will package  them and then publish the distributions using Twine to the repositories specified in your BUILD files.

Python Repositories
-------------------

When publishing a `python_distribution`, you need to tell Pants which repositories to publish to. That is done with a new `repositories` field on the `python_distribution`.

```python src/python/BUILD
python_distribution(
  name="demo",
  # ...
  repositories=[
    "@pypi",
    "@private-repo",
    "https://pypi.private2.example.com",
  ]
)
```
```text .pypirc
[distutils]
index-servers =
	pypi
  private-repo

[pypi]
username: publisher-example

[private-repo]
repository: https://pypi.private.example.com
```

The repositories are either references to a configured repository in the `.pypirc` file when prefixed with `@`, or the repository URL otherwise.

> ❗️ Keep Secrets Secret
> 
> We strongly discourage the use of secrets verbatim in your configuration files.
> 
> Better is to inject the required secrets as environment variables only when needed when running `pants publish`, or better still is to use `keyring` is possible as described in the [Twine documentation](https://twine.readthedocs.io/en/latest/#keyring-support)

Environment variables
---------------------

Twine may be configured using [environment variables](https://twine.readthedocs.io/en/latest/#environment-variables), and this is supported also when publishing with Pants. However, as there may be multiple repositories involved with a single `publish` goal, the repository name should be used (upper cased, and with hyphens replaced with underscores) as suffix on the variable names.

It is only repositories configured with the URL directly in the build file that don't have any special suffix, so does not scale to multiple different repositories if using environment variables is a requirement.

Only the following environment variable names are considered when running Twine:

- `TWINE_USERNAME` 
- `TWINE_USERNAME_<repository>`
- `TWINE_PASSWORD`
- `TWINE_PASSWORD_<repository>`
- `TWINE_REPOSITORY_URL`
- `TWINE_REPOSITORY_URL_<repository>`

```shell secrets
# Ephemeral file
export TWINE_USERNAME_PRIVATE_REPO="accountname"
export TWINE_PASSWORD_PRIVATE_REPO="secretvalue"
```

Given the example `BUILD` and `.pypirc` files from the previous section, `demo` could be published with the following command:

```shell
$ { source ./secrets && pants publish src/python:demo }
```
