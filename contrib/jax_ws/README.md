# Pants plugin for JAX-WS

The JAX-WS plugin for Pants uses the [wsimport tool](https://jax-ws.java.net/jax-ws-ea3/docs/wsimport.html) to generate web service client stubs from a 
Web Services Description Language (WSDL) file for calling a JAX-WS web service.

## Installation

JAX-WS support is provided by a plugin distributed to [pypi]
(https://pypi.python.org/pypi/pantsbuild.pants.contrib.jax_ws).
Assuming you have already [installed pants](http://www.pantsbuild.org/install.html), you'll need to
add the JAX-WS plugin in your `pants.ini`, like so:
```ini
[GLOBAL]
pants_version: 1.0.0

plugins: [
    'pantsbuild.pants.contrib.jax_ws==%(pants_version)s',
  ]
```

## Target Example

You can now add a `jax_ws_library` target definition to your BUILD file
```python
jax_ws_library(name='hello-service',
  sources = [
    'HelloService.wsdl',
  ],
  dependencies = [],
)
```

and service stubs will be generated for you when you `gen` this target
```bash
$ ./pants gen myproject/src/main/jax_ws:hello-service
```

Common jvm_options for jax-rs can be included in your pants.ini file
```ini
[gen.jax-ws]
jvm_options: [
    '-Djavax.xml.accessExternalSchema=all'
  ]
```

## Options

The `jax_ws_library` target definition has the following options
```python
jax_ws_library(name='hello-service',
  sources = [
    # wsdl files
  ],
  xjc_args=[
    # XJC-specific arguments
  ],
  extra_args=[
    # Additional arguments for wsimport
  ],
)
```
