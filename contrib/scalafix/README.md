# Pants plugin to support executing scalafix

A plugin to add support for executing the [scalafix](https://scalacenter.github.io/scalafix/) tool.

## Setup

Unlike `scalafmt` (which is included in the default distribution of pants), `scalafix` requires a
compiler plugin, and is thus distributed as a contrib module with extra setup steps.

The [scalameta](http://scalameta.org/) compiler plugin extracts semantic information at compile
time that is used in some of the most useful `scalafix` rewrites. To install `scalameta` in your
build, you should define a `//:scalac-plugin-dep` target (at the root of your repository) that
references it, and uses the full compiler version:

```
FULL_SCALA_REV=2.11.11
jar_library(
  name = 'scalac-plugin-dep',
  jars = [jar(org='org.scalameta', name='scalahost_{}'.format(SCALA_REV), rev='1.8.0')],
)
```

Then, you will additionally need to enable plugin, and pass the `-Yrangepos` flag for scalac
in `pants.ini`:
```
[compile.zinc]
args: [
    # The `-S` prefix here indicates that zinc should pass this option to scalac rather than
    # to javac (`-C` prefix).
    '-S-Yrangepos',
  ]

scalac_plugins: [
    'scalahost',
  ]
```

## Usage

Tasks for both the `fmt` and `lint` goals are provided, each with the same set of options.

The `fmt.scalafix` task executes rewrites in place (that is: it will edit your code!) for the
specified targets, and would generally be used explicitly to run a particular rewrite:
```
./pants fmt.scala --rewrites=ProcedureSyntax ${TARGETS}
```

The `lint.scalafix` task on the other hand operates in a readonly mode, and reports whether
any changes would have been made to the targets.

To enforce a particular pattern in your repo, you'd generally use either the `--rewrite` or
`--config` options (corresponding to the
[upstream CLI options](https://scalacenter.github.io/scalafix/#--help)) in `pants.ini` to declare
the relevant rewrites for both the `lint.scalafix` and `fmt.scalafix` tasks.
