# Create a Target Aggregate

## Problem

You want to create a common target that when run in turn run several other targets

## Solution

Use a literal `target` definition in your BUILD file to specify an aggregate target that depends on all the targets you wish to run

Here's an example `target` definition that creates a target names `agg` dependent on two modules named `dep1` and `dep2`:

    :: python
    # agg/BUILD
    target(name='agg',
      dependencies=[
        'myproject/src/main/scala/com/twitter/myproject/subproject/dep1:scala',
        'myproject/src/main/scala/com/twitter/myproject/subproject/dep2:scala'
      ]
    )

Triggering any goal for `agg` will trigger said goal for both `dep1` and `dep2`

If you wish to create an alias for an existing target see [[Create an Alias for a Target|pants('src/docs/common_tasks:alias')]]

## See Also

* [[Create an Alias for a Target|pants('src/docs/common_tasks:alias')]]
