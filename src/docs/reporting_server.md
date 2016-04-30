Reporting Server
================

Apart from the usual console logging, Pants has an HTML interface
that allows you to view past builds and drill down into the inputs and
outputs of every tool invocation.

To use this interface, first launch the reporting server:

```bash
$ ./pants server --open
Launching server with pid 6991 at http://localhost:49266
```

This will run the server and open a browser pointing to it. The report looks something like this:

![image](images/report-server-page.png)

These reports contain additional information such as:

- Performance timings
- Links to source code
- Details of the command line and stdout/stderr from running tasks
- Details on which targets are being operated on
- Artifact cache usage information
