scalac Plugins with Pants
=========================

The Scala compiler, scalac, has a plugin mechanism.

Plugins allow you to hook into the compiler while it's running, to perform various
tasks such as custom error checking, code analysis and so on.

Pants supports both building and using scalac plugins.

Building scalac plugins
-----------------------

scalac plugins are specified using a `scalac_plugin` target:

```
scalac_plugin(
  name = 'plugin',
  plugin = 'simple_scalac_plugin',
  sources = ['SimpleScalacPlugin.scala'],
  dependencies = [],
  classname = 'org.pantsbuild.example.scalac.plugin.SimpleScalacPlugin',
  scope='compile',
)
```

A scalac plugin target has the same fields as a `scala_library` target, 
plus two extra:

- `classname`: The name of the `Plugin` implementation class. Required.
- `plugin`: The logical name of the plugin, as returned by the `Plugin`
  class's `getName()` method.  If unspecified, this field defaults to 
  the target name.
  
Building a plugin target will, in addition to compiling the code, generate
the appropriate metadata into `scalac-plugin.xml`, so
that scalac can load the plugin by name at runtime.

A plugin may be published for later consumption in any repo. It can also
be consumed (with some restrictions) from source, in the same repo.


Using scalac plugins
--------------------

Plugins can be integrated in one of two ways:

- Global plugins: specified in `pants.ini` and used on all Scala code.
- Per-target plugins: specified on a Scala target and used only when compiling that target.

#### Global plugins

Global plugins are specified using the `scalac_plugins` key in the `compile.zinc` section of `pants.ini`:

```
[compile.zinc]
scalac_plugins: ['simple_scalac_plugin']

```

Plugins can optionally take arguments, specified like this:

```
[compile.zinc]
scalac_plugins: ['simple_scalac_plugin]
scalac_plugin_args: {
    'simple_scalac_plugin': ['arg1', 'arg2']
  }
```


#### Per-target plugins

These are specified like this:

```
scala_library(
  ...
  scalac_plugins=['simple_scalac_plugin'],
  scalac_plugin_args={
      'simple_scalac_plugin': ['arg1', 'arg2']
    }
)
```

#### Depending on plugins

In order to load a plugin, it has to be on scalac's classpath. 
This can be achieved in one of two ways:

- Have targets that must be compiled with a plugin depend (directly or indirectly) 
either on the `scalac_plugin` target, or on a `jar_library` pointing to a published version
of the plugin.
- Have a `scalac-plugin-dep` target in `BUILD.tools`:

```
jar_library(name='scalac-plugin-dep',
            jars = [jar(org='com.foo', name='foo_plugin', rev='1.2.3')],
```

Note that, as always with `BUILD.tools`, plugin locations specified via `scala-plugin-dep` 
must be published jars. They cannot be local `scalac_plugin` targets.

Usually, it will make more sense to use `scala-plugin-dep` with global plugins, to avoid 
laborious repetition of that dependency, and to use target dependencies for per-target plugins,
to keep the dependencies selective.  

Depending directly on the `scalac_plugin` has the added advantage of allowing plugin changes
to be picked up when compiling the target that uses the plugin, with no need for an intermediate 
publishing step.

Note that, to avoid a chicken-and-egg problem, an in-repo plugin will not be used when 
compiling its own `scalac_plugin` target, or any of that target's dependencies.
To use a plugin on its own code, you must publish it and consume the published plugin
via `scala-plugin-dep`.


