---
title: "Remote caching"
slug: "remote-caching"
hidden: false
createdAt: "2021-03-19T21:40:24.451Z"
updatedAt: "2022-04-26T19:47:08.373Z"
---
# What is remote caching?

Remote caching allows Pants to store and retrieve the results of process execution to and from a remote server that complies with the [Remote Execution API](https://github.com/bazelbuild/remote-apis) standard ("REAPI"), rather than only using your machine's local Pants cache. This allows Pants to share a cache across different runs and different machines, for example, all of your CI workers sharing the same fine-grained cache.

# Setup

## Server

Remote caching requires the availability of a REAPI-compatible cache. See the [REAPI server compatibility guide](doc:remote-caching-execution#server-compatibility) for more information.

## Pants Configuration

After you have either set up a REAPI cache server or obtained access to one, the next step is to point Pants to it so that Pants will use it to read and write process results. 

For the following examples, assume that the REAPI server is running on `cache.corp.example.com` at port 8980 and that it is on an internal network. Also assume that the name of the REAPI instance is "main." At a minimum, you will need to configure `pants.toml` as follows:

```toml
[GLOBAL]
remote_cache_read = true
remote_cache_write = true
remote_store_address = "grpc://build.corp.example.com:8980"
remote_instance_name = "main"
```

If the endpoint is using TLS, then the `remote_store_address` option would be specified with the  `grpcs://` scheme, i.e. `"grpcs://cache.corp.example.com:8980"`.

# Reference

Run `./pants help-advanced global` or refer to [Global options](doc:reference-global). Most remote execution and caching options begin with the prefix `--remote`.