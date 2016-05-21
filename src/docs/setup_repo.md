Setting Up Pants
================

Pants will work out of the box, at least for basic functionality. However some uses require further setup.

Source Roots
------------

Pants needs to know where the root of a source tree is, so it can correctly set up import paths,
bundle code etc.

In typical cases, Pants can deduce the source roots automatically based on naming conventions.
E.g., `src/<lang>`, `src/main/<lang>`, `test/<lang>`, `src/test/<lang>`, `3rdparty/<lang>` and so on.
However if your source roots don't conform to any of the default patterns, you can add your own
patterns.  See ` ./pants help-advanced source` for details.

`.gitignore`
------------

If you use Git as your SCM you'll want to add the following entries to your `.gitignore` file:

`.pants.d`<br>
`dist`<br>
`.pids`<br>
`.pants.workdir.file_lock`

`BUILD` files
-------------

BUILD files describe the dependency graph of your codebase.  You'll need to
[[create some|pants('src/docs:build_files')]] in order to use Pants.

<a pantsmark="setup_mvn2pants"></a>
If you're converting a `mvn`-built workspace to Pants, you can get a head start by using
information from your `pom.xml` files. The [`mvn2pants`](https://github.com/ericzundel/mvn2pants)
repo demonstrates some scripts that convert `pom.xml` files into `BUILD` files. This can get
you up and running with Pants faster. Careful, though: Maven projects tend to be very coarse-grained.
Once you have things working, you'll probably want to break down the large Maven-style targets
into finer-grained ones.


Options
-------

Pants is very configurable and has literally hundreds of tuneable parameters, known in Pants
parlance as _options_.

Most options are  automatically set to useful defaults. However it is inevitable that sooner or
later you'll need to tweak some of them.

+ [[More details on pants options|pants('src/docs:options')]]
+ [Options reference](options_reference.html)


Tools
-----

Pants calls out to other tools for many build steps. E.g., it uses Zinc for incremental compilation
of Java and Scala code.

Pants bootstraps such tools as needed.  The default versions of these tools can be overridden
using the appropriate options. It's idiomatic, but not required, to set these options to addresses
of targets in a special BUILD file named `BUILD.tools` in the repo root.

Pants uses `Ivy` to fetch JVM-based tools.  Ivy requires an XML configuration file.
By default, pants uses the configuration that ships with Ivy,
but if you need to change Ivy settings you can specify your own in `pants.ini`:

    [ivy]
    ivy_settings: %(pants_supportdir)s/ivy/ivysettings.xml
    cache_dir: ~/.ivy2/pants

For more information on Ivy settings, see the [Ivy documentation](http://ant.apache.org/ivy/)


<a id="setup_cache"></a>

Build Cache
-----------

Pants automatically caches its work locally. But most organizations will want to set up a shared
remote build cache. To do so, set `cache` options in `pants.ini`:

    [cache]
    read_from: ['https://myserver.co/pantscache']
    write_to: ['https://myserver.co/pantscache']

Note that the read and write cache locations are separate options: you may, for example, only want
your CI machines, not individual developer builds, to populate the shared cache.

Valid option values are:

+ `[ 'https://myserver.co/pantscache' ]` RESTful server URL.
+ `[ '/tmp/pantscache' ]` local directory.
+ `[ 'https://myserver.us/pcache|https://myserver.bf/pcache' ]` pipe-separated list of URLs--Pants pings each and uses the fastest.
+ `[ '/tmp/pantscache', 'https://myserver.co/pcache' ]` try local fs first, then remote server.

For details see the `_do_create_artifact_cache` docstring in
[`cache_setup.py`](https://github.com/pantsbuild/pants/blob/master/src/python/pants/cache/cache_setup.py).

The remote server should be a RESTful server that can handle `GET`, `HEAD`, `PUT`, and `DELETE` requests
on large binary blobs. E.g., you can implement this using [Varnish](https://www.varnish-cache.org/)
in front of [nginx](https://www.nginx.com/resources/wiki/) (with `dav_methods PUT DELETE;` enabled).

When reading from a cache server, Pants tries to `GET` an URL at some path under the server URL;
your server should respond with 404 if there's nothing there, 200 if there is.

When writing to a cache server, Pants first tries a `HEAD` request to see if the file's already
there; respond with 404 if there's nothing there, 200 if there is. If Pants gets a 404, it will
then try a `PUT` request; store the file it sends.

If the user's `.netrc` has authentication information for the cache server[s], Pants will use it.
(Thus, if only some users with known-good setups should be able to write to the cache, you might
find it handy to use `.netrc` to authenticate those users.)

Uploading Timing Stats
----------------------

Pants tracks information about its performance: what it builds, how much
time various build operations take, cache hits, and more.
If you you work with a large engineering organization, you might want to
gather this information in one place, so it can inform decisions about how
to improve everybody's build times.

To upload these stats to a server for future analysis set the following option in `pants.ini`:

    :::ini
    [run-tracker]
    stats_upload_url: "http://myorg.org/pantsstats"

Pants will `POST` JSON data to that URL.  The JSON format should be self-explanatory.

Using Pants behind a firewall
-----------------------------

Pants may encounter issues running behind a firewall. Several components expect to be able to reach the Internet:

* Ivy bootstrapper
* Binary tool bootstrapping
* Ivy itself (used for tool bootstrapping and downloading external .jar files)
* Python requirements


### Configuring the Python requests library

Code in bootstrapper.py and other parts of Pants use the Python
[requests](http://docs.python-requests.org/en/latest/) library to
download resources using http or https.  The first time you may
encounter this is when Pants attempts to download an initial version
of Ivy.  If this initial download is through a proxy, the requests
library uses the `HTTP_PROXY` or `HTTPS_PROXY` environment variable to
find the proxy server.

```
export HTTP_PROXY=http://proxy.corp.example.com:123
export HTTPS_PROXY=https://proxy.corp.example.com:456
```

If Pants tries to find resources with HTTPS urls, you may see an error like:

```
Exception message: Problem fetching the ivy bootstrap jar! Problem GETing data from https://artifactserver.example.com/content/groups/public/org/apache/ivy/ivy/2.3.0/ivy-2.3.0.jar: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed (_ssl.c:581)
```

The requests library attempts to verify SSL certificates by default.
The reason it is denying the request is that it cannot find a trusted
public key for the root certificate authority presented by the server.
The requests library uses the 'certifi' library of well known
certificate authorities, if that library is installed.  If you are
using a virtualenv installation of pants, using `pip
install certifi` to add the certify package to your pants environment
might help.  You can also download a .pem bundle from the
[certifi project page](http://certifi.io/en/latest/) and set
`REQUESTS_CA_BUNDLE` as mentioned below.

If you are using hosts with a self-signed certificate, your
certificate authority will not be available in the certifi library.
You will need a `.pem` file for the local certificate authority.

You can tell the requests library about your trusted certificate
authority certificates by setting the environment variable `REQUESTS_CA_BUNDLE`.
This variable should point to a file containing trusted certificates:

```
export REQUESTS_CA_BUNDLE=/etc/certs/latest.pem
```

### Bootstrapping Ivy

Pants fetches the Ivy tool with an initial manual bootstrapping step using the Python requests library.
If you do not want to use `HTTP_PROXY` or `HTTPS_PROXY` as described above, you can re-redirect
this initial download to another URL with a setting in `pants.ini`:

    :::ini
    [ivy]
    bootstrap_jar_url: https://proxy.corp.example.com/content/groups/public/org/apache/ivy/ivy/2.3.0/ivy-2.3.0.jar

You may also encounter issues downloading this .jar file if you are using self-signed SSL certificates.
See the section on Configuring the Python requests library above.


## Nexus as proxy

If your site uses Sonatype Nexus or another reverse proxy for
artifacts, you do not need to use a separate HTTP proxy.  Contact the
reverse proxy administrator to setup a proxy for the sites listed in
`build-support/ivy/settings.xml` and `pants.ini`.  By default these
are `https://repo1.maven.org/maven2/` and `https://dl.bintray.com/pantsbuild/maven/`:

Here is an excerpt of a modified ivysettings.xml with some possible configurations:

```
<macrodef name="_remote_resolvers">
    <chain returnFirst="true">
      <ibiblio name="example-corp-maven"
               m2compatible="true"
               usepoms="true"
               root="https://nexus.example.com/content/groups/public/"/>
      <ibiblio name="maven.twttr.com-maven"
               m2compatible="true"
               usepoms="true"
               root="https://nexus.example.com/content/repositories/maven.twttr.com/"/>
  </chain>
</macrodef>
```

### Redirecting tool downloads to other servers

For the binary support tools like protoc, you will need to setup a
proxy for the `dl.bintray.com` repo, or create your own repo of build
tools:

    :::ini
    pants_support_baseurls = [
        "https://nexus.example.com/content/repositories/dl.bintray.com/pantsbuild/bin/build-support"
	  ]

### Redirecting python requirements to other servers

For python repos, you need to override the following settings in pants.ini:

    :::ini
    [python-repos]
    repos: [
        "https://pantsbuild.github.io/cheeseshop/third_party/python/dist/index.html",
        "https://pantsbuild.github.io/cheeseshop/third_party/python/index.html"
      ]

    indices: [
        "https://pypi.python.org/simple/"
      ]

