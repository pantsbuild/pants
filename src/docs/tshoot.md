Troubleshooting
===============

Reporting Server
----------------

You can get a huge amount of useful debugging information from the detailed HTML
build reports. See  for information on how to view these reports.


Maximum Verbosity
-----------------

To output verbose debugging information to stdout set the log level to `debug`:

    :::bash
    $ ./pants -ldebug ...


<a pantsmark="washpants"> </a>

Cleaning
--------

If you suspect that your build products are in a bad state you can remove
them with `./pants clean-all`.


Stopping Nailguns
-----------------

Pants runs JVM processes in persistent daemons called "nailguns".  If you think they may
be holding bad state, you can kill them with `./pants ng-killall`.  They will
restart on the next build.

Nailgun Errors
--------------

If nailguns stop resonding, look for clues in the `stdout` and `stderr` files in
`.pants.d/ng/*/*`.


Ivy Failures
------------

You can see an Ivy invocation's detailed outputs in the [[HTML report|pants('src/docs:reporting_server')]].

You can get more verbose information from Ivy with the `--resolve-ivy-args=-debug` option.

This setting does not affect the output of the Ivy tasks used for bootstrapping tools.

Ivy Resolution
--------------

You can view Ivy's report of how it resolved each (transitive) third-party dependency:

    :::bash
    $ ./pants resolve.ivy --open examples/tests/java/org/pantsbuild/example/hello/greet


Ivy HTTP Debugging
------------------

This is a bit more involved, but gives you deeper inspection into the
network traffic between Ivy and the repo.

First, you need to add commons-httpclient to the bootstrapped Ivy
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

See [[How to Ask|pants('src/docs:howto_ask')]]
