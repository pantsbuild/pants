# Get an Overview of Your Recent Pants Activity

## Problem

You need a list of goals that you have recently run, combined with the output of those runs.

## Solution

The `server` goal will start up a local web server that you can use to access information about your recent Pants usage:

    ::bash
    $ ./pants server
    Launching server with pid 85420 at http://localhost:57466

Set the `-o` or `--open` flag to automatically open the browser.

The UI looks like this:

<img src="images/pants-server-ui.png" width="800px">

To kill the server:

    ::bash
    $ ./pants killserver

For more info, see [[Reporting Server|pants('src/docs:reporting_server')]].

## See Also

* [[Clean Cached Artifacts|pants('src/docs/common_tasks:clean')]]
