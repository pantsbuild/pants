// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::scope::Scope;

use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

static VALID_ALIAS_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^((--)?\w(\w|-)*\w)(=(\w|-|_)+)?$").expect("compile VALID_ALIAS_RE")
});
const ALIAS_NAME_CAPTURE_INDEX: usize = 1;
const ALIAS_METAVAR_CAPTURE_INDEX: usize = 4;

const METAVAR_SENTINNEL: &str = "__PANTS_METAVAR__";

#[derive(Debug, Eq, PartialEq, Hash)]
pub enum AliasExpansion {
    Bare(Vec<String>),
    WithParameter(Vec<String>),
}

#[derive(Debug, Eq, PartialEq)]
pub struct AliasMap(pub HashMap<String, AliasExpansion>);

fn construct_alias_expansion(
    known_scopes_to_flags: Option<&HashMap<String, HashSet<String>>>,
    alias_spec: &str,
    alias_expansion: &str,
) -> Result<(String, AliasExpansion), String> {
    let Some(alias_captures) = VALID_ALIAS_RE.captures(alias_spec) else {
        return Err(format!(
            "Invalid alias in `[cli].alias` option: {alias_spec}. May only contain alphanumerical \
            letters and the separators `-` and `_`. Flags can be defined using `--`. \
            A single dash is not allowed. For flags, an optional parameter may be included by \
            appending `=METAVAR` (for your choice of METAVAR) to the flag name and including \
            $METAVAR or ${{METAVAR}} in the expansion to mark where it should be inserted.",
        ));
    };

    let alias = alias_captures
        .get(ALIAS_NAME_CAPTURE_INDEX)
        .expect("alias name")
        .as_str();

    if let Some(known_scopes_to_flags) = known_scopes_to_flags {
        for (scope, args) in known_scopes_to_flags.iter() {
            if scope == alias {
                return Err(format!(
                    "Invalid alias in `[cli].alias` option: {alias}. This is already a registered goal or subsytem."
                ));
            }
            if args.contains(alias) {
                return Err(format!(
                    "Invalid alias in `[cli].alias` option: {alias}. This is already a registered flag in the {} scope.",
                    Scope::named(scope).name()
                ));
            }
        }
    }

    let value = match (
        alias_captures.get(ALIAS_METAVAR_CAPTURE_INDEX),
        shlex::split(alias_expansion),
    ) {
        (_, None) => Err(format!(
            "Invalid value in `[cli].alias` option: {alias}. Failed to split according to shell rules: {alias_expansion}"
        )),
        (Some(_), _) if !alias.starts_with("--") => Err(format!(
            "Invalid alias in `[cli].alias` option: {alias}. Only flag-type aliases may define a replacement parameter.",
        )),
        (Some(alias_metavar), Some(vs)) => {
            let alias_metavar = &alias_metavar.as_str()[1..];

            let re_escaped_alias_metavar = regex::escape(alias_metavar);
            let marker_re = Regex::new(&format!(r"(\${re_escaped_alias_metavar})\W?")).unwrap();

            let mut args = Vec::with_capacity(vs.len());
            for v in vs {
                let mut v_with_sentinels = v.clone();
                loop {
                    let Some(captures) = marker_re.captures(&v_with_sentinels) else {
                        break;
                    };
                    v_with_sentinels
                        .replace_range(captures.get(1).unwrap().range(), METAVAR_SENTINNEL);
                }
                args.push(
                    v_with_sentinels.replace(&format!("${{{alias_metavar}}}"), METAVAR_SENTINNEL),
                );
            }

            Ok(AliasExpansion::WithParameter(args))
        }
        (None, Some(vs)) => Ok(AliasExpansion::Bare(vs)),
    };

    Ok((alias.to_string(), value?))
}

fn recursive_expand(
    definitions: &HashMap<String, AliasExpansion>,
    definition: &AliasExpansion,
    trail: &mut Vec<String>,
) -> Result<AliasExpansion, String> {
    let (args, contains_metavars) = match definition {
        AliasExpansion::Bare(xs) => (xs, false),
        AliasExpansion::WithParameter(xs) => (xs, true),
    };

    let mut ret: Vec<String> = vec![];
    for arg in args {
        let Some(alias_matcher) = VALID_ALIAS_RE.captures(arg) else {
            ret.push(arg.to_owned());
            continue;
        };

        let alias_name = alias_matcher
            .get(ALIAS_NAME_CAPTURE_INDEX)
            .unwrap()
            .as_str();

        if let Some(defn) = definitions.get(alias_name) {
            trail.push(alias_name.to_owned());
            if trail.iter().position(|x| x == alias_name).unwrap() < trail.len() - 1 {
                return Err(format!(
                    "CLI alias cycle detected in `[cli].alias` option:\n{}",
                    trail.join(" -> ")
                ));
            }
            let expanded_form = recursive_expand(definitions, defn, trail)?;
            match &expanded_form {
                AliasExpansion::Bare(args) => ret.extend(args.clone()),
                AliasExpansion::WithParameter(_) => {
                    // No support for nestedt flag-like aliases with replacement parameters.
                    return Err(format!(
                        "Nested CLI aliases may not refer to a flag-type alias which expects a replacement parameter:\n{}",
                        trail.join(" -> ")
                    ));
                }
            }
            trail.pop();
        } else {
            ret.push(arg.to_owned());
        }
    }

    if contains_metavars {
        Ok(AliasExpansion::WithParameter(ret))
    } else {
        Ok(AliasExpansion::Bare(ret))
    }
}

#[allow(dead_code)]
pub fn create_alias_map(
    known_scopes_to_flags: Option<&HashMap<String, HashSet<String>>>,
    aliases: &HashMap<String, String>,
) -> Result<AliasMap, String> {
    let definitions = AliasMap(
        aliases
            .iter()
            .map(|(k, v)| construct_alias_expansion(known_scopes_to_flags, k, v))
            .collect::<Result<_, _>>()?,
    );
    definitions
        .0
        .iter()
        .map(|(alias, definition)| {
            Ok((
                alias.to_owned(),
                recursive_expand(&definitions.0, definition, &mut vec![])?,
            ))
        })
        .collect::<Result<_, _>>()
        .map(AliasMap)
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
            let Some(alias_captures) = VALID_ALIAS_RE.captures(expanded_args.last().unwrap())
            else {
                continue;
            };

            let Some(alias_name) = alias_captures.get(ALIAS_NAME_CAPTURE_INDEX) else {
                continue;
            };

            match alias_map.0.get(alias_name.as_str()) {
                Some(AliasExpansion::Bare(replacement)) => {
                    expanded_args.pop();
                    expanded_args.extend(replacement.clone());
                }
                Some(AliasExpansion::WithParameter(replacement)) => {
                    let metavar_value = alias_captures
                        .get(ALIAS_METAVAR_CAPTURE_INDEX)
                        .map(|s| s.as_str()[1..].to_string())
                        .unwrap_or_default();

                    expanded_args.pop();
                    for v in replacement {
                        expanded_args.push(v.replace(METAVAR_SENTINNEL, &metavar_value));
                    }
                }
                _ => (),
            }
        }
    }
    expanded_args
}
