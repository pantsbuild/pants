---
title: "terraform-fmt"
slug: "reference-terraform-fmt"
hidden: false
createdAt: "2022-06-02T21:10:17.965Z"
updatedAt: "2022-06-02T21:10:18.336Z"
---
Terraform fmt options.

Backend: <span style="color: purple"><code>pants.backend.experimental.terraform</code></span>
Config section: <span style="color: purple"><code>[terraform-fmt]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>skip</code></h3>
  <code>--[no-]terraform-fmt-skip</code><br>
  <code>PANTS_TERRAFORM_FMT_SKIP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Don't use `terraform fmt` when running `./pants fmt` and `./pants lint`.
</div>
<br>


## Advanced options

None

## Deprecated options

None