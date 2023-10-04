---
title: "2.2.x"
slug: "release-notes-2-2"
hidden: true
createdAt: "2020-11-25T23:17:27.178Z"
---
This release requires having a Python 3.7 or 3.8 interpreter to run Pants. Run `curl -L -o ./pants https://raw.githubusercontent.com/pantsbuild/setup/2f079cbe4fc6a1d9d87decba51f19d7689aee69e/pants` to update your ./pants script to choose the correct interpreter.

Some highlights:

- Added dependency inference for Python imports of Protobuf, along with Protobuf imports of Protobuf. See [Protobuf and gRPC](doc:protobuf).
- Pantsd will no longer restart when a run of Pants is killed (such as with `Ctrl+C`): instead, the serverside work will be canceled. This improves performance by keeping your builds warm for longer periods.
- Pants uses PEX `2.1.24`, which enables using [the new PIP resolver](https://pyfound.blogspot.com/2020/11/pip-20-3-new-resolver.html) by setting  `[python-setup] resolver_version: pip-2020-resolver`. This is expected to be the only stable release of Pants that supports _both_ resolvers without a deprecation, so give it a whirl soon!
- The `sources` field is deprecated for `pex_binary` and `python_awslambda` targets to ease dependency inference, and improve consistency. See [the change](https://github.com/pantsbuild/pants/pull/11332) for more info!

See [here](https://github.com/pantsbuild/pants/blob/master/src/python/pants/notes/2.2.x.md) for a detailed change log.