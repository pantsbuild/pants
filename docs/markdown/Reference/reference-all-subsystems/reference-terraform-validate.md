---
title: "terraform-validate"
slug: "reference-terraform-validate"
hidden: false
createdAt: "2022-06-02T21:10:19.173Z"
updatedAt: "2022-06-02T21:10:19.574Z"
---
Terraform validate options.

Backend: <span style="color: purple"><code>pants.backend.experimental.terraform</code></span>
Config section: <span style="color: purple"><code>[terraform-validate]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>skip</code></h3>
  <code>--[no-]terraform-validate-skip</code><br>
  <code>PANTS_TERRAFORM_VALIDATE_SKIP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Don't use `terraform validate` when running `./pants check`.
</div>
<br>


## Advanced options

None

## Deprecated options

None