Migrating from old pants (Nov. 2010 - Mar. 2012) to pants.new requires
some BUILD file edits and new targets to support old pants behaviors.
The migration steps are outlined below.

[TOC]

## Migrate targets with fake sources:

The old pants ant backend required each target that accepted sources
to list at least one source file even if the file did not exist.
This led to a common hack that looks like this:

    :::python
    java_library(name='hack',
      sources=['__hack_file_does_not_exist__'],
      # rest elided
    )

In pants.new sources must actually exist, so when a target has no
sources an empty list should be used:

    :::python
    java_library(name='hack',
      sources=[],
      # rest elided
    )

## Migrate targets used with dist, bundle and zip:

Old pants mixed 2 notions into library targets that are now broken out.
In old pants, a jvm library target would accept a buildflags list and
these flags would be added to the ant command line turning on certain
behavior.  Amongst the controlled behaviors were packaging of a target
into a deployable package.  3 varieties of package were supported:

 * self contained jar
 * a bundle of files under a chroot
 * a zipped bundle

In pants.new the same three packaging options remain, but they are now
enabled via 2 new target types and 2 goals:

### Self contained jars (deployjars)

These jars have all the classfiles and resource files needed to run a
main contained within them.  They also optionally have a Main-Class
manifest attribute to enable launching with `java -jar`.  To create
one to replace a pre-existing target with buildflags:

    :::python
    scala_library(name='main',
      sources=globs('*.scala'),
      dependencies=[],
      deployjar=True,
      buildflags=[
        '-Dproject.dist.name=runner',
        '-Djar.main.class=com.twitter.osprey.RunnerMain'
      ]
    )

You'd add a new jvm_binary target:

    :::python
    jvm_binary(name='main_deploy',
      basename='runner',
      main='com.twitter.osprey.RunnerMain',
      dependencies=[pants(':main')]
    )

The jvm_binary target effectively extracts the information needed to
create an executable jar from the buildflags into its arguments.  By
default the jar produced has the same name as the target, but if
basename is supplied this is used instead.  Once your project no longer
uses old pants `dist` to create its deploy jars you can delete the
buildflags argument to your deployjar libraries.

To build the deployjar you execute the pants.new binary goal:

    ./pants goal binary src/java/com/twitter/osprey:main_deploy \
      --binary-deployjar -v

The jar will be deposited to `dist/runner.jar` in this case and in
this will be logged to the console.


### Bundles and Zips

These are used when you have auxiliary files that you app needs to run
that aren't contained as resource files in your jar.  Common examples
of auxiliary files include control scripts and configuration files. A
bundle is the central concept here and is simply a directory to lay
out your application files in.  For example:

    dist/runner-bundle/
      config/
        common.conf
        runner.conf
      data/
        stopwords.txt
      libs/
        c3p0-c3p0-0.9.1.2.jar
        org.apache.mesos-mesos-0.0.1-98.jar
      scripts/
        start.sh
        stop.sh
      runner.jar

To create a bundle like this in old pants you'd need to use buildflags
that pointed to the directories containing the extra files to bundle
in along with your jar and its supporting libs:

    :::python
    java_library(name='main',
      sources=globs('*.java'),
      dependencies=[],
      buildflags=[
        '-Dproject.dist.name=runner',
        '-Djar.main.class=com.twitter.osprey.RunnerMain',
        '-Dproject.dist.dir=osprey/runner',
        '-Dproject.dist.dir.additional=osprey/common,osprey/data',
      ]
    )

Where there was a top-level layout in the project of:

    osprey/
      common/
        config/
          common.conf
      data/
        stopwords.txt
      runner/
        config/
          runner.conf
        scripts/
          start.sh
          stop.sh

To create the same bundle in pants.new you need to add a jvm_app
target that defines the bundle files and points to a jvm_binary to
include.  The most natural spot for the target is in your pre-existing
top-level project directory. Note that all files bundled must
be under the top-level project directory. In `osprey/BUILD` you'd add:

    :::python
    jvm_app(name='runner-app',
      basename='runner',
      binary = pants('src/java/com/twitter/osprey:main_deploy'),
      bundles = [
        bundle().add(rglobs('data/*'))
        bundle(relative_to='common').add(rglobs('common/*')),
        bundle(relative_to='runner').add(rglobs('runner/*')),
      ]
    )

To build the bundle you execute the pants.new bundle goal:

    ./pants goal bundle osprey:runner-app -v

The bundle will be created in `dist/runner-bundle/` in this case.  To
create a zip or other archive of the bundle, just use the
`--bundle-archive` flag and select from one of tar, tgz, tbz2 or zip:

    ./pants goal bundle osprey:runner-app -v --bundle-archive=tgz

The archive will be deposited to `dist/runner.tar.gz` in this case and in
this will be logged to the console.

**Note** that in pants.new the archives preserve permission bits such
that you no longer need to chmod bundled scripts after unpacking the
generated bundle archives.
