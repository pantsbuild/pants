// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::Scope;
use lazy_static::lazy_static;
use regex::Regex;
use std::collections::{HashMap, HashSet};

lazy_static! {
    static ref VALID_ALIAS_RE: Regex = Regex::new(r"^(--)?\w(\w|-)*\w$").unwrap();
}

fn validate_alias(
    known_scopes: &HashSet<String>,
    known_flags: &HashMap<String, HashSet<String>>,
    alias: &str,
) -> Result<(), String> {
    if !VALID_ALIAS_RE.is_match(alias) {
        return Err(format!(
            "Invalid alias in `[cli].alias` option: {}. May only contain alphanumerical \
            letters and the separators `-` and `_`. Flags can be defined using `--`. \
            A single dash is not allowed.",
            alias
        ));
    }

    if known_scopes.contains(alias) {
        return Err(format!(
            "Invalid alias in `[cli].alias` option: {}. This is already a registered goal or subsytem.",
            alias
        ));
    };

    for (scope, args) in known_flags.iter() {
        if args.contains(alias) {
            return Err(format!(
                "Invalid alias in `[cli].alias` option: {}. This is already a registered flag in the {} scope.",
                alias, Scope::named(scope).name()
            ));
        }
    }
    Ok(())
}

fn recursive_expand(
    definitions: &HashMap<String, Vec<String>>,
    definition: &Vec<String>,
    trail: &mut Vec<String>,
) -> Result<Vec<String>, String> {
    let mut ret: Vec<String> = vec![];
    for arg in definition {
        if let Some(defn) = definitions.get(arg) {
            trail.push(arg.to_owned());
            if trail.iter().position(|x| x == arg).unwrap() < trail.len() - 1 {
                return Err(format!(
                    "CLI alias cycle detected in `[cli].alias` option:\n{}",
                    trail.join(" -> ")
                ));
            }
            ret.extend(recursive_expand(definitions, defn, trail)?);
            trail.pop();
        } else {
            ret.push(arg.to_owned());
        }
    }
    Ok(ret)
}

pub type AliasMap = HashMap<String, Vec<String>>;

#[allow(dead_code)]
pub fn create_alias_map(
    known_scopes: &HashSet<String>,
    known_flags: &HashMap<String, HashSet<String>>,
    aliases: &HashMap<String, String>,
) -> Result<AliasMap, String> {
    let definitions: AliasMap = aliases
        .iter()
        .map(|(k, v)| {
            validate_alias(known_scopes, known_flags, k)?;
            if let Some(vs) = shlex::split(v) {
                Ok((k.to_owned(), vs))
            } else {
                Err(format!("Couldn't shlex string: {}", v))
            }
        })
        .collect::<Result<_, _>>()?;
    definitions
        .iter()
        .map(|(alias, definition)| {
            Ok((
                alias.to_owned(),
                recursive_expand(&definitions, definition, &mut vec![])?,
            ))
        })
        .collect()
}

pub fn expand_aliases<I: IntoIterator<Item = String>>(
    arg_strs: I,
    alias_map: &AliasMap,
) -> Vec<String> {
    let mut expanded_args: Vec<String> = vec![];
    let mut expand = true;
    for arg_str in arg_strs {
        if arg_str == "--" {
            // Don't expand passthrough args (but make sure we still add them to expanded_args).
            expand = false;
        }
        expanded_args.push(arg_str);
        if expand {
            if let Some(replacement) = alias_map.get(expanded_args.last().unwrap()) {
                expanded_args.pop();
                expanded_args.extend(replacement.clone())
            }
        }
    }
    expanded_args
}
