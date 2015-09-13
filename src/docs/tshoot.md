Troubleshooting
===============

Sometimes Pants doesn't do what you hoped.
Pants has good error messages for common errors, but
some messages are not so useful.
(Please report these when you see them.
We want Pants' error messages to be useful.)
Sometimes Pants just plain doesn't work. (Please report these, too.) The
following workarounds can get you up and running again.

<a pantsmark="tshoot_verbosity"> </a>

Pants Run Log
------------

The console output you get when running pants is also logged under the
pants workdir.  An HTML formatted version of the log from previous
runs will be stored under `.pants.d/reports` and the most recent run
is in `.pants.d/reports/latest`.  Additional information from the run
will be logged under `.pants.d/runs`.

An easy way to view this output is to use the reporting server.

```bash
$ ./pants server --open
Launching server with pid 6991 at http://localhost:49266
```

Your browser should open up automatically to the main reporting server
page, or you can use the specified URL.  On this page you will be able to
browse through all of the runs since the last call to `./pants
clean-all`.

![image](images/report-server-page.png)

When viewed under the reporting server, there is additional
information available such as:

- Performance timings
- Links to source code
- Details of the command line and stdout/stderr from running tasks
- Details on which targets are being operated on
- Artifact cache usage information (if artifact caching is enabled)


Maximum Verbosity
-----------------

To run a Pants command so that it outputs much much more information to
stdout, you can set some environment variables and pass the `-ldebug`
flag (along with the parameters you meant to pass):

    :::bash
    $ PEX_VERBOSE=5 ./pants -ldebug ...

This can be especially useful if you're trying to figure out what Pants
was "looking at" when it crashed.

<a pantsmark="washpants"> </a>

Scrub the Environment
---------------------

If you suspect that Pants has cached some corrupt data somewhere, but
don't want to track down exactly what, you can reset your state:

-   **Clean many cached files:** `./build-support/python/clean.sh`
-   **Clean more cached files:** If your source tree lives under source
    control, use your source control tool to clean up more files. For
    example with `git`, you might do something like:

        :::bash
        $ git status  # look for untracked files
        $ git add path/to/file1 path/to/file2  # preserve untracked files you don't want deleted
        $ git clean -fdx  # delete all untracked files

-   **Stop background processes:**

        :::bash
        $ ./pants ng-killall --everywhere

Nailgun 10 seconds
------------------

If Pants fails with a stack trace that ends with something like

    :::bash
    File "pants/tasks/nailgun_task.py", line 255, in _spawn_nailgun_server
    File "pants/tasks/nailgun_task.py", line 226, in _await_nailgun_server
    pants.java.nailgun_client.NailgunError: Failed to read ng output after 10 seconds...

The exception might show some command args.

Pants uses a program called nailgun to run some JVM jobs. Pants runs
nailgun as a server in the background and then sends requests to it. If
nailgun runs into problems, it might not respond.

To debug this, look in `.pants.d/ng/*/*`: these files should be named
`stdout` and `stderr`.

One typical cause behind this symptom: if you removed your machine's Ivy
cache, Pants may try to use symbolic links to files that have gone away.
To recover from this, <a pantsref="washpants">scrub the environment</a>.

Troubleshooting Ivy download failures
---------------------------------

Sometimes Ivy will refuse to download a particular artifact.   When
the ivy step fails, pants echos the ivy output to the console.
You can go back and look at previous runs or get more insight
by starting the reporting server with `./pants server --open` and
looking at the report for the failed run.

* If you missed it the first time, you can open up the `[ivy-resolve]`
or one of the `bootstrap` steps in the output and check the stderr
and stdout links.

* Using a web browser, navigate to the URLs that are failing the Ivy
download and see if you can download the artifact manually.
If you are downloading through a proxy you may find a configuration
issue or an artifact missing from the proxy's cache.

There are other options you can use to enable more debugging in
Ivy if you think you need it.

### Add the `-debug` flag to the ivy tool

You can get more debugging in the ivy resolve task by passing the
`-debug` argument when ivy is invoked:

```ini
[resolve.ivy]
args: [ "-debug" ]
```

This makes the ivy output much more verbose.  You can see the output in the
pants reporting server window for stderr and stdout for the
`[ivy-resolve]` step.  This setting does not affect the output of the
bootstrapping task for downloading tools.

### Turn on HTTP header debugging in Ivy

This is a bit more involved, but gives you deeper inspection into the
network traffic between Ivy and the repo.

First, you need to add commons-httpclient to the bootstrapped ivy
installation by creating a custom ivy.xml.  You can
start with the org.apache.ivy xml file under the ivy cache and just
add a dependency for commons-httpclient as follows:

```xml
$ cat ./ivy-with-commons-httpclient.xml
<ivy-module version="2.0">
        <info organisation="org.apache.ivy" module="ivy-caller" />
        <configurations defaultconf="default" />
        <dependencies>
                <dependency org="org.apache.ivy" name="ivy" rev="2.3.0" />
                <dependency org="commons-httpclient" name="commons-httpclient" rev="3.0" />
        </dependencies>
</ivy-module>
```

Then, reference your modified ivy profile from pants.ini and flip on
some extra logging in the commons-httpclient by setting some system properties:

```ini
[ivy]
ivy_profile: ivy-with-commons-httpclient.xml

# Enable httpcommons debugging when bootstrapping tools
[bootstrap.bootstrap-jvm-tools]
jvm_options: [
    "-Dorg.apache.commons.logging.Log=org.apache.commons.logging.impl.SimpleLog",
    "-Dorg.apache.commons.logging.simplelog.showdatetime=true",
    "-Dorg.apache.commons.logging.simplelog.log.httpclient.wire.header=debug",
    "-Dorg.apache.commons.logging.simplelog.log.org.apache.commons.httpclient=debug",
  ]

# Enable httpcommons debugging when resolving 3rdparty libraries
[resolve.ivy]
jvm_options: [
    "-Dorg.apache.commons.logging.Log=org.apache.commons.logging.impl.SimpleLog",
    "-Dorg.apache.commons.logging.simplelog.showdatetime=true",
    "-Dorg.apache.commons.logging.simplelog.log.httpclient.wire.header=debug",
    "-Dorg.apache.commons.logging.simplelog.log.org.apache.commons.httpclient=debug",
	]
```

You'll be able to see the output in the pants reporting server output
by expanding the `stderr` nodes.

```
2015/03/12 03:55:56:456 PDT [DEBUG] HttpConnection - -Open connection to repo1.maven.org:443
2015/03/12 03:55:57:144 PDT [DEBUG] header - ->> "HEAD /maven2/org/antlr/antlr4/4.1/antlr4-4.1.pom HTTP/1.1[\r][\n]"
2015/03/12 03:55:57:144 PDT [DEBUG] HttpMethodBase - -Adding Host request header
2015/03/12 03:55:57:149 PDT [DEBUG] header - ->> "User-Agent: Apache Ivy/2.3.0[\r][\n]"
2015/03/12 03:55:57:150 PDT [DEBUG] header - ->> "Host: repo1.maven.org[\r][\n]"
2015/03/12 03:55:57:150 PDT [DEBUG] header - ->> "[\r][\n]"
2015/03/12 03:55:57:448 PDT [DEBUG] header - -<< "HTTP/1.1 200 OK[\r][\n]"
2015/03/12 03:55:57:450 PDT [DEBUG] header - -<< "Date: Thu, 12 Mar 2015 10:55:57 GMT[\r][\n]"
2015/03/12 03:55:57:450 PDT [DEBUG] header - -<< "Server: nginx[\r][\n]"
2015/03/12 03:55:57:450 PDT [DEBUG] header - -<< "Content-Type: text/xml[\r][\n]"
2015/03/12 03:55:57:450 PDT [DEBUG] header - -<< "Content-Length: 4800[\r][\n]"
2015/03/12 03:55:57:450 PDT [DEBUG] header - -<< "Last-Modified: Fri, 05 Jul 2013 21:35:45 GMT[\r][\n]"
2015/03/12 03:55:57:450 PDT [DEBUG] header - -<< "ETag: "51d73c31-12c0"[\r][\n]"
2015/03/12 03:55:57:450 PDT [DEBUG] header - -<< "Accept-Ranges: bytes[\r][\n]"
2015/03/12 03:55:57:450 PDT [DEBUG] header - -<< "Accept-Ranges: bytes[\r][\n]"
2015/03/12 03:55:57:450 PDT [DEBUG] header - -<< "Via: 1.1 varnish[\r][\n]"
2015/03/12 03:55:57:451 PDT [DEBUG] header - -<< "Accept-Ranges: bytes[\r][\n]"
2015/03/12 03:55:57:451 PDT [DEBUG] header - -<< "Via: 1.1 varnish[\r][\n]"
2015/03/12 03:55:57:451 PDT [DEBUG] header - -<< "X-Served-By: cache-iad2127-IAD, cache-atl6233-ATL[\r][\n]"
2015/03/12 03:55:57:451 PDT [DEBUG] header - -<< "X-Cache: MISS, MISS[\r][\n]"
2015/03/12 03:55:57:451 PDT [DEBUG] header - -<< "X-Cache-Hits: 0, 0[\r][\n]"
2015/03/12 03:55:57:451 PDT [DEBUG] header - -<< "X-Timer: S1426157757.333469,VS0,VE36[\r][\n]"
```


Questions, Issues, Bug Reports
------------------------------

See [[How to Ask|pants('src/python/pants/docs:howto_ask')]]
