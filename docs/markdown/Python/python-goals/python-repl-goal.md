---
title: "repl"
slug: "python-repl-goal"
excerpt: "Open a REPL for interactive development."
hidden: false
createdAt: "2020-03-16T16:19:56.329Z"
updatedAt: "2022-02-09T01:01:10.431Z"
---
Pants will load a [REPL](https://en.wikipedia.org/wiki/REPL) with all of your specified source code and any of its third-party dependencies, which allows you to import those values.
[block:api-header]
{
  "title": "IPython"
}
[/block]
In addition to the default Python shell, Pants supports the improved [IPython shell](https://ipython.org).

To use IPython, run `./pants repl --shell=ipython`. To permanently use IPython, add this to your `pants.toml`:
[block:code]
{
  "codes": [
    {
      "code": "[repl]\nshell = \"ipython\"",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
You can change IPython's version with `[ipython].version`. If you change it, Pants's default lockfile for IPython will not work. Either set the `lockfile` option to a custom path or `"<none>"` to opt-out. See [Third-party dependencies](doc:python-third-party-dependencies#tool-lockfiles).
[block:code]
{
  "codes": [
    {
      "code": "[ipython]\nversion = \"ipython>=6.0.0\"\nlockfile = \"3rdparty/python/ipython_lock.txt\"\n",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]


If you set the `version` lower than IPython 7, then you must set `[ipython].ignore_cwd = false` to avoid Pants setting an option that did not exist in earlier IPython releases.
[block:callout]
{
  "type": "danger",
  "title": "IPython does not yet work with Pantsd",
  "body": "When using IPython, use the option `--no-pantsd` to turn off the Pants daemon, e.g. `./pants --no-pantsd repl --shell=ipython`. We are working to [fix this](https://github.com/pantsbuild/pants/issues/9939)."
}
[/block]

[block:callout]
{
  "type": "info",
  "title": "Python 2 support",
  "body": "Pants uses IPython 7 by default, which does not work with Python 2. You can override `version` to use IPython 5. As mentioned above, you must set `ignore_cwd = false`.\n\n```toml\n[ipython]\nversion = \"ipython<6\"\nlockfile = \"3rdparty/python/ipython_lock.txt\"\nignore_cwd = false\n```\n\nYou can even use IPython 7 for Python 3 code, and IPython 5 for Python 2 code:\n\n```toml\n[ipython]\nversion = \"ipython==7.16.1 ; python_version >= '3.6'\"\nextra_requirements.add = [\"ipython<6 ; python_version == '2.7'\"]\nlockfile = \"3rdparty/python/ipython_lock.txt\"\nignore_cwd = false\n```"
}
[/block]

[block:api-header]
{
  "title": "Examples"
}
[/block]

[block:code]
{
  "codes": [
    {
      "code": "$ ./pants repl helloworld/greet/greeting.py\n\nPython 3.7.6 (default, Feb 26 2020, 08:28:08)\n[Clang 11.0.0 (clang-1100.0.33.8)] on darwin\nType \"help\", \"copyright\", \"credits\" or \"license\" for more information.\n(InteractiveConsole)\n>>> from helloworld.greet.greeting import Greeter\n>>> Greeter().greet(\"Pants\")\n'buenas tardes, Pants!'\n>>> from translate import Translator\n>>> Translator(to_lang=\"fr\").translate(\"Good morning.\")\n'Salut.'",
      "language": "text",
      "name": "Shell"
    }
  ]
}
[/block]
This will not load any of your code:
[block:code]
{
  "codes": [
    {
      "code": "$ ./pants --no-pantsd repl --shell=ipython\n\nPython 3.6.10 (default, Feb 26 2020, 08:26:13)\nType \"copyright\", \"credits\" or \"license\" for more information.\n\nIPython 5.8.0 -- An enhanced Interactive Python.\n?         -> Introduction and overview of IPython's features.\n%quickref -> Quick reference.\nhelp      -> Python's own help system.\nobject?   -> Details about 'object', use 'object??' for extra details.\n\nIn [1]: 21 * 4\nOut[1]: 84",
      "language": "text",
      "name": "Shell"
    }
  ]
}
[/block]
`./pants repl ::` will load all your code.
[block:callout]
{
  "type": "info",
  "title": "Tip: how to exit the REPL",
  "body": "Either type `exit()` and hit enter, or press `ctrl+d`."
}
[/block]