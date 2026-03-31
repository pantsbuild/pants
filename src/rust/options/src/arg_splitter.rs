// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::flags::Flag;
use crate::{GoalInfo, Scope};

use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::env;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

// These are the names for the built in goals to print help message when there is no goal, or any
// unknown goals respectively. They begin with underlines to exclude them from the list of goals in
// the goal help output.
pub const NO_GOAL_NAME: &str = "__no_goal";
pub const UNKNOWN_GOAL_NAME: &str = "__unknown_goal";

static SPEC_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[/\\.:*#]").unwrap());
static SINGLE_DASH_FLAGS: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    HashSet::from([
        "-h", "-v", "-V", "-ltrace", "-ldebug", "-linfo", "-lwarn", "-lerror", "-l=trace",
        "-l=debug", "-l=info", "-l=warn", "-l=error",
    ])
});

#[derive(Clone, Debug, Eq, PartialEq)]
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

// The details of a Pants invocation command, not including option flags.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct PantsCommand {
    pub builtin_or_auxiliary_goal: Option<String>, // Requested builtin/auxiliary goal.
    pub goals: Vec<String>,                        // Requested known goals.
    pub unknown_goals: Vec<String>,                // Any requested but unknown goals.
    pub specs: Vec<String>, // What to run against, e.g. targets or files/dirs.
    pub(crate) flags: Vec<Flag>, // Option values set via flag.
    pub passthru: Option<Vec<String>>, // Any remaining args specified after a -- separator.
}

impl PantsCommand {
    pub fn empty() -> Self {
        Self {
            builtin_or_auxiliary_goal: None,
            goals: vec![],
            unknown_goals: vec![],
            specs: vec![],
            flags: vec![],
            passthru: None,
        }
    }

    pub fn add_specs(self, extra_specs: Vec<String>) -> Self {
        Self {
            specs: [self.specs, extra_specs].concat(),
            ..self
        }
    }
}

pub struct ArgSplitter {
    build_root: PathBuf,
    known_goals: HashMap<String, GoalInfo>,
}

impl ArgSplitter {
    pub fn new<I: IntoIterator<Item = GoalInfo>>(build_root: &Path, known_goals: I) -> Self {
        let mut known_goals_map = HashMap::new();
        for goal_info in known_goals.into_iter() {
            for alias in &goal_info.aliases {
                known_goals_map.insert(alias.to_owned(), goal_info.clone());
            }
            known_goals_map.insert(goal_info.scope_name.to_owned(), goal_info);
        }

        Self {
            build_root: build_root.to_owned(),
            known_goals: known_goals_map,
        }
    }

    // Split the given args, which must *not* include the argv[0] process name.
    pub fn split_args(&self, args: Args) -> PantsCommand {
        let mut builtin_or_auxiliary_goal: Option<String> = None;
        let mut goals = vec![];
        let mut unknown_goals: Vec<String> = vec![];
        let mut specs = vec![];
        let mut flags = vec![];
        let mut passthru = None;
        let mut scope = Scope::Global;

        let mut unconsumed_args = args.arg_strings.into_iter();

        // Scan the args looking for goals, specs and flags.
        // The one hard case is a single word like `foo` with no path- or target-like qualities
        // (e.g., a slash or a colon). It could be a goal, or it could be a top-level directory.
        // We disambiguate thus: If it is a known goal name, assume the user intended a goal.
        // Otherwise, if it looks like a path or target, or exists on the filesystem, assume
        // the user intended a spec, otherwise it's an unknown goal.
        // TODO: This is probably not good logic, since the CLI behavior will change based on
        //  changes to plugins (as they can introduce new goals) or changes on the filesystem.
        //  We might want to deprecate this behavior and consistently assume that these are goals,
        //  since the user can always add a `./` prefix to override.
        while let Some(arg) = unconsumed_args.next() {
            let goal_info = self.known_goals.get(&arg);
            // Some special flags, such as `-v` and `--help`, are implemented as
            // goal aliases, so we must check this before checking for any dash prefixes.
            if let Some(goal_info) = goal_info {
                let canonical_scope_name = goal_info.scope_name.clone();
                if (goal_info.is_auxiliary || goal_info.is_builtin)
                    && (builtin_or_auxiliary_goal.is_none() || arg.starts_with("-"))
                {
                    if let Some(boag) = builtin_or_auxiliary_goal {
                        goals.push(boag);
                    }
                    builtin_or_auxiliary_goal = Some(canonical_scope_name);
                } else {
                    goals.push(canonical_scope_name);
                }
                scope = Scope::Scope(arg.clone());
            } else if arg == "--" {
                // Arg is the passthru delimiter.
                let mut remainder = vec![];
                for s in unconsumed_args.by_ref() {
                    remainder.push(s);
                }
                passthru = Some(remainder);
            } else if arg.starts_with("--") {
                let mut components = arg.splitn(2, '=');
                let flag_name = components.next().unwrap();
                flags.push(Flag {
                    context: scope.clone(),
                    key: flag_name.to_string(),
                    value: components.next().map(str::to_string),
                });
            } else if SINGLE_DASH_FLAGS.contains(arg.as_str()) {
                let (flag_name, mut flag_value) = arg.split_at(2);
                // We support both -ldebug and -l=debug, so strip that extraneous equals sign.
                if let Some(stripped) = flag_value.strip_prefix('=') {
                    flag_value = stripped;
                }
                flags.push(Flag {
                    context: scope.clone(),
                    key: flag_name.to_string(),
                    value: if flag_value.is_empty() {
                        None
                    } else {
                        Some(flag_value.to_string())
                    },
                });
            } else {
                // This is not a flag, so it must be an unknown goal or a spec (or a negative spec,
                // which starts with a single dash, and we know is not a single dash flag).
                if arg.starts_with("-")
                    || SPEC_RE.is_match(&arg)
                    || self.build_root.join(Path::new(&arg)).exists()
                {
                    // Arg is a spec.
                    specs.push(arg);
                    // Revert to global context for any trailing flags.
                    scope = Scope::Global;
                } else {
                    // Arg is an unknown goal.
                    unknown_goals.push(arg.clone());
                }
            }
        }

        if builtin_or_auxiliary_goal.is_none() {
            if !unknown_goals.is_empty() {
                builtin_or_auxiliary_goal = Some(UNKNOWN_GOAL_NAME.to_string());
            } else if goals.is_empty() {
                builtin_or_auxiliary_goal = Some(NO_GOAL_NAME.to_string())
            }
        }

        PantsCommand {
            builtin_or_auxiliary_goal,
            goals,
            unknown_goals,
            specs,
            flags,
            passthru,
        }
    }
}
