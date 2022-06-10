---
title: "pex-cli"
slug: "reference-pex-cli"
hidden: false
createdAt: "2022-06-02T21:09:57.354Z"
updatedAt: "2022-06-02T21:09:57.831Z"
---
The PEX (Python EXecutable) tool (https://github.com/pantsbuild/pex).

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[pex-cli]</code></span>

## Basic options

None

## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--pex-cli-version=&lt;str&gt;</code><br>
  <code>PANTS_PEX_CLI_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>v2.1.90</code></span>

<br>

Use this version of pex.

Supported pex versions: >=2.1.90,<3.0
</div>
<br>

<div style="color: purple">
  <h3><code>known_versions</code></h3>
  <code>--pex-cli-known-versions=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_PEX_CLI_KNOWN_VERSIONS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "v2.1.90|macos&lowbar;arm64|2781255baf77c2a8fdc85c5e830f7191a6048fd91d2e20b5c7a20e5a0b7beb66|3755345",
  "v2.1.90|macos&lowbar;x86&lowbar;64|2781255baf77c2a8fdc85c5e830f7191a6048fd91d2e20b5c7a20e5a0b7beb66|3755345",
  "v2.1.90|linux&lowbar;x86&lowbar;64|2781255baf77c2a8fdc85c5e830f7191a6048fd91d2e20b5c7a20e5a0b7beb66|3755345"
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
  <code>--pex-cli-use-unsupported-version=&lt;UnsupportedVersionUsage&gt;</code><br>
  <code>PANTS_PEX_CLI_USE_UNSUPPORTED_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>error, warning</code></span><br>
<span style="color: green">default: <code>error</code></span>

<br>


What action to take in case the requested version of pex is not supported.

Supported pex versions: >=2.1.90,<3.0

</div>
<br>

<div style="color: purple">
  <h3><code>url_template</code></h3>
  <code>--pex-cli-url-template=&lt;str&gt;</code><br>
  <code>PANTS_PEX_CLI_URL_TEMPLATE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>https://github.com/pantsbuild/pex/releases/download/{version}/pex</code></span>

<br>

URL to download the tool, either as a single binary file or a compressed file (e.g. zip file). You can change this to point to your own hosted file, e.g. to work with proxies or for access via the filesystem through a `file:$abspath` URL (e.g. `file:/this/is/absolute`, possibly by [templating the buildroot in a config file]([Options](doc:options)#config-file-entries)).

Use `{version}` to have the value from --version substituted, and `{platform}` to have a value from --url-platform-mapping substituted in, depending on the current platform. For example, https://github.com/.../protoc-{version}-{platform}.zip.
</div>
<br>

<div style="color: purple">
  <h3><code>url_platform_mapping</code></h3>
  <code>--pex-cli-url-platform-mapping=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_PEX_CLI_URL_PLATFORM_MAPPING</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>{}</code></span>

<br>

A dictionary mapping platforms to strings to be used when generating the URL to download the tool.

In --url-template, anytime the `{platform}` string is used, Pants will determine the current platform, and substitute `{platform}` with the respective value from your dictionary.

For example, if you define `{"macos_x86_64": "apple-darwin", "linux_x86_64": "unknown-linux"}`, and run Pants on Linux with an intel architecture, then `{platform}` will be substituted in the --url-template option with unknown-linux.
</div>
<br>


## Deprecated options

None