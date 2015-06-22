Develop a Task to Publish "Extra" Artifacts
===========================================

Pants supports "publish plugins", which allow end-users to add
additional, arbitrary files to be published along with the primary
artifact. For example, let's say that along with publishing your jar
full of class files, you would also like to publish a companion file
that contains some metadata -- code coverage info, source git
repository, java version that created the jar, etc. To accomplish this,
you'll first need to write a custom task, which creates any additional
files (jar or otherwise) that you would like to publish. Next, you'll
create a `publish_extras` section under `[publish.jar]` in pants.ini,
and add a key for the new product type. Your custom task will create the
extra file(s) that you want to publish, and write the path to the
products map under the key that you have defined in pants.ini. The
publishing code will loop over all keys found in pants.ini, and consult
the product map. If pants finds a file for the current key, it will
gather it up, and bundle it in with the rest of the files being
published.

An example of a custom task is supplied in the
`examples/src/python/example/pants_publish_plugin` directory. To use it,
add the following to your pants.ini:

    [publish.jar]
    publish_extras: {
        'extra_test_jar_example': {
          'override_name': '{target_provides_name}-extra_example',
          'classifier': 'classy',
          'extension': 'jar',
        },
      }

    [DEFAULT]
    backend_packages: [
        'example.pants_publish_plugin',
      ]

In the above configuration example, the string
`'extra_test_jar_example'` is a key into the product map. In this case,
the example task will add additional files for publishing to the product
map under this key. And `jar_publish.py` will examine the product map,
looking for all keys defined here, and publishing any additional files
found.

Constructing a name for your extra artifact:
--------------------------------------------

By default, pants uses the following scheme when publishing artifacts:

    [artifactId]-[version](-[classifier]).[ext]

The pants plugin publishing system allows a customization of the
artifact identifier, classifier, and file extension. To customize the
name of your extra object, you can supply some extra parameters in the
`pants.ini` file:

+   `override_name` -- allows customization of the name (`artifactId`)
    of the additional file published. Specifying a string will
    completely override the name, or include
    '`{target_provides_name}`' to tack an addition on to the
    pre-existing artifact name. Defaults to the pre-existing artifact
    name.
+   `classifier` -- the maven classifier. Can be any arbitrary string,
    or leave this unspecified for nothing.
+   `extension` -- the filename extension. Defaults to "jar".

**Note:** You must supply a non-default value for at least one of the
above parameters, otherwise your extra publish artifact won't have a
unique name. With the above config in your pants.ini, invoke pants like
this, to do a test publish:

    :::bash
    WRAPPER_SRCPATH=examples/src/python ./pants publish.jar --no-dryrun --local=~/tmp \
      examples/src/java/org/pantsbuild/example/hello/greet

Now if you examine the `/tmp` directory, you'll notice that an extra jar
has been published for the `greet` target:

    :::bash
    $ ls -1 /tmp/org/pantsbuild/example/hello-greet/0.0.1-SNAPSHOT/|grep example
    hello-greet-extra_example-0.0.1-SNAPSHOT-classy.jar
    hello-greet-extra_example-0.0.1-SNAPSHOT-classy.jar.md5
    hello-greet-extra_example-0.0.1-SNAPSHOT-classy.jar.sha1

This example task should provide a rough starting guide, and can be
tailored to suit a more specific situation.

