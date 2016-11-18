# Specify a File Bundle

## Problem

You're create a `jvm_app` target definition for [[bundling|pants('src/docs/common_tasks:bundle')]] a Scala or Java project and you want to include assets such as config files or shell scripts in the bundle.

## Solution

Add a `bundles` list to your `jvm_app` target definition (more info on `jvm_app` definitions can be found in [[Define a Scala or Java Bundle Target|pants('src/docs/common_tasks:bundle')]]).

## Discussion

Here is an example `jvm_app` definition that shows different possibilities for defining file bundles (and explains them below):

    ::python
    jvm_app(name='bundle',
      bundle(fileset=rglobs('src/main/resources/*')), # 1
      bundle(fileset=globs('config/*') - globs('*.xml'), # 2
      bundle(relative_to='src', fileset=globs('src/scripts/*.sh')) # 3
    )


1. The `rglobs` definition will recursively include all files in the `src/main/resources` directory, *including all sub-directories*. More info can be found in [[Use globs and rglobs to group files|pants('src/docs/common_tasks:globs')]].
2. All files in the `config` directory are included except any `.xml` files.
3. All `.sh` files in the `src/scripts` directory will be included. The `relative_to` effectively strips away the specified directory, in this case `src`, which means that all files in `src/scripts` would end up in the root of the bundle. If you specified `relative_to='src/scripts'` instead, for example, all files would end up in the root directory.

## See Also

* [[Create a Bundled zip or Other Archive|pants('src/docs/common_tasks:bundle')]]
* [[Use globs and rglobs to Group Files|pants('src/docs/common_tasks:globs')]]
