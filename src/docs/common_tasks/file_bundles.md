# Specify a File Bundle

## Problem

You have created a `jvm_app` target definition for [[bundling|pants('src/docs/common_tasks:bundle')]] a Scala or Java project and you want to include assets such as config files or shell scripts in the bundle.

## Solution

Add a `bundles` list to your `jvm_app` target definition (more info on `jvm_app` definitions can be found in [[Define a Scala or Java Bundle Target|pants('src/docs/common_tasks:bundle')]]).

## Discussion

Here is an example `jvm_app` definition that shows different possibilities for defining file bundles (and explains them below):

    ::python
    jvm_app(
      name='bundle',
      bundle(fileset=['src/main/resources/**/*')), # 1
      bundle(fileset=['config/*', '!*.xml']), # 2
      bundle(fileset=['src/scripts/*.sh'], relative_to='src') # 3
    )


1. All files in the `src/main/resources` directory are recursively included.
2. All files in the `config` directory are included, except any `.xml` files.
3. All `.sh` files in the `src/scripts` directory will be included. The `relative_to` effectively strips away the specified directory, in this case `src`, which means that all files in `src/scripts` would end up in the root of the bundle. If you specified `relative_to='src/scripts'` instead, for example, all files would end up in the root directory.

## See Also

* [[Create a Bundled zip or Other Archive|pants('src/docs/common_tasks:bundle')]]
* [[Use globs to group files|pants('src/docs/common_tasks:globs')]]
