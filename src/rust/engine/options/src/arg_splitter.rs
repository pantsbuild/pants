// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use lazy_static::lazy_static;
use regex::Regex;
use std::collections::HashSet;
use std::path::{Path, PathBuf};

lazy_static! {
    static ref SPEC_RE: Regex = Regex::new(r"[/\\.:*#]").unwrap();
    static ref SINGLE_DASH_FLAGS: HashSet<&'static str> =
        HashSet::from(["-ltrace", "-ldebug", "-linfo", "-lwarn", "-lerror", "-h", "-v", "-V"]);
}

#[derive(Debug, Eq, PartialEq)]
pub struct SplitArgs {
    pub goals: Vec<String>,         // The requested known goals.
    pub unknown_goals: Vec<String>, // Any requested but unknown goals.
    pub specs: Vec<String>,         // What to run against, e.g. targets or files/dirs.
    pub passthru: Vec<String>,      // Any remaining args specified after a -- separator.
}

pub struct ArgSplitter {
    build_root: PathBuf,
    known_goal_names: HashSet<String>,
}

impl ArgSplitter {
    pub fn new<'a, I: IntoIterator<Item = &'a str>>(
        build_root: &Path,
        known_goal_names: I,
    ) -> ArgSplitter {
        ArgSplitter {
            build_root: build_root.to_owned(),
            known_goal_names: known_goal_names.into_iter().map(str::to_string).collect(),
        }
    }

    pub fn split_args(&self, args: Vec<String>) -> SplitArgs {
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
            // Some special flags, such as `-v` and `--help`, are implemented as
            // goal aliases, so we must check this before checking for any dash prefixes.
            if self.known_goal_names.contains(&arg) {
                goals.push(arg);
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

        SplitArgs {
            goals,
            unknown_goals,
            specs,
            passthru,
        }
    }
}
