---
title: "Terraform Overview"
slug: "terraform-overview"
hidden: false
createdAt: "2023-11-22T17:00:00.000Z"
---
> 🚧 Terraform support is in alpha stage
> 
> Pants is currently building support for developing and deploying Terraform. Simple use cases might be supported, but many options are missing. 
> 
> Please share feedback for what you need to use Pants with your Terraform modules and deployments by either [opening a GitHub issue](https://github.com/pantsbuild/pants/issues/new/choose) or [joining our Slack](doc:getting-help)!

Initial setup
=============

First, activate the relevant backend in `pants.toml`:

```toml pants.toml
[GLOBAL]
backend_packages = [
  ...
  "pants.backend.experimental.terraform",
  ...
]
```

The Terraform backend also needs Python to run Pants's analysers. The setting `[python].interpreter_constraints` will need to be set.

Adding Terraform targets
------------------------

The Terraform backend has 2 target types:
- `terraform_module` for Terraform source code
- `terraform_deployment` for deployments that can be deployed with the `experimental-deploy` goal

### Modules

The `tailor` goal will automatically generate `terraform_module` targets. Run [`pants tailor ::`](doc:initial-configuration#5-generate-build-files). For example:

```
❯ pants tailor ::
Created src/terraform/root/BUILD:
  - Add terraform_module target root
```

### Deployments

`terraform_deployments` must be manually created. The deployment points to a `terraform_module` target as its `root_module` field. This module will be the "root" module that Terraform operations will be run on. You can reference vars files with the `var_files` field. You can have multiple deployments reference the same module:


```
terraform_module(name="root")
terraform_deployment(name="prod", root_module=":root", var_files=["prod.tfvars"]) 
terraform_deployment(name="test", root_module=":root", var_files=["test.tfvars"]) 
```

### Lockfiles

Automatic lockfile management is currently in progress. You can include lockfiles manually as a dependency:

```
terraform_deployment(name="prod", root_module=":root", dependencies=[":lockfile"])
file(name="lockfile", source=".terraform.lock.hcl")
```

Basic Operations
----------------

### Formatting

Run `terraform fmt` as part of the `fix`, `fmt`, or `lint` goals.

```
pants fix ::
[INFO] Completed: pants.backend.terraform.lint.tffmt.tffmt.tffmt_fmt - terraform-fmt made no changes.

✓ terraform-fmt made no changes.
```

### Validate

Run `terraform validate` as part of the `check` goal.

```
pants check ::
[INFO] Completed: pants.backend.terraform.goals.check.terraform_check - terraform-validate succeeded.
Success! The configuration is valid.

✓ terraform-validate succeeded.

```

`terraform validate` isn't valid for all Terraform modules. Some child modules, in particular those using aliased providers, need to have their providers provided by a "root" module. You can opt these modules out of `validate` by setting `skip_terraform_validate=True`. For example:

```
terraform_module(skip_terraform_validate=True)
```

### Deploying

> 🚧 Terraform deployment support is in alpha stage
> 
> Many options and features aren't supported yet. 
> Local state backends aren't supported.


Run `terraform apply` as part of the `experimental-deploy` goal. The process is run interactively, so you will be prompted for variables and confirmation as usual.

```
pants experimental-deploy ::
[INFO] Deploying targets...
--- 8< ---
Do you want to perform these actions?
  Terraform will perform the actions described above.
  Only 'yes' will be accepted to approve.

  Enter a value: yes
--- 8< ---
Apply complete! Resources: 4 added, 0 changed, 0 destroyed.

✓ testprojects/src/terraform/root:root deployed
```

You can set auto approve by adding `-auto-approve` to the `[download-terraform].args` setting in `pants.toml`. You can also set it for a single pants invocation with `--download-terraform-args='-auto-approve'`, for example `pants experimental-deploy "--download-terraform-args='-auto-approve'"`.
