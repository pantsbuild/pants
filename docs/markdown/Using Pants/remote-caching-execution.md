---
title: "Remote caching & execution"
slug: "remote-caching-execution"
hidden: false
createdAt: "2021-03-19T21:39:51.235Z"
---
Overview
========

By default, Pants executes processes in a local [environment](doc:environments) on the system on which it is run, and caches the results of those processes locally as well. Besides this "local execution" mode of operation, Pants also supports two distributed modes of operation:

1. "Remote caching" where Pants store results from local process execution in a remote cache and also consumes results from that remote cache; and

2. "Remote execution" where Pants offloads execution of processes to a remote server (and consumes cached results from that remote server)

Pants does this by using the "Remote Execution API" to converse with the remote cache or remote execution server.

What is Remote Execution API?
-----------------------------

Pants is compatible with remote caching and remote execution servers that comply with the [Remote Execution API](https://github.com/bazelbuild/remote-apis) standard ("REAPI"). The REAPI protocol is supported by several different server and client projects including Bazel and of course Pants.

REAPI servers implement several related but distinct services:

1. A "content-addressable storage" service that stores data keyed by the hash of that data (also known as a "CAS").
2. An "action cache service" that maps process executions to their results.
3. An "execution service" that executes processes by using the content-addressable storage service to obtain the inputs and store the outputs from running those processes.

Remote cache servers implement the CAS and action cache services. Remote execution servers implement all three services.

Pants calls the CAS a "store server" and the execution service an "execution server." These are logically distinct in the REAPI, but in fact may be exposed to clients on the same network endpoint.

The REAPI model contains the notion of an "instance." An "instance" is a distinct deployment of a CAS and/or execution service that is given a specific name. All REAPI operations send an instance name to the server, thus a single network endpoint can conceivably support multiple REAPI deployments.

Server compatibility
====================

In order to use remote caching or remote execution, Pants will need access to a server that complies with REAPI. Pants is known to work with:

**Self-hosted**:
- [BuildBarn](https://github.com/buildbarn/bb-remote-execution)
- [Buildfarm](https://github.com/bazelbuild/bazel-buildfarm/) 
- [BuildGrid](https://buildgrid.build/)

**Note**: Setup of a self-hosted REAPI server is beyond the scope of this documentation. All these server projects have support channels on the BuildTeamWorld Slack. [Go here to obtain an invite to that Slack.](https://bit.ly/2SG1amT)

As a more lightweight solution - for caching only - Pants can use a server providing only the CAS (content-addressable storage) service.

**Self-hosted**:

- [bazel-remote-cache](https://github.com/buchgr/bazel-remote)

Bazel Remote Cache supports local disk, S3, GCS, and Azure Blob storage options - needing only a single lightweight Docker container.

There are a few [other](https://github.com/bazelbuild/remote-apis) systems and services in this space, but they have not, to our knowledge, been tested with Pants.  Let us know if you have any experience with them!

Resources
=========

- The [remote-apis-testing project](https://gitlab.com/remote-apis-testing/remote-apis-testing) maintains a compatibility test suite of the various server and client implementations of REAPI.
