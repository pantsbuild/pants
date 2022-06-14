---
title: "publish"
slug: "python-publish-goal"
excerpt: "How to distribute packages to a PyPi repository"
hidden: true
createdAt: "2021-10-05T08:10:25.568Z"
updatedAt: "2022-01-11T16:09:21.278Z"
---
The `publish` goal is currently in the experimental Python backend. Activate with this config:

[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nbackend_packages.add = [\n  \"pants.backend.experimental.python\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
This will register a new `repositories` field for the `python_distribution` target, so when you run `./pants publish` for those targets, they will package  them and then publish the distributions using Twine to the repositories specified in your BUILD files.
[block:api-header]
{
  "title": "Python Repositories"
}
[/block]
When publishing a `python_distribution`, you need to tell Pants which repositories to publish to. That is done with a new `repositories` field on the `python_distribution`.
[block:code]
{
  "codes": [
    {
      "code": "python_distribution(\n  name=\"demo\",\n  # ...\n  repositories=[\n    \"@pypi\",\n    \"@private-repo\",\n    \"https://pypi.private2.example.com\",\n  ]\n)",
      "language": "python",
      "name": "src/python/BUILD"
    },
    {
      "code": "[distutils]\nindex-servers =\n\tpypi\n  private-repo\n\n[pypi]\nusername: publisher-example\n\n[private-repo]\nrepository: https://pypi.private.example.com",
      "language": "text",
      "name": ".pypirc"
    }
  ]
}
[/block]
The repositories are either references to a configured repository in the `.pypirc` file when prefixed with `@`, or the repository URL otherwise.
[block:callout]
{
  "type": "danger",
  "title": "Keep Secrets Secret",
  "body": "We strongly discourage the use of secrets verbatim in your configuration files.\n\nBetter is to inject the required secrets as environment variables only when needed when running `./pants publish`, or better still is to use `keyring` is possible as described in the [Twine documentation](https://twine.readthedocs.io/en/latest/#keyring-support)"
}
[/block]

[block:api-header]
{
  "title": "Environment variables"
}
[/block]
Twine may be configured using [environment variables](https://twine.readthedocs.io/en/latest/#environment-variables), and this is supported also when publishing with Pants. However, as there may be multiple repositories involved with a single `publish` goal, the repository name should be used (upper cased, and with hyphens replaced with underscores) as suffix on the variable names.

It is only repositories configured with the URL directly in the build file that don't have any special suffix, so does not scale to multiple different repositories if using environment variables is a requirement.

Only the following environment variable names are considered when running Twine:
* `TWINE_USERNAME` 
* `TWINE_USERNAME_<repository>`
* `TWINE_PASSWORD`
* `TWINE_PASSWORD_<repository>`
* `TWINE_REPOSITORY_URL`
* `TWINE_REPOSITORY_URL_<repository>`

[block:code]
{
  "codes": [
    {
      "code": "# Ephemeral file\nexport TWINE_USERNAME_PRIVATE_REPO=\"accountname\"\nexport TWINE_PASSWORD_PRIVATE_REPO=\"secretvalue\"",
      "language": "shell",
      "name": "secrets"
    }
  ]
}
[/block]
Given the example `BUILD` and `.pypirc` files from the previous section, `demo` could be published with the following command:

```shell
$ { source ./secrets && ./pants publish src/python:demo }
```