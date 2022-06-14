---
title: "Installing Pants"
slug: "installation"
hidden: false
createdAt: "2020-02-21T17:44:53.022Z"
updatedAt: "2022-05-03T20:48:35.453Z"
---
[block:api-header]
{
  "title": "Creating the launch script"
}
[/block]
Pants is invoked via a launch script named `./pants` , saved at the root of the repository. This script will install Pants and handle upgrades.

First, set up a minimal `pants.toml` config file to instruct the script to download the latest 2.11 release:

```bash
printf '[GLOBAL]\npants_version = "2.11.0"\n' > pants.toml
```

Then, download the script:

```bash
curl -L -O https://static.pantsbuild.org/setup/pants && chmod +x ./pants
```

Now, run this to bootstrap Pants and to verify the version it installs:

```bash
./pants --version
```
[block:callout]
{
  "type": "info",
  "title": "Add `./pants` to version control",
  "body": "You should check the `./pants` script into your repo so that all users can easily run Pants."
}
[/block]

[block:callout]
{
  "type": "success",
  "body": "The `./pants` script will automatically install and use the Pants version specified in `pants.toml`, so upgrading Pants is as simple as editing `pants_version` in that file.",
  "title": "Upgrading Pants"
}
[/block]

[block:api-header]
{
  "title": "Running Pants from unreleased builds"
}
[/block]
To use an unreleased build of Pants from the [pantsbuild/pants](https://github.com/pantsbuild/pants) main branch, locate the main branch SHA, set PANTS_SHA=<SHA> in the environment, and run `./pants` as usual:

```bash
PANTS_SHA=22c566e78b4dd982958429813c82e9f558957817 ./pants --version
```
[block:api-header]
{
  "title": "Building Pants from sources"
}
[/block]
We currently distribute Pants for Linux (x86_64) and macOS.

If you need to run Pants on some other platform, such as Linux on ARM or Alpine Linux, you can try building it yourself by checking out the [Pants repo](https://github.com/pantsbuild/pants), and running `./pants package src/python/pants:pants-packaged` to build a wheel.
[block:api-header]
{
  "title": "Running Pants from sources"
}
[/block]
See [here](doc:running-pants-from-sources) for instructions on how to run Pants directly from its sources.

This is useful when making changes directly to Pants, to see how those changes impact your repo.