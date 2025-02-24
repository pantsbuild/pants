// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use super::id::{NameTransform, OptionId};
use super::scope::Scope;
use super::{DictEdit, OptionsSource};
use crate::fromfile::FromfileExpander;
use crate::parse::{ParseError, Parseable};
use crate::ListEdit;
use itertools::{chain, Itertools};
use parking_lot::Mutex;
use std::any::Any;
use std::collections::{HashMap, HashSet};
use std::iter::once;
use std::sync::Arc;

// Represents a single cli flag used to set an option value, e.g., `--foo`, or `--bar=baz`.
// The `context` field tracks the scope in which the flag was found, e.g., in
// `pants --foo goal --bar=baz` the scope for `--foo` is GLOBAL and for `--bar` it is `goal`.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub(crate) struct Flag {
    pub(crate) context: Scope,
    pub(crate) key: String,           // E.g., `--foo` or `--bar`.
    pub(crate) value: Option<String>, // E.g., None or Some(`baz`).
}

impl Flag {
    /// Checks if the flag is equal to the provided strings concatenated with dashes.
    /// E.g., "--foo-bar" matches ["-", "foo", "bar"].
    fn _flag_match<'a>(&self, dash_separated_strs: impl Iterator<Item = &'a str>) -> bool {
        #[allow(unstable_name_collisions)]
        // intersperse is provided by itertools::Itertools, but is also in the Rust nightly
        // as an experimental feature of standard Iterator. If/when that becomes standard we
        // can use it, but for now we must squelch the name collision.
        itertools::equal(
            self.key.chars(),
            dash_separated_strs
                .map(str::chars)
                .intersperse("-".chars())
                .flatten(),
        )
    }

    fn _prefix<'a>(negate: bool) -> impl Iterator<Item = &'a str> {
        if negate {
            once("--no")
        } else {
            once("-")
        }
    }

    // Check if --scope-flag matches.
    fn _matches_explicit_scope(&self, id: &OptionId, negate: bool) -> bool {
        self._flag_match(chain![
            Self::_prefix(negate),
            once(id.scope.name()),
            id.name_components_strs()
        ])
    }

    // Check if --flag matches in the context of the current goal's scope.
    fn _matches_implicit_scope(&self, id: &OptionId, negate: bool) -> bool {
        self.context == id.scope
            && self._flag_match(chain![Self::_prefix(negate), id.name_components_strs()])
    }

    // Check if -s matches for a short name s, if any.
    fn _matches_short(&self, id: &OptionId) -> bool {
        if let Some(sn) = &id.short_name {
            self._flag_match(chain![once(""), once(sn.as_ref())])
        } else {
            false
        }
    }

    /// Checks if this arg provides a value for the specified option, either negated or not.
    fn _matches(&self, id: &OptionId, negate: bool) -> bool {
        self._matches_explicit_scope(id, negate)
            || self._matches_implicit_scope(id, negate)
            || self._matches_short(id)
    }

    pub(crate) fn matches(&self, id: &OptionId) -> bool {
        self._matches(id, false)
    }

    pub(crate) fn matches_negation(&self, id: &OptionId) -> bool {
        self._matches(id, true)
    }
}

pub(crate) struct FlagsTracker {
    unconsumed_flags: Mutex<HashSet<Flag>>,
}

impl FlagsTracker {
    pub(crate) fn new(flags: &[Flag]) -> Self {
        Self {
            unconsumed_flags: Mutex::new(flags.iter().cloned().collect()),
        }
    }

    pub(crate) fn consume_flag(&self, flag: &Flag) {
        self.unconsumed_flags.lock().remove(flag);
    }

    pub fn get_unconsumed_flags(&self) -> HashMap<Scope, Vec<String>> {
        // Map from positional context (GLOBAL or a goal name) to unconsumed flags encountered
        // at that position in the CLI args.
        let mut ret: HashMap<Scope, Vec<String>> = HashMap::new();
        for flag in self.unconsumed_flags.lock().iter() {
            if let Some(flags_for_context) = ret.get_mut(&flag.context) {
                flags_for_context.push(flag.key.clone());
            } else {
                let flags_for_context = vec![flag.key.clone()];
                ret.insert(flag.context.clone(), flags_for_context);
            };
        }
        for entry in ret.iter_mut() {
            entry.1.sort(); // For stability in tests and when reporting unconsumed flags.
        }
        ret
    }
}

pub(crate) struct FlagsReader {
    flags: Vec<Flag>,
    fromfile_expander: FromfileExpander,
    tracker: Arc<FlagsTracker>,
}

impl FlagsReader {
    pub fn new(flags: Vec<Flag>, fromfile_expander: FromfileExpander) -> Self {
        let tracker = Arc::new(FlagsTracker::new(&flags));
        Self {
            flags,
            fromfile_expander,
            tracker,
        }
    }

    pub fn get_tracker(&self) -> Arc<FlagsTracker> {
        self.tracker.clone()
    }

    fn matches(&self, flag: &Flag, id: &OptionId) -> bool {
        let ret = flag.matches(id);
        if ret {
            self.tracker.consume_flag(flag);
        }
        ret
    }

    fn matches_negation(&self, flag: &Flag, id: &OptionId) -> bool {
        let ret = flag.matches_negation(id);
        if ret {
            self.tracker.consume_flag(flag);
        }
        ret
    }

    fn to_bool(&self, arg: &Flag) -> Result<Option<bool>, ParseError> {
        // An arg can represent a bool either by having an explicit value parseable as a bool,
        // or by having no value (in which case it represents true).
        match &arg.value {
            Some(value) => match self.fromfile_expander.expand(value.to_string())? {
                Some(s) => bool::parse(&s).map(Some),
                _ => Ok(None),
            },
            None => Ok(Some(true)),
        }
    }

    fn get_list<T: Parseable>(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<T>>>, String> {
        let mut edits = vec![];
        for flag in &self.flags {
            if self.matches(flag, id) {
                let value = flag.value.as_ref().ok_or_else(|| {
                    format!("Expected list option {} to have a value.", self.display(id))
                })?;
                if let Some(es) = self
                    .fromfile_expander
                    .expand_to_list::<T>(value.to_string())
                    .map_err(|e| e.render(&flag.key))?
                {
                    edits.extend(es);
                }
            }
        }
        if edits.is_empty() {
            Ok(None)
        } else {
            Ok(Some(edits))
        }
    }
}

impl OptionsSource for FlagsReader {
    fn display(&self, id: &OptionId) -> String {
        format!(
            "--{}{}",
            match &id.scope {
                Scope::Global => "".to_string(),
                Scope::Scope(scope) => format!("{}-", scope.to_ascii_lowercase()),
            },
            id.name("-", NameTransform::ToLower)
        )
    }

    fn as_any(&self) -> &dyn Any {
        self
    }

    fn get_string(&self, id: &OptionId) -> Result<Option<String>, String> {
        // We iterate in reverse so that the rightmost flag wins in case an option
        // is specified multiple times.
        for flag in self.flags.iter().rev() {
            if self.matches(flag, id) {
                return self
                    .fromfile_expander
                    .expand(flag.value.clone().ok_or_else(|| {
                        format!("Expected list option {} to have a value.", self.display(id))
                    })?)
                    .map_err(|e| e.render(&flag.key));
            };
        }
        Ok(None)
    }

    fn get_bool(&self, id: &OptionId) -> Result<Option<bool>, String> {
        // We iterate in reverse so that the rightmost arg wins in case an option
        // is specified multiple times.
        for arg in self.flags.iter().rev() {
            if self.matches(arg, id) {
                return self.to_bool(arg).map_err(|e| e.render(&arg.key));
            } else if self.matches_negation(arg, id) {
                return self
                    .to_bool(arg)
                    .map(|ob| ob.map(|b| b ^ true))
                    .map_err(|e| e.render(&arg.key));
            }
        }
        Ok(None)
    }

    fn get_bool_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<bool>>>, String> {
        self.get_list::<bool>(id)
    }

    fn get_int_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<i64>>>, String> {
        self.get_list::<i64>(id)
    }

    fn get_float_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<f64>>>, String> {
        self.get_list::<f64>(id)
    }

    fn get_string_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<String>>>, String> {
        self.get_list::<String>(id)
    }

    fn get_dict(&self, id: &OptionId) -> Result<Option<Vec<DictEdit>>, String> {
        let mut edits = vec![];
        for flag in self.flags.iter() {
            if self.matches(flag, id) {
                let value = flag.value.clone().ok_or_else(|| {
                    format!("Expected dict option {} to have a value.", self.display(id))
                })?;
                if let Some(es) = self
                    .fromfile_expander
                    .expand_to_dict(value)
                    .map_err(|e| e.render(&flag.key))?
                {
                    edits.extend(es);
                }
            }
        }
        if edits.is_empty() {
            Ok(None)
        } else {
            Ok(Some(edits))
        }
    }
}
