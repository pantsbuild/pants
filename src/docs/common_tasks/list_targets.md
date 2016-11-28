# List Available Targets

## Problem

You want to find out which Pants targets are currently available in your project or in a subfolder within the project.

## Solution

Use the `list` goal and specify a folder containing a `BUILD` file. This command, for example, would show all targets available in `myproject/BUILD`:

```bash
$ ./pants list myproject/:
```

This command would show all targets available in the `myproject` directory *as well as in all subdirectories*:

```bash
$ ./pants list myproject/::
```

Note the syntactical difference between the single colon and the double colon.

The output from a `./pants list` invocation may look something like this:

```bash
$ ./pants list server/:
server/server:analytics
server/server:bin
server/server:tests
```

## Warning

We do not recommend using `./pants list ::` unless you're working with a very small Pants project. This command will list *all* targets currently available in the entire project, which can be a very slow operation in larger projects.

## See Also

* [[List All Pants Goals|pants('src/docs/common_tasks:list_goals')]]
