---
title: "Remote execution"
slug: "remote-execution"
hidden: false
createdAt: "2020-11-13T23:44:25.806Z"
updatedAt: "2021-03-19T21:47:56.096Z"
---
[block:callout]
{
  "type": "warning",
  "title": "Remote execution support is still experimental",
  "body": "Remote execution support in Pants comes with several limitations. For example, Pants requires that the server's operating system match the client's operating system. In practice, this means that Pants must be running on Linux because all three major server projects generally only operate on Linux."
}
[/block]
# What is remote execution?

"Remote execution" allows Pants to offload execution of processes to a remote server that complies with the [Remote Execution API](https://github.com/bazelbuild/remote-apis) standard ("REAPI"). The REAPI standard is supported by several different server and client projects including Bazel and of course Pants.

# Setup

## Server

Remote execution requires the availability of a REAPI-compatible execution server. See the [REAPI server compatibility guide](doc:remote-caching-execution#server-compatibility) for more information.

## Pants

After you have either set up a REAPI server or obtained access to one, the next step is to point Pants to it so that Pants may submit REAPI execution requests. The server should be running a CAS and execution service. These may be the same network endpoint, but for Pants' purposes, they are configured by different configuration options.

For the following examples, assume that the REAPI server is running on `build.corp.example.com` at port 8980 and that it is on an internal network (and for the sake of this example is not running TLS, which will be covered later). Also, assume that the name of the REAPI instance is "main." At a minimum, you will need to configure `pants.toml` as follows:

```toml
[GLOBAL]
remote_execution = true
remote_store_address = "grpc://build.corp.example.com:8980"
remote_execution_address = "grpc://build.corp.example.com:8980"
remote_instance_name = "main"
```

### Platform Properties

The REAPI execution service selects a worker for a process by consulting the "platform properties" that are passed in a remote execution request. These platform properties are key/value pairs that are configured in the server. Generally, you will configure these in the server (or be provided them by your server's administrator), and then configure Pants to use what was configured.

Assume that the REAPI server is configured with `OSFamily=linux` as the only platform properties. Then building on the first example earlier, add the `remote_execution_extra_platform_properties` to `pants.toml`:

```toml
[GLOBAL]
remote_execution = true
remote_store_address = "grpc://build.corp.example.com:8980"
remote_execution_address = "grpc://build.corp.example.com:8980"
remote_instance_name = "main"
remote_execution_extra_platform_properties = [
  "OSFamily=linux",
]
```

### Concurrency

Finally, you should configure Pants to limit the number of concurrent execution requests that are sent to the REAPI server. The `process_execution_remote_parallelism` option controls this concurrency. For example, if `process_execution_remote_parallelism` is set to `20`, then Pants will only send a maximum of 20 execution requests at a single moment of time.

Note: The specific value depends on the resources available to the REAPI server. If this value is configured to a high number, then Pants will happily send that many concurrent execution requests, which could potentially overwhelm the REAPI server.

Building on the previous example, `pants.toml` would contain:

```toml
[GLOBAL]
remote_execution = true
remote_store_address = "grpc://build.corp.example.com:8980"
remote_execution_address = "grpc://build.corp.example.com:8980"
remote_instance_name = "main"
remote_execution_extra_platform_properties = [
  "OSFamily=linux",
]
process_execution_remote_parallelism = 20
```

### TLS

You can enable TLS by prefixing the `remote_store_address` and `remote_execution_address` with `grpcs://` instead of `grpc://`.

Pants will automatically discover root CA certificates on your machine, but you can also configure Pants to use your preferred certificates with the `--remote-ca-certs-path` option.

Assume that the REAPI server is running on port 443 (https/TLS) at build.example.com. Then the relevant parts of `pants.toml` would contain:

```toml
[GLOBAL]
remote_execution = true
remote_store_address = "grpcs://build.example.com:443"
remote_execution_address = "grpcs://build.example.com:443"
remote_instance_name = "main"
# This is optional, Pants will auto-discover certificates otherwise.
remote_ca_certs_path = "/etc/ssl/certs/ca-certificates.crt"
```

# Reference

Run `./pants help-advanced global` or refer to [Global options](doc:reference-global). Most remote execution and caching options begin with the prefix `--remote`.

# Limitations

The remote execution support in Pants is still experimental and comes with several limitations:

1. The main limitation is that Pants assumes that the remote execution platform is the same as the local platform. Thus, if the remote execution service is running on Linux, then Pants must also be running on Linux in order to successfully submit remote execution requests. This limitation will eventually be fixed, but as of version 2.0.x, Pants still has the limitation.

2. The remote execution environment will need to contain appropriate tooling expected by the Pants subsystems used in your repository. At a minimum, this means a Python interpreter must be available if building Python code. If using protobuf support, then you may also need `unzip` available in the remote execution environment in order to unpack the protoc archive. This documentation is incomplete with regards to what tooling needs to be available.