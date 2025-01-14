// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use lazy_static::lazy_static;

use regex::Regex;

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum Scope {
    Global,
    Scope(String),
}

lazy_static! {
    // Note: must be aligned with the regex in src/python/pants/option/subsystem.py.
    static ref SCOPE_NAME_RE: Regex = Regex::new(r"^(?:[a-z0-9_])+(?:-(?:[a-z0-9_])+)*$").unwrap();
}

pub(crate) fn is_valid_scope_name(name: &str) -> bool {
    // The exact string "pants" is not allowed as a scope name: if we encounter it on the
    // command line, it is part of the invocation: /path/to/python -m pants <actual args>.
    SCOPE_NAME_RE.is_match(name) && name != "pants"
}

impl Scope {
    pub fn named(name: &str) -> Scope {
        match name {
            "" | "GLOBAL" => Scope::Global,
            scope => Scope::Scope(scope.to_owned()),
        }
    }

    pub fn name(&self) -> &str {
        match self {
            Scope::Global => "GLOBAL",
            Scope::Scope(scope) => scope.as_str(),
        }
    }
}
