---
title: "Upgrade tips"
slug: "upgrade-tips"
excerpt: "How we recommend staying up-to-date with Pants."
hidden: false
createdAt: "2020-05-16T22:53:24.499Z"
---
> 📘 Reminder: change the `pants_version` to upgrade
>
> Change the `pants_version` option in the `[GLOBAL]` scope in your pants.toml to upgrade.
>
> You can see all releases at <https://github.com/pantsbuild/pants/releases>.

Upgrade one minor release at a time
-----------------------------------

Per our [Deprecation policy](doc:deprecation-policy), deprecations must last a minimum of one minor release. For example, something may be deprecated in 2.1.0 and then removed in 2.2.0.

This means that it is helpful to upgrade one minor release at a time so that you can see all deprecation warnings.

You do not need to land every upgrade into your organization—often, you will want to upgrade your organization multiple versions at a time, e.g. 2.1.0 to 2.4.0. But, when you are working on the upgrade locally, it is helpful to iterate one version at a time.

First, see if Pants can automatically fix any safe deprecations for you:

```bash
# To avoid unrelated formatting changes, you may want to use `--no-fmt`.
❯ pants update-build-files --no-fmt ::
```

You can add `update-build-files` to your [continuous integration](doc:using-pants-in-ci) so that developers don't accidentally use removed features:

```bash
❯ pants update-build-files --check ::
```

Then, see if there are any remaining deprecation warnings:

```bash
❯ pants
❯ pants list :: > /dev/null
❯ pants filedeps :: > /dev/null
```

It is also helpful to spot-check that your main commands like `lint`, `package`, and `test` still work by running on a single target.

> 📘 Use dev releases for the newest
>
> As described in our [Release strategy](doc:release-strategy), we make weekly dev releases with all the latest features and bug fixes we've been working on. While dev releases are less stable, they mean you get access to improvements sooner.
>
> If you encounter any blocking issues, you can easily roll back to a prior version by changing the `pants_version` option. (Please let us know the issue by opening a [GitHub issue](https://github.com/pantsbuild/pants/issues) or messaging us on [Slack](doc:the-pants-community)).

Ignore deprecation messages with `ignore_warnings`
--------------------------------------------------

Sometimes when upgrading, you will not have time to fully fix the deprecation. The `ignore_warnings` option allows you to silence those deprecations.

The `ignore_warnings` option expects a string with the start of the deprecation warning. You can also prefix the string with `$regex$` to use a regex pattern instead of literal string matching.

```toml pants.toml
[GLOBAL]
ignore_warnings = [
  "DEPRECATED: option 'config' in scope 'flake8' will be removed",
  "$regex$DEPRECATED:\\s*",
]
```

Check for updates to the `pants` script
-----------------------------------------

Run `curl -L -o pants https://pantsbuild.github.io/setup/pants` to check if there have been any changes, e.g. adding support for running Pants with new Python interpreters.

> 🚧 Consider migrating to the new `pants` binary
> 
> The `pants` script is deprecated. The new `pants` binary has many improvements over the script, including an embedded Python runtime. The [installation page](doc:installation) has more details on how to migrate.

Find any bugs or issues?
------------------------

Please either open a [GitHub issue](https://github.com/pantsbuild/pants/issues) or head over to [Slack](doc:the-pants-community). We'd be happy to help and would appreciate knowing about the issue!
