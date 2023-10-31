---
title: "Logging and dynamic output"
slug: "rules-api-logging"
excerpt: "How to add logging and influence the dynamic UI."
hidden: false
createdAt: "2020-09-12T03:38:10.345Z"
---
Even though a [`@goal_rule`](doc:rules-api-goal-rules) is the only type of rule that can print to `stdout` (via the special `Console` type), any rule can log to stderr and change how the rule appears in the dynamic UI.

Adding logging
--------------

To add logging, use the [`logging` standard library module](https://docs.python.org/3/library/logging.html).

```python
import logging

logger = logging.getLogger(__name__)

@rule
def demo(...) -> Foo:
    logger.info("Inside the demo rule.")
    ...
```

You can use `logger.info`, `logger.warning`, `logger.error`, `logger.debug`, and `logger.trace`. You can then change your log level by setting the `-l`/`--level` option, e.g. `pants -ldebug my-goal`.

Changing the dynamic UI
-----------------------

Streaming results (advanced)
----------------------------

When you run `pants fmt`, `pants lint`, and `pants test`, you may notice that we "stream" the results. As soon as an individual process finishes, we print the result, rather than waiting for all the processes to finish and dumping at the end.

We also set the log level dynamically. If something succeeds, we log the result at `INFO`, but if something fails, we use `WARN`.
