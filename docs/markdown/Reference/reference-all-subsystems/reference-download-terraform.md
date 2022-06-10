---
title: "download-terraform"
slug: "reference-download-terraform"
hidden: false
createdAt: "2022-06-02T21:09:41.620Z"
updatedAt: "2022-06-02T21:09:41.992Z"
---
Terraform (https://terraform.io)

Backend: <span style="color: purple"><code>pants.backend.experimental.terraform</code></span>
Config section: <span style="color: purple"><code>[download-terraform]</code></span>

## Basic options

None

## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--download-terraform-version=&lt;str&gt;</code><br>
  <code>PANTS_DOWNLOAD_TERRAFORM_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>1.0.7</code></span>

<br>

Use this version of terraform.
</div>
<br>

<div style="color: purple">
  <h3><code>known_versions</code></h3>
  <code>--download-terraform-known-versions=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_DOWNLOAD_TERRAFORM_KNOWN_VERSIONS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "1.0.7|macos&lowbar;arm64 |cbab9aca5bc4e604565697355eed185bb699733811374761b92000cc188a7725|32071346",
  "1.0.7|macos&lowbar;x86&lowbar;64|80ae021d6143c7f7cbf4571f65595d154561a2a25fd934b7a8ccc1ebf3014b9b|33020029",
  "1.0.7|linux&lowbar;x86&lowbar;64|bc79e47649e2529049a356f9e60e06b47462bf6743534a10a4c16594f443be7b|32671441"
]</pre></span>

<br>


Known versions to verify downloads against.

Each element is a pipe-separated string of `version|platform|sha256|length`, where:

    - `version` is the version string
    - `platform` is one of [linux_arm64,linux_x86_64,macos_arm64,macos_x86_64],
    - `sha256` is the 64-character hex representation of the expected sha256
    digest of the download file, as emitted by `shasum -a 256`
    - `length` is the expected length of the download file in bytes, as emitted by
    `wc -c`

E.g., `3.1.2|macos_x86_64|6d0f18cd84b918c7b3edd0203e75569e0c7caecb1367bbbe409b44e28514f5be|42813`.

Values are space-stripped, so pipes can be indented for readability if necessary.

</div>
<br>

<div style="color: purple">
  <h3><code>use_unsupported_version</code></h3>
  <code>--download-terraform-use-unsupported-version=&lt;UnsupportedVersionUsage&gt;</code><br>
  <code>PANTS_DOWNLOAD_TERRAFORM_USE_UNSUPPORTED_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>error, warning</code></span><br>
<span style="color: green">default: <code>error</code></span>

<br>


What action to take in case the requested version of terraform is not supported.

Supported terraform versions: unspecified

</div>
<br>

<div style="color: purple">
  <h3><code>url_template</code></h3>
  <code>--download-terraform-url-template=&lt;str&gt;</code><br>
  <code>PANTS_DOWNLOAD_TERRAFORM_URL_TEMPLATE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>https://releases.hashicorp.com/terraform/{version}/terraform&lowbar;{version}&lowbar;{platform}.zip</code></span>

<br>

URL to download the tool, either as a single binary file or a compressed file (e.g. zip file). You can change this to point to your own hosted file, e.g. to work with proxies or for access via the filesystem through a `file:$abspath` URL (e.g. `file:/this/is/absolute`, possibly by [templating the buildroot in a config file]([Options](doc:options)#config-file-entries)).

Use `{version}` to have the value from --version substituted, and `{platform}` to have a value from --url-platform-mapping substituted in, depending on the current platform. For example, https://github.com/.../protoc-{version}-{platform}.zip.
</div>
<br>

<div style="color: purple">
  <h3><code>url_platform_mapping</code></h3>
  <code>--download-terraform-url-platform-mapping=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_DOWNLOAD_TERRAFORM_URL_PLATFORM_MAPPING</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>{
  "linux&lowbar;x86&lowbar;64": "linux&lowbar;amd64",
  "macos&lowbar;arm64": "darwin&lowbar;arm64",
  "macos&lowbar;x86&lowbar;64": "darwin&lowbar;amd64"
}</pre></span>

<br>

A dictionary mapping platforms to strings to be used when generating the URL to download the tool.

In --url-template, anytime the `{platform}` string is used, Pants will determine the current platform, and substitute `{platform}` with the respective value from your dictionary.

For example, if you define `{"macos_x86_64": "apple-darwin", "linux_x86_64": "unknown-linux"}`, and run Pants on Linux with an intel architecture, then `{platform}` will be substituted in the --url-template option with unknown-linux.
</div>
<br>


## Deprecated options

None