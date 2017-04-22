javac Plugins with Pants
========================

For Java versions 8 and higher, the Java compiler, javac, has a 
[plugin](https://docs.oracle.com/javase/8/docs/jdk/api/javac/tree/com/sun/source/util/Plugin.html) mechanism.

Plugins allow you to hook into the compiler while it's running, to perform various
tasks such as custom error checking, code analysis and so on.

Pants supports both building and using javac plugins.

Building javac plugins
----------------------

javac plugins are specified using a `javac_plugin` target:

```
javac_plugin(
  name = 'plugin',
  plugin = 'simple_javac_plugin',
  sources = ['SimpleJavacPlugin.java'],
  dependencies = [],
  classname = 'org.pantsbuild.example.javac.plugin.SimpleJavacPlugin',
  scope='compile',
)
```

A javac plugin target has the same fields as a `java_library` target, 
plus two extra:

- `classname`: The name of the `Plugin` implementation class. Required.
- `plugin`: The logical name of the plugin, as returned by the `Plugin`
  class's `getName()` method.  If unspecified, this field defaults to 
  the target name.
  
Building a plugin target will, in addition to compiling the code, generate
the appropriate metadata into `META-INF/services/com.sun.source.util.Plugin`, so
that javac can load the plugin by name at runtime.

A plugin may be published for later consumption in any repo. It can also
be consumed (with some restrictions) from source, in the same repo.


Using javac plugins
-------------------

Plugins can be integrated in one of two ways:

- Global plugins: specified in `pants.ini` and used on all Java code.
- Per-target plugins: specified on a Java target and used only when compiling that target.

#### Global plugins

Global plugins are specified using the `javac_plugins` key in the `compile.zinc` section of `pants.ini`:

```
[compile.zinc]
javac_plugins: ['simple_javac_plugin']

```

Plugins can optionally take arguments, specified like this:

```
[compile.zinc]
javac_plugins: ['simple_javac_plugin]
javac_plugin_args: {
    'simple_javac_plugin': ['arg1', 'arg2']
  }
```


#### Per-target plugins

These are specified like this:

```
java_library(
  ...
  javac_plugins=['simple_javac_plugin'],
  javac_plugin_args={
      'simple_javac_plugin': ['arg1', 'arg2']
    }
)
```

#### Depending on plugins

In order to load a plugin, it has to be on javac's classpath. 
This can be achieved in one of two ways:

- Have targets that must be compiled with a plugin depend (directly or indirectly) 
either on the `javac_plugin` target, or on a `jar_library` pointing to a published version
of the plugin.
- Have a `javac-plugin-dep` target in `BUILD.tools`:
 
```
jar_library(name='java-plugin-dep',
            jars = [jar(org='com.foo', name='foo_plugin', rev='1.2.3')],
```

Note that, as always with `BUILD.tools`, plugin locations specified via `java-plugin-dep` 
must be published jars. They cannot be local `javac_plugin` targets.

Usually, it will make more sense to use `java-plugin-dep` with global plugins, to avoid 
laborious repetition of that dependency, and to use target dependencies for per-target plugins,
to keep the dependencies selective.  

Depending directly on the `javac_plugin` has the added advantage of allowing plugin changes
to be picked up when compiling the target that uses the plugin, with no need for an intermediate 
publishing step.

Note that, to avoid a chicken-and-egg problem, an in-repo plugin will not be used when 
compiling its own `javac_plugin` target, or any of that target's dependencies.
To use a plugin on its own code, you must publish it and consume the published plugin
via `java-plugin-dep`.


