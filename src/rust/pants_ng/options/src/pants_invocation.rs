// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::iter::Peekable;
use std::sync::LazyLock;
use std::{env, path};

use options::Scope;
use regex::Regex;

static NAME_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[A-Za-z][0-9A-Za-z_\-]*$").unwrap());

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Args {
    pub(crate) arg_strings: Vec<String>,
}

impl Args {
    // Create an Args instance with the provided args, which must *not* include the
    // argv[0] process name.
    pub fn new<I: IntoIterator<Item = String>>(arg_strs: I) -> Self {
        Self {
            arg_strings: arg_strs.into_iter().collect(),
        }
    }

    pub fn argv() -> Self {
        let mut args = env::args().collect::<Vec<_>>().into_iter();
        args.next(); // Consume the process name (argv[0]).
        // TODO: In Pants's own integration tests we may invoke Pants in a subprocess via
        //  `python -m pants` or `python path/to/__main__.py` or similar. So
        //  skipping argv[0] may not be sufficient to get just the set of args to split.
        //  In practice our tests pass despite these extra args being interpreted as specs
        //  or goals, but that is skating on thin ice.
        Self::new(args.collect::<Vec<_>>())
    }
}

// Represents a single cli flag used to set an option value, e.g., `--foo`, or `--bar=baz`.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Flag {
    pub key: String, // The flag name, without the `--` prefix, up to the `=` if any.
    pub value: Option<String>, // The value after the `=`, if any.
}

impl Flag {
    pub fn to_arg_string(&self) -> String {
        if let Some(val) = self.value.as_ref() {
            format!("--{}={}", self.key, val)
        } else {
            format!("--{}", self.key)
        }
    }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct SubCommand {
    pub name: String,
    pub flags: Vec<Flag>,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Command {
    pub name: String,
    pub flags: Vec<Flag>,
    pub subcommand: Option<SubCommand>,
}

// The details of a Pants invocation command.
//
// An invocation has the form:
//
// pants --global-flags \
//   cmd1 --cmd1-flags (subcmd1 --subcmd1-flags)? \
//   + cmd2 --cmd2-flags (subcmd2 --subcmd2-flags)? \
//   ... \
//   + cmdN --cmdN-flags (subcmdN --subcmdN-flags)? \
//   path/to/spec1 path/to/spec2 ... path/to/specM \
//   (-- passthru-args)?
//
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct PantsInvocation {
    pub global_flags: Vec<Flag>,
    pub commands: Vec<Command>,
    pub specs: Vec<String>, // Non-flag arguments, typically file paths or globs.
    pub passthru: Option<Vec<String>>, // Any remaining args specified after a -- separator.
}

impl PantsInvocation {
    pub fn empty() -> Self {
        Self {
            global_flags: vec![],
            commands: vec![],
            specs: vec![],
            passthru: None,
        }
    }

    pub fn from_args(args: Args) -> Result<Self, String> {
        #[inline]
        fn is_flag(s: &str) -> bool {
            s.starts_with("--") && s.len() > 2
        }

        #[inline]
        fn is_name(s: &str) -> bool {
            NAME_RE.is_match(s)
        }

        #[inline]
        fn is_spec(s: &str) -> bool {
            s.contains(path::MAIN_SEPARATOR)
        }

        fn consume_flags<I>(iter: &mut Peekable<I>) -> Vec<Flag>
        where
            I: Iterator<Item = String>,
        {
            let mut ret = vec![];
            while let Some(s) = iter.peek()
                && is_flag(s)
            {
                let mut components = s.splitn(2, '=');
                ret.push(Flag {
                    key: components.next().unwrap()[2..].to_string(),
                    value: components.next().map(str::to_string),
                });
                iter.next();
            }
            ret
        }

        fn consume_cmd<I>(iter: &mut Peekable<I>) -> Option<Command>
        where
            I: Iterator<Item = String>,
        {
            if let Some(s) = iter.peek()
                && is_name(s)
            {
                let name = iter.next().unwrap();
                let flags = consume_flags(iter);
                let subcommand = if let Some(s) = iter.peek()
                    && is_name(s)
                {
                    Some(SubCommand {
                        name: iter.next().unwrap(),
                        flags: consume_flags(iter),
                    })
                } else {
                    None
                };

                Some(Command {
                    name,
                    flags,
                    subcommand,
                })
            } else {
                None
            }
        }

        fn consume_specs<I>(iter: &mut Peekable<I>) -> Vec<String>
        where
            I: Iterator<Item = String>,
        {
            let mut ret = vec![];
            while let Some(s) = iter.peek()
                && is_spec(s)
            {
                ret.push(iter.next().unwrap());
            }
            ret
        }

        let mut unconsumed_args = args.arg_strings.into_iter().peekable();

        let mut global_flags = consume_flags(&mut unconsumed_args);

        let mut commands = vec![];
        let mut cmd_opt = consume_cmd(&mut unconsumed_args);
        while cmd_opt.is_some()
            && let Some(s) = unconsumed_args.peek()
            && s == "+"
        {
            unconsumed_args.next();
            commands.push(cmd_opt.unwrap());
            cmd_opt = consume_cmd(&mut unconsumed_args);
        }
        if let Some(cmd) = cmd_opt {
            commands.push(cmd);
        }

        let specs = consume_specs(&mut unconsumed_args);

        if commands.is_empty() && !specs.is_empty() {
            return Err(format!(
                "Path specs must come after commands, but found `{}` before any commands",
                specs.join(" ")
            ));
        }

        // Any flags after specs (but before passthru args) are considered to be global flags.
        // This makes it convenient to tack flags on at the end of an existing cmd line.
        global_flags.append(&mut consume_flags(&mut unconsumed_args));

        let mut passthru = None;
        if let Some(s) = unconsumed_args.next() {
            if s == "--" {
                let mut remainder = vec![];
                for s in unconsumed_args.by_ref() {
                    remainder.push(s);
                }
                passthru = Some(remainder);
            } else if specs.is_empty() {
                return Err(format!("Invalid command name `{s}`"));
            } else {
                return Err(format!("Extraneous argument `{s}`"));
            }
        }

        Ok(PantsInvocation {
            global_flags,
            commands,
            specs,
            passthru,
        })
    }

    pub fn goals(&self) -> Vec<String> {
        self.commands
            .iter()
            .map(|cmd| {
                if let Some(subcmd) = cmd.subcommand.as_ref() {
                    format!("{}.{}", cmd.name, subcmd.name)
                } else {
                    cmd.name.clone()
                }
            })
            .collect()
    }

    pub(crate) fn get_flags(&self) -> HashMap<Scope, HashMap<String, Vec<Option<String>>>> {
        let mut flags: HashMap<Scope, HashMap<String, Vec<Option<String>>>> = HashMap::new();
        // Global flags can either refer implicitly to options in the global scope (--global_option),
        // or prefixed with an explicit scope and a dash (--explicit-scope-flag_in_that_scope).
        // Multi-word scope names must use dashes as word separators, while multi-word option
        // names must use underscores as word separators, so that a flag is never ambiguous.
        for flag in &self.global_flags {
            let (scope_name, name) = flag.key.rsplit_once("-").unwrap_or(("", &flag.key));
            flags
                .entry(Scope::named(scope_name))
                .or_default()
                .entry(name.to_string())
                .or_default()
                .push(flag.value.clone());
        }
        // Command flags for `command` correspond to options with scopes named `command`.
        // Subcommand flags correspond to options with scopes named `command.subcommand`.
        for command in &self.commands {
            let flags_for_scope = flags.entry(Scope::named(&command.name)).or_default();
            for flag in &command.flags {
                flags_for_scope
                    .entry(flag.key.clone())
                    .or_default()
                    .push(flag.value.clone());
            }
            if let Some(subcommand) = &command.subcommand {
                let subcommand_scope = format!("{}.{}", &command.name, &subcommand.name);
                let flags_for_scope = flags.entry(Scope::named(&subcommand_scope)).or_default();
                for flag in &subcommand.flags {
                    flags_for_scope
                        .entry(flag.key.clone())
                        .or_default()
                        .push(flag.value.clone());
                }
            }
        }
        flags
    }
}
