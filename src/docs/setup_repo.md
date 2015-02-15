Set up Your Source Tree for Pants
=================================

**As of September 2014, this much more complex than it should be.**
**The Pants community is actively working to simplify it.**
If you're setting up the Pants build tool to work in your source tree, you need to
configure Pants' behavior. (Once it's set up, most folks should be able
[[to use Pants as normal|pants('src/docs:first_concepts')]]
and not worry about these things.)

Configuring with `pants.ini`
----------------------------

Pants Build is very configurable. Your source tree's top-level directory
should contain a `pants.ini` file that sets many, many options. You can
modify a broad range of settings here, including specific binaries to
use in your toolchain, arguments to pass to tools, etc.

These files are formatted as [Python config
files](http://docs.python.org/install/index.html#inst-config-syntax),
parsed by
[ConfigParser](http://docs.python.org/library/configparser.html). Thus,
they look something like:

    :::ini
    [section]
    setting1: value1
    setting2: value2

The `[DEFAULT]` section is special: its values are available in other
sections. It's thus handy for defining values that will be used in
several contexts, as in these excerpts that define/use `thrift_workdir`:

    :::ini
    [DEFAULT]
    thrift_workdir: %(pants_workdir)s/thrift

    [thrift-gen]
    workdir: %(thrift_workdir)s

    [java-compile]
    args: [
      '-C-Tnowarnprefixes', '-C%(thrift_workdir)s',
    ]

It's also handy for defining values that are used in several contexts,
since these values will be available in all those contexts. The code
that combines DEFAULT values with others is in Pants'
[base/config.py](https://github.com/pantsbuild/pants/blob/master/src/python/pants/base/config.py).

Configure Pants' own Runtime Dependencies
-----------------------------------------

Pants calls out to other tools. E.g., it uses `jmake` for part of Java compilation.
Some special files in your workspace specify versions of these to fetch.
When setting up your Pants repo, you want to copy these files over from a working Pants
repo and perhaps change some version numbers to fit your situation.

**JVM** `BUILD.tools` has JVM dependencies. For example, when Pants fetches `jmake`, it looks in
`BUILD.tools` for that target:

!inc[start-at=jmake&end-before=java](../../BUILD.tools)

**Python** `build-support/python/pants.requirements.txt` has Pants' runtime Python requirements,
expressed as a `requirements.txt` file.

Configure Code Layout with `source_root`, `maven_layout`
--------------------------------------------------------

Maybe someday all the world's programmers will agree on the one true
directory structure for source code. Until then, you'll want some
<a pantsref="bdict_source_root">`source_root`</a>
rules to specify which directories hold your code. A
typical programming language has a notion of *base paths* for imports;
you configure pants to tell it those base paths.

If your project's source tree is laid out for Maven, there's a shortcut
function
<a pantsref="bdict_maven_layout">`maven_layout`</a>
that configures source roots for Maven's expected
source code tree structure. See
[`testprojects/maven_layout`](https://github.com/pantsbuild/pants/tree/master/testprojects/maven_layout)
for examples of using this style source tree.

### Organized by Language

If your top-level `BUILD` file is `top/BUILD` and your main Java code is
in `top/src/java/com/foo/` and your Java tests are in
`top/src/javatest/com/foo/`, then your top-level `BUILD` file might look
like:

    :::python
    # top/BUILD
    source_root('src/java')
    source_root('src/javatest')
    ...

Pants can optionally enforce that only certain target types are allowed
under each source root:

    :::python
    # top/BUILD
    source_root('src/java', annotation_processor, doc, jvm_binary, java_library, page)
    source_root('src/javatest', doc, java_library, java_tests, page)
    ...

### Organized by Project

If your top-level `BUILD` file is `top/BUILD` and the Java code for your
Theodore and Hank projects live in `top/theodore/src/java/com/foo/`,
then your top-level `BUILD` file might not contain any `source_root`
statements. Instead, `theodore/BUILD` and `hank/BUILD` might look like:

    :::python
    # top/(project)/BUILD
    source_root('src/java')
    source_root('src/javatest')
    ...

Or:

    :::python
    # top/(project)/BUILD
    source_root('src/java', annotation_processor, doc, jvm_binary, java_library, page)
    source_root('src/javatest', doc, java_library, java_tests, page)
    ...

Setting up `BUILD` files
------------------------

Pants is well-suited to large multi-project workspaces. You probably have a lot of code
organized in a big directory tree. [[The usual BUILD file advice|pants('src/docs:build_files')]]
applies here.

<a pantsmark="setup_mvn2pants"> </a>

**If you're converting a `mvn`-built workspace to use Pants**, you can get a head start by using
information from your `pom.xml` files. The [`mvn2pants`](https://github.com/ericzundel/mvn2pants)
shows some scripts that convert `pom.xml` files into `BUILD` files; Square wrote and used these
to convert some projects. This can get you up and running with Pants faster. Careful, though:
Maven projects tend to be "coarser-grained" than Pants projects. Once you have things working,
you'll probably want to replace the big automatically-generated targets with things that follow
the 1:1:1 rule.

`BUILD.*` and environment-specific config
-----------------------------------------

When we say `BUILD` files are named `BUILD`, we really mean `BUILD` or <tt>BUILD.*something*</tt>.
If you have some rules that make sense for folks in one environment but not others, you might put
them into a separate BUILD file named <tt>BUILD.*something*</tt>. For example, you might have
some `BUILD` config that you'd like to ship with your open-source code but some other parts to
keep internal. You can put open-source things in `BUILD.oss` and internal things in
`BUILD.internal`. Pants "sees" both of these. When shipping open-source code, you can hold back
the `BUILD.internal` file.

Configure JVM Artifact Publishing
---------------------------------

Pants uses `ivy` to publish artifacts. To specify where it should publish those artifacts,
bring over a working `build-support/ivy/ivysettings.xml` file from a working Pants workspace
and tweak to fit your situation. You can change the location of this file in `pants.ini`:

    :::ini
    [ivy]
    ivy_settings: some/other/path/ivysettings.xml

If the `PANTS_IVY_SETTINGS_XML` environment variable is defined, Pants uses that value instead
of the one in `pants.ini`.

Integrate New Tools via a Pants Plugin
--------------------------------------

Pants knows how to build many things, but maybe you need it to learn a new tool.
Maybe your organization has a custom linter, a custom code generator, or some other custom tool.
Maybe your organization uses a tool that, while not custom, has not yet been integrated with Pants.

-   If your organization has some custom tools to integrate, set up a
    [[Pants plugin|pants('src/python/pants/docs:howto_plugin')]].
-   If you want to integrate with a not-custom tool, you still want to
    set up a Pants plugin (or perhaps add abilities to an existing
    plugin), but it might make sense to
    [[get your changes in upstream|pants('src/python/pants/docs:howto_contribute')]].

`BUILD.*` in the source tree for special targets
------------------------------------------------

If you distribute code to different organizations, you might want to
expose some targets to one organization but not to another. You can do
this by defining those targets in a `BUILD.*` file. You can give that
file to some people and not give it to others. This code will be
processed by people invoking pants on this directory only if they have
the file.

For example, you might work at the Foo Corporation, which maintains a
fleet of machines to run big test jobs. You might define a humungous
test job as a convenient way to send many many tests to the fleet:

    :::python
    # src/javatest/com/foo/BUILD.foo

    # many-many test: Run this on the fleet, not your workstation
    # (unless you want to wait a few hours for results)
    junit_tests(name='many-many',
    dependencies = [
      'bar:all',
      'baz:all',
      'garply:all',
    ])

If you don't want to make this test definition available to the public
(lest they complain about how long it takes), you might put this in a
BUILD.foo file and hold back this file when mirroring for the public
repository.

<a pantsmark="setup_publish"></a>

Enabling Pants Publish
----------------------

Pants can ease [["publishing"|pants('src/docs:publish')]]: uploading versioned compiled artifacts.
There are some special things to set up to enable and customize publishing.

### Tell Pants about your Artifact Repository

To tell Pants which artifact repository to publish to, [[Create a
plugin|pants('src/python/pants/docs:howto_plugin')]] if you haven't already. Register it with Pants.

In the plugin, define and register at least one `Repository` object in a `BUILD` file alias as
shown in
[`src/python/internal_backend/repositories/register.py`](https://github.com/pantsbuild/pants/blob/master/src/python/internal_backend/repositories/register.py).

`BUILD` targets can use this Repository's alias as the `repo` parameter to an <a
pantsref="bdict_artifact">`artifact`</a>. For example,
[examples/src/java/com/pants/examples/hello/greet/BUILD](https://github.com/pantsbuild/pants/blob/master/examples/src/java/com/pants/examples/hello/greet/BUILD)
refers to the `public` repository defined above. (Notice it's a Python object, not a string.)

!inc[start-at=java_library](../../examples/src/java/com/pants/examples/hello/greet/BUILD)

If you get an error that the repo name (here, `public`) isn't defined, your plugin didn't register
with Pants successfully. Make sure you bootstrap Pants in a way that loads your `register.py`.

In your config file (usually `pants.ini`), set up a `[jar-publish]` section. In that section,
create a `dict` called `repos`. It should contain a section for each `Repository` object that you
defined in your plugin:

    repos: {
      'public': {  # must match the name of the `Repository` object that you defined in your plugin.
        'resolver': 'maven.example.com', # must match hostname in ~/.netrc and the <url> parameter
                                         # in your custom ivysettings.xml.
        'confs': ['default', 'sources', 'docs', 'changelog'],
        'auth': 'build-support:netrc',   # Pants spec to a 'credentials()' object.
        'help': 'Configure your ~/.netrc for maven.example.com access.'
      },
      'testing': {
        'resolver': 'artifactory.example.com',
        'confs': ['default', 'sources', 'docs', 'changelog'],
        'auth': 'build-support:netrc',
        'help': 'Configure your ~/.netrc for artifactory.example.com access.'
      },
    }

If your repository requires authentication, add a `~/.netrc` file. Here is a sample file, that
matches the `repos` specified above:

    machine maven.example.com
      login someuser
      password password123

    machine artifactory.example.com
      login someuser
      password someotherpassword123

And place the following in a `BUILD` file somewhere in your repository (`build-support/BUILD` is a
good place, and is used in the example above):

    netrc = netrc()

    credentials(
      name = 'netrc',
      username=netrc.getusername,
      password=netrc.getpassword)

Next, tell Ivy how to publish to your repository. Add a new `ivysettings.xml` file to your repo
(for example: '`build-support/ivy/ivysettings_for_publishing.xml`'). Here is an example file to get
you started:

		<?xml version="1.0"?>
		<!-- pants.ini forces this settings file to be loaded by Ivy, but only at
		     publish time. -->

		<ivysettings>
		  <settings defaultResolver="chain-repos"/>

		  <include file="${ivy.settings.dir}/ivysettings.xml"/>

		  <credentials host="artifactory.example.com"
		               realm="Artifactory Realm"
                   <!-- These values come from a credentials() object, which is fed by '~/.netrc'.
                        There must be a '~/.netrc' machine entry which matches a resolver in the
                        "repos" object in 'pants.ini', which also matches the 'host' in this XML
                        block. -->
		               username="${login}"
		               passwd="${password}"/>

		  <resolvers>
		    <chain name="chain-repos" returnFirst="true">
		      <_remote_resolvers name="remote-repos"/>
		    </chain>

		    <url name="artifactory.example.com" m2compatible="true">
		      <artifact pattern="https://artifactory.example.com/libs-releases-local/[organization]/[module]/[revision]/[module]-[revision](-[classifier]).[ext]"/>
		    </url>
		  </resolvers>
		</ivysettings>

With this file in place, add a `[publish]` section to `pants.ini`, and tell pants to use
the custom Ivy settings when publishing:

    ivy_settings: %(pants_supportdir)s/ivy/ivysettings_for_publishing.xml

<a pantsmark="setup_publish_restrict_branch"> </a>

### Restricting Publish to "Release Branch"

Your organization might have a notion of a special "release branch": you want [[artifact
publishing|pants('src/docs:publish')]] to happen on this source control branch, which you maintain
extra-carefully. You can set this branch using the `restrict_push_branches` option of the
`[jar-publish]` section of your config file (usually `pants.ini`).

### Task to Publish "Extra" Artifacts

Pants supports "publish plugins", which allow end-users to add additional, arbitrary files to be
published along with the primary artifact. For example, let's say that along with publishing your
jar full of class files, you would also like to publish a companion file that contains some
metadata -- code coverage info, source git repository, java version that created the jar, etc. By
[[developing a task|pants('src/python/pants/docs:dev_tasks')]] in a
[[plugin|pants('src/python/pants/docs:howto_plugin')]], you give Pants a new ability. [[Develop a
Task to Publish "Extra" Artifacts|pants('src/python/pants/docs:dev_tasks_publish_extras')]] to find
out how to develop a special Task to include "extra" data with published artifacts.

Outside Caches
--------------

You can tell Pants to use outside caches when building. Pants automatically caches much of its
work in its working directory. But you can tell it to use (and generate) pre-built things in
another directory or a remote RESTful server. E.g, to use a shared server for cached builds,
and having set up such a server, set `..._caches` options in `pants.ini`:

    [DEFAULT]
    read_artifact_caches: ['https://myserver.co/pantscache']
    write_artifact_caches: ['https://myserver.co/pantscache']

When building, Pants first tries to read built things from places in `read_artifact_caches`.
If it builds something, it caches those built things in places in  `write_artifact_caches`.
(It's handy that these are separate settings; if members of your organization can install wacky
tools on their laptops, you might not want their builds to write to the cache, but would want
them to be able to read from it.)

Valid option values include

* `[ 'https://myserver.co/pcache' ]` RESTful server URL
* `[ '/tmp/pantscache' ]` local machine file location
* `[ 'https://myserver.us/pcache|https://myserver.bf/pcache' ]` pipe-separated list of URLs--Pants pings each and uses fastest
* `[ '/tmp/pantscache', 'https://myserver.co/pcache' ]` try local fs first, then remote server

For a list of allowed values see the `create_artifact_cache` docstring in
[`cache_setup.py`](https://github.com/pantsbuild/pants/blob/master/src/python/pants/cache/cache_setup.py)

To make a cache server, you need to write it. It's basically a RESTful server that can handle
`GET`, `HEAD`, `PUT`, and `DELETE` requests on big binary blobs. If you implement this via `nginx`,
then the `dav_methods PUT DELETE;` directive is good. (You might want to add some
organization-specific business logic on top of that. E.g., if you're worried about the
"wacky laptop tools" case, your server should only accept artifacts from known-legitimate
machines.)
When *reading* from a cache server, Pants tries to `GET` an URL at some path under the server URL;
respond with 404 if there's nothing there, 200 if there is.
When *writing* to a cache server, Pants first tries a `HEAD` request to see if the file's already
there; respond with 404 if there's nothing there, 200 if there is. If Pants gets a 404, it will
then try a `PUT` request; store the file it sends.
If the user's `.netrc` has authentication information for the cache server[s], Pants will use it.
(Thus, if only some users with known-good setups should be able to write to the cache, you might
find it handy to use `.netrc` to authenticate those users.)