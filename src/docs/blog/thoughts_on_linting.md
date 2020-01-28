# Some thoughts on formatting and linting

**28/01/2020**

**Authors and Contributors**

[[Daniel Wagner-Hall|https://twitter.com/illicitonion]], [[Stu Hood|https://twitter.com/stuhood]] and [[Pierre Chevalier|https://twitter.com/pierrechevali15]] at Twitter Engineering Effectiveness - Build.

## Context

In the last few weeks, I have worked on a task to accelerate the linting experience at Twitter by bypassing pants entirely for certain linters in favour of a script that only runs a given linter on a given set of files.

Byapassing pants speeds up linting for two reasons: there is a fixed overhead to running any command in pants, and when linting a single file, pants will lint the entire target which incurs some unnecessary work.

The script I wrote is an interface between various formatters/linters and another tool (arcanist); so this allowed me to develop some thoughts on linters, and how to let them expose a consistent interface to outside tools.

In this post, I would like to sum up some of these thoughts and possibly extract recommendations that may be applied to pants as we port linters to v2.

One of the key take-aways of this post is the description of a [[communication format|pants('src/docs/blog:thoughts_on_linting')#communication-format]] between a linter wrapper and an outside tool.

## Semantics

Before diving into the substance, I would like to clarify some semantic to avoid any confusion.

Note that in general, a formatter and a linter are different tools. A formatter (for instance, rustfmt, clang-format, gofmt) is generally focused on "simple formatting" changes whereas a linter may focus on higher level concepts called "lints" (for instance, clippy, clang-tidy, golint).
Sometimes, it means that it is more likely that a formatter will be able to edit files inplace, as the changes are more trivial. This being said, some linters may be able to automatically fix some specific lints (for instance clang-tidy with `--fix` or clippy with `cargo fix --clippy`).
Another distinction that is sometimes implied by categorizing a tool as a formatter or a linter is that a linter is more likely to operate "semantically", meaning it may need to be aware of the transitive dependencies of the file being linted. Formatters typically would only operate "syntactically", which means that a single file would definitely contain all the information needed to format it.

So in general, there are two different categories of tools that try to improve your code: formatters and linters. For any of these tools, there could be two modes of operation: `--fix` and `--check`.

Because the difference between linters and formatters can be blury (for instance, `flake8` is a linter which also gives formatting advice), in the context of pants, we assign a different meaning to these terms:

- *Formatter*: a tool which automatically edits your code. (the `--fix` concept from above)

- *Linter*: a tool which suggests edits to your code but doesn't produce an actual diff. (the `--check` concept from above)

This means that running `./pants fmt` and `./pants lint` on a piece of code may very well run the same tool in two different modes.

## Linters, adapters and views

I would like to limit the scope of what is being discussed in this blogpost by introducing a philosophical distinction between different parts of the architecture involved when a user lints their code with pants.

Splitting the problem into multiple layers of abstraction, we have:

- A *linter/formatter*. Sitting at the lowest level of abstraction, this is a tool which actually formats or lints code. These tools typically exist as standalone tools outside of pants. Example of such tools includes `gofmt`, `scalafmt`, `checkstyle` etc. Because we don't own these tools, the set of flags they take, the way they are invoked, the meaning of the error code they return etc. may vary significantly between tools.

- A *linter adapter*. As its name indicates, this tool "adapts" any linter to conform to a specific interface that is decided by us. It allows to hide any inconsistencies between linters to entities operating at a higher level of abstraction. This avoids an explosions of the number of ways to deal with linting where the amount of code to write would be `O(number of linters * number of ways to interpret a linter's output)`. Concretely, this tool would be able to call any linter of a given set and provide a consistent experience to the caller of the linter adapter. For instance, error codes returned by this tool would have an assigned meaning and wouldn't vary depending on the underlying linter. This layer of abstraction is not meant to be directly interacted with by a user, which means that the interface can be "tool-focused". For instance, a *linter adapter* doesn't need to output human readable logging in stdout.
  Concretely, a *linter adapter* would only be one part of a linter integration into pants.

- A *linter view*. At the highest level of abstraction, we need a way for our human users to interact with linters and get feedback on any linting error present in their code, be it with an automatic fix or with an error report. There may be more than one view. For instance, a vim plugin could be a linter view, a git hook could be abother view and a pants cli invocation may be yet another view. Because we defined the concept of a linter adapter, coding such a view doesn't involve an explosion of linter-specific handling since that was already abstracted away.

In my work on accelerating linting at twitter, the *linter adapter* was a script I wrote called `source_linter.py`. The *linter view* was `arc lint`.
In the context of pants, the adapter and the view may both live in the pants codebase and the view would be the only piece of software a user is directly exposed to.

Introducing this distinction allows us to design an interface for a `linter adapter` that aims to be fully "tool-proof" and does not need to be "user friendly". The `linter view` should be "user friendly", but this is a topic for another blogpost. The following discussion primarily focuses on defining a sensible interface for a `linter adapter`.


## Consistency

If the goal is to interact with a dumb tool, consistency is key. This includes error codes, how to represent an error and how to represent a suggested diff.

Your mileage may vary, but here are some lessons learnt from writing the `source_linter` script:

### Communicating with the outside world

There are a few ways a process can communicate with other processes:

- [[Error codes|pants('src/docs/blog:thoughts_on_linting')#error-codes]]

- [[IO streams|pants('src/docs/blog:thoughts_on_linting')#io-streams]]

- [[The file system|pants('src/docs/blog:thoughts_on_linting')#existence-of-an-output-directory]]

- [[RPCs|pants('src/docs/blog:thoughts_on_linting')#why-not-use-rpcs]]

#### Error codes
Error codes are useful and they can convey limited information on what happened during the linting of a set of files.

When formatting/linting some code, 3 outcomes may happen;
I assigned the following integer codes to distinguish them:

- 0 - The code was formatted/linted successfuly and no change to the code was suggested.

- 1 - The linter/formatter failed for some reason (for instance, the file had a syntax error which tripped the linter/formatter up).

- 2 - The code was formatted/linted successfuly and a change was suggested.

#### IO streams

IO streams are useful and they can convey information that is general to the process of linting a set of files.

When the underlying tool fails to lint/fmt some code, if a description for the cause of the failure was given, it makes sense to simply dump it to stdout.

#### Existence of an output directory

The filesystem can be a convenient way to communicate feedback on what happened at a file-per-file level when linting a set of files.
When using the filesystem, a decision must be made:

- Do we edit the files inplace or not?
  There are two issues with editing source files in-place:

    - It doesn't parallelize well:

         - If we were going to run different linters in parallel on the same file and both tried to edit the source file in-place, concurrency issues would arise.

    - It doesn't generalize to non-autofixing tasks (linters)

For these two reasons, it makes sense to use an output directory to communicate file-level information:

- Suggested edits to the code (formatting suggestions)

- Reported errors in the code (linting errors)

Note that the behaviour of editing source files inplace may be desirable. It may also be desirable to expose it in pants. See [[Linters, adapters and views|pants('src/docs/blog:thoughts_on_linting')#linters-adapters-and-views]] 

The linting tool may use a certain directory structure under the output directory to communicate which files the diff or error refer too.
One possible scheme is as follows:
```
{output_dir}/{linter_name}/{relative_path}.{extension}
```
Where the relative_path would be the relative path to the file from the root of the repository and the extension could be `.error` to indicate an error report relating to that input file or `.fixed` to indicate a suggested modification to that input file.
Note that the `{linter_name}` isn't something I've actually implemented in my work on Twitter source code, but my script only ever ran one linter at a time and I would expect for pants to possibly run multiple linters on a given file at the same time. Having parallel directory structures would avoid overwriting the results of one linter with the results of another.

#### Why not use RPCs?

RPCs may be the right solution for tooling in the long term; for instance, if the Language Server Protocol was to be extended to add awareness of formatters/linters, it would almost certainly be the best way to communicate between tools.
In the absence of an existing standard protocol, though; it feels like inventing a new RPC protocol to interact between linters and other tools would be a case of over-engineering.

### Communication format

Three different kinds of things may be communicated from a linter/formatter to the world:

- a suggested edit in a file,

    - For this, in my work at Twitter, I chose to simply output a file containing the modified version of the code

    - This was because arcanist understands that format, which is a detail. If we were willing to spend a bit of time on it, arcanist could easily be made to understand a `diff` by simply applying it to the original file and working with the resulting file

    - If I had to recommend a way to do it, I would say that outputting a `diff` is more elegant

- a reported linting error,

    - To report a linting error to a tool, one of the easiest way is json. It's simple to output and to parse in most languages. It reads better and parses more easily than XML (*opinion)

    - If the linter doesn't provide a rich enough output, falling back to plain text may also be OK; providing that the tools which parse this output are aware of this detail.

    - Here is a suggested json schema that would contain most information ever needed:
```
// A list of errors found in this file
[
  {
    "message": "Failed to demangle the foo", // A string describing the error. Must be present.
    "line": "42", // Line number. Optional
    "column": "12", // Column number. Optional
    "code": "532 - DEMANG", // Shortcode for error (can be an int, a tag-like string or both) from underlying linter. Optional
    "level": "error", // One of "error", "warning" or "info". Optional
  },
  {
    "message": "Possibly as many other errors as needed"
  }
  ...
]
```

- a failure to lint

    - For a failure to lint, plain text in the stdout stream makes sense and is simple enough.

## The transparency vs consistency trade-off

Users may be familiar with how some specific linters work. For instance, a user may expect a particular linter to return certain error codes to represent some situation.
By forcing linters into consistency with one another, we may surprise users by diverging from the default behaviour.
I feel like this is a trade-off we have to live with if we value interoperability with external tools.
A workaround for the negative aspect of this trade-off would be to write extensive documentation on the behaviour of pants driving linters (as opposed to running the linters themselves)

There definitely is a cost to adding a layer of abstraction between the user and the linter.

### Configurability

In general, linters expose some configurability to the user through command line flags or config files.
There are different kinds of things that may be configured:

- Indentation preferences

- Location of the file that contains indentation preferences

- Linter behaviour (for instance, should you edit the file inplace or not; should you return a non-zero error code on a linting error or not, etc.)

If we are writing a tool that adapt any linter to a given interface, we probably can not afford to leak the third kind of configurations to the user as that would make our work much harder.

We definitely do want to allow the user to configure indentation preferences as this is none of our buisness.

It is debatable if we should allow the user to point us at a specific config file location or if we should aim to enforce use of the default locations supported by the underlying linters.

An advantage of enforcing use of the default locations used by the linters is that IDEs, text editor plugins etc. should all behave consistently with pants without requiring the user to perform latteral configration.
The drawback of this approach is that we, as pants authors must be able to list all the locations in which a configuration file may possibly be found to add it as a dependency to our linting task. This may be non-trivial or impose a maintainance burden as the number of linters we support increases and as these tools evolve.

A possible solution to this trade-off would be to always have the user explicitely specify the config file location (if not using all defaults for that linter), but encourage them to use a default location in our documentation.

#### Passthrough arguments

Given the issues described in the [[Configurability section above|pants('src/docs/blog:thoughts_on_linting')#configurability]], passthrough arguments are a concern because they may allow the user to have the linter behaves in a way that breaks our (as pants authors) assumptions.
On another hand, we may not want to expose each flag that each linter supports through pants; as this list can grow quickly and create a maintainance burden as each linter changes over time.

One possible solution for this dichotomy is to minimise the surface of linter configurability exposed to pants users. This may cause some upset for some users who rely on these hooks and cranies and there may be good reasons to revisit that position as we go, but that is where I would currently stand.

I think exposing less in a first time and re-evaluating as usecases show up may be the prudent approach.

