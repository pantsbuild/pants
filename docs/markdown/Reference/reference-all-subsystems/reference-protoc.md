---
title: "protoc"
slug: "reference-protoc"
hidden: false
createdAt: "2022-06-02T21:09:58.725Z"
updatedAt: "2022-06-02T21:09:59.231Z"
---
The protocol buffer compiler (https://developers.google.com/protocol-buffers).

Backend: <span style="color: purple"><code>pants.backend.codegen.protobuf.python</code></span>
Config section: <span style="color: purple"><code>[protoc]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>dependency_inference</code></h3>
  <code>--[no-]protoc-dependency-inference</code><br>
  <code>PANTS_PROTOC_DEPENDENCY_INFERENCE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Infer Protobuf dependencies on other Protobuf files by analyzing import statements.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--protoc-version=&lt;str&gt;</code><br>
  <code>PANTS_PROTOC_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>3.20.1</code></span>

<br>

Use this version of protoc.
</div>
<br>

<div style="color: purple">
  <h3><code>known_versions</code></h3>
  <code>--protoc-known-versions=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_PROTOC_KNOWN_VERSIONS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "3.20.1|linux&lowbar;arm64 |8a5a51876259f934cd2acc2bc59dba0e9a51bd631a5c37a4b9081d6e4dbc7591|1804837",
  "3.20.1|linux&lowbar;x86&lowbar;64|3a0e900f9556fbcac4c3a913a00d07680f0fdf6b990a341462d822247b265562|1714731",
  "3.20.1|macos&lowbar;arm64 |b362acae78542872bb6aac8dba73aaf0dc6e94991b8b0a065d6c3e703fec2a8b|2708249",
  "3.20.1|macos&lowbar;x86&lowbar;64|b4f36b18202d54d343a66eebc9f8ae60809a2a96cc2d1b378137550bbe4cf33c|2708249"
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
  <code>--protoc-use-unsupported-version=&lt;UnsupportedVersionUsage&gt;</code><br>
  <code>PANTS_PROTOC_USE_UNSUPPORTED_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>error, warning</code></span><br>
<span style="color: green">default: <code>error</code></span>

<br>


What action to take in case the requested version of protoc is not supported.

Supported protoc versions: unspecified

</div>
<br>

<div style="color: purple">
  <h3><code>url_template</code></h3>
  <code>--protoc-url-template=&lt;str&gt;</code><br>
  <code>PANTS_PROTOC_URL_TEMPLATE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>https://github.com/protocolbuffers/protobuf/releases/download/v{version}/protoc-{version}-{platform}.zip</code></span>

<br>

URL to download the tool, either as a single binary file or a compressed file (e.g. zip file). You can change this to point to your own hosted file, e.g. to work with proxies or for access via the filesystem through a `file:$abspath` URL (e.g. `file:/this/is/absolute`, possibly by [templating the buildroot in a config file]([Options](doc:options)#config-file-entries)).

Use `{version}` to have the value from --version substituted, and `{platform}` to have a value from --url-platform-mapping substituted in, depending on the current platform. For example, https://github.com/.../protoc-{version}-{platform}.zip.
</div>
<br>

<div style="color: purple">
  <h3><code>url_platform_mapping</code></h3>
  <code>--protoc-url-platform-mapping=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_PROTOC_URL_PLATFORM_MAPPING</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>{
  "linux&lowbar;arm64": "linux-aarch&lowbar;64",
  "linux&lowbar;x86&lowbar;64": "linux-x86&lowbar;64",
  "macos&lowbar;arm64": "osx-aarch&lowbar;64",
  "macos&lowbar;x86&lowbar;64": "osx-x86&lowbar;64"
}</pre></span>

<br>

A dictionary mapping platforms to strings to be used when generating the URL to download the tool.

In --url-template, anytime the `{platform}` string is used, Pants will determine the current platform, and substitute `{platform}` with the respective value from your dictionary.

For example, if you define `{"macos_x86_64": "apple-darwin", "linux_x86_64": "unknown-linux"}`, and run Pants on Linux with an intel architecture, then `{platform}` will be substituted in the --url-template option with unknown-linux.
</div>
<br>


## Deprecated options

None