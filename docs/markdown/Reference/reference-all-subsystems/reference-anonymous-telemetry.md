---
title: "anonymous-telemetry"
slug: "reference-anonymous-telemetry"
hidden: false
createdAt: "2022-06-02T21:09:32.302Z"
updatedAt: "2022-06-02T21:09:32.653Z"
---
Options related to sending anonymous stats to the Pants project, to aid development.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[anonymous-telemetry]</code></span>

## Basic options

None

## Advanced options

<div style="color: purple">
  <h3><code>enabled</code></h3>
  <code>--[no-]anonymous-telemetry-enabled</code><br>
  <code>PANTS_ANONYMOUS_TELEMETRY_ENABLED</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Whether to send anonymous telemetry to the Pants project.

Telemetry is sent asynchronously, with silent failure, and does not impact build times or outcomes.

See [Anonymous telemetry](doc:anonymous-telemetry) for details.
</div>
<br>

<div style="color: purple">
  <h3><code>repo_id</code></h3>
  <code>--anonymous-telemetry-repo-id=&lt;str&gt;</code><br>
  <code>PANTS_ANONYMOUS_TELEMETRY_REPO_ID</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

An anonymized ID representing this repo.

For private repos, you likely want the ID to not be derived from, or algorithmically convertible to, anything identifying the repo.

For public repos the ID may be visible in that repo's config file, so anonymity of the repo is not guaranteed (although user anonymity is always guaranteed).

See [Anonymous telemetry](doc:anonymous-telemetry) for details.
</div>
<br>


## Deprecated options

None