// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::GoalInfo;
use lazy_static::lazy_static;
use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

// These are the names for the built in goals to print help message when there is no goal, or any
// unknown goals respectively. They begin with underlines to exclude them from the list of goals in
// the goal help output.
pub static NO_GOAL_NAME: &str = "__no_goal";
pub static UNKNOWN_GOAL_NAME: &str = "__unknown_goal";

lazy_static! {
    static ref SPEC_RE: Regex = Regex::new(r"[/\\.:*#]").unwrap();
    static ref SINGLE_DASH_FLAGS: HashSet<&'static str> =
        HashSet::from(["-ltrace", "-ldebug", "-linfo", "-lwarn", "-lerror", "-h", "-v", "-V"]);
}

#[derive(Debug, Eq, PartialEq)]
pub struct SplitArgs {
    pub builtin_or_auxiliary_goal: Option<String>, // Requested builtin/auxiliary goal.
    pub goals: Vec<String>,                        // Requested known goals.
    pub unknown_goals: Vec<String>,                // Any requested but unknown goals.
    pub specs: Vec<String>, // What to run against, e.g. targets or files/dirs.
    pub passthru: Vec<String>, // Any remaining args specified after a -- separator.
}

pub struct ArgSplitter {
    build_root: PathBuf,
    known_goals: HashMap<String, GoalInfo>,
}

impl ArgSplitter {
    pub fn new<I: IntoIterator<Item = GoalInfo>>(build_root: &Path, known_goals: I) -> ArgSplitter {
        let mut known_goals_map = HashMap::new();
        for goal_info in known_goals.into_iter() {
            for alias in &goal_info.aliases {
                known_goals_map.insert(alias.to_owned(), goal_info.clone());
            }
            known_goals_map.insert(goal_info.scope_name.to_owned(), goal_info);
        }

        ArgSplitter {
            build_root: build_root.to_owned(),
            known_goals: known_goals_map,
        }
    }

    pub fn split_args(&self, args: Vec<String>) -> SplitArgs {
        let mut builtin_or_auxiliary_goal: Option<String> = None;
        let mut goals = vec![];
        let mut unknown_goals: Vec<String> = vec![];
        let mut specs = vec![];
        let mut passthru = vec![];

        let mut unconsumed_args = args;
        unconsumed_args.reverse();
        // The first arg is the binary name, so skip it.
        unconsumed_args.pop();

        // Scan the args looking for goals and specs.
        // The one hard case is a single word like `foo` with no path- or target-like qualities
        // (e.g., a slash or a colon). It could be a goal, or it could be a top-level directory.
        // We disambiguate thus: If it is a known goal name, assume the user intended a goal.
        // Otherwise, if it looks like a path or target, or exists on the filesystem, assume
        // the user intended a spec, otherwise it's an unknown goal.
        // TODO: This is probably not good logic, since the CLI behavior will change based on
        //  changes to plugins (as they can introduce new goals) or changes on the filesystem.
        //  We might want to deprecate this behavior and consistently assume that these are goals,
        //  since the user can always add a `./` prefix to override.
        while let Some(arg) = unconsumed_args.pop() {
            let goal_info = self.known_goals.get(&arg);
            // Some special flags, such as `-v` and `--help`, are implemented as
            // goal aliases, so we must check this before checking for any dash prefixes.
            if let Some(goal_info) = goal_info {
                let canoncal_scope_name = goal_info.scope_name.clone();
                if (goal_info.is_auxiliary || goal_info.is_builtin)
                    && (builtin_or_auxiliary_goal.is_none() || arg.starts_with("-"))
                {
                    if let Some(boag) = builtin_or_auxiliary_goal {
                        goals.push(boag);
                    }
                    builtin_or_auxiliary_goal = Some(canoncal_scope_name);
                } else {
                    goals.push(canoncal_scope_name);
                }
            } else if arg == "--" {
                // Arg is the passthru delimiter.
                for item in unconsumed_args.drain(..) {
                    passthru.push(item);
                }
                passthru.reverse();
            } else if !(arg.starts_with("--") || SINGLE_DASH_FLAGS.contains(arg.as_str())) {
                // This is not a flag, so it must be an unknown goal or a spec (or a negative spec,
                // which starts with a single dash, and we know is not a single dash flag).
                if arg.starts_with("-")
                    || SPEC_RE.is_match(&arg)
                    || self.build_root.join(Path::new(&arg)).exists()
                {
                    // Arg is a spec.
                    specs.push(arg);
                } else {
                    // Arg is an unknown goal.
                    unknown_goals.push(arg);
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

        SplitArgs {
            builtin_or_auxiliary_goal,
            goals,
            unknown_goals,
            specs,
            passthru,
        }
    }
}
