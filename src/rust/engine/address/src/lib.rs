// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
    clippy::all,
    clippy::default_trait_access,
    clippy::expl_impl_clone_on_copy,
    clippy::if_not_else,
    clippy::needless_continue,
    clippy::unseparated_literal_suffix,
    clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
    clippy::len_without_is_empty,
    clippy::redundant_field_names,
    clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

pub struct AddressInput<'a> {
    pub path: &'a str,
    pub target: Option<&'a str>,
    pub generated: Option<&'a str>,
    pub parameters: Vec<(&'a str, &'a str)>,
}

pub struct SpecInput<'a> {
    /// The address (or literal, if no target/generated/parameters were specified) portion.
    pub address: AddressInput<'a>,
    /// If a spec wildcard was specified (`:` or `::`), its value.
    pub wildcard: Option<&'a str>,
}

peg::parser! {
    grammar parsers() for str {
        rule path() -> &'input str =
            s:$(([^':' | '@' | '#'] / ("@" !parameter()))*) { s }

        rule target_name() -> &'input str
            = quiet!{ s:$([^'#' | '@' | ':']+) { s } }
            / expected!("a non-empty target name to follow a `:`.")

        rule target() -> &'input str =
          // NB: We use `&[_]` to differentiate from a wildcard by ensuring that a non-EOF
          // character follows the `:`.
          ":" &[_] s:target_name() { s }

        rule generated_name() -> &'input str
            = quiet!{ s:$([^'@' | ':']+) { s } }
            / expected!("a non-empty generated target name to follow a `#`.")

        rule generated() -> &'input str = "#" s:generated_name() { s }

        rule parameters() -> Vec<(&'input str, &'input str)>
            = "@" parameters:parameter() ++ "," { parameters }

        rule parameter() -> (&'input str, &'input str)
            = quiet!{ key:$([^'=' | ':']+) "=" value:$([^',' | ':']*) { (key, value) } }
            / expected!("one or more key=value pairs to follow a `@`.")

        rule address() -> AddressInput<'input>
            = path:path() target:target()? generated:generated()? parameters:parameters()? {
                AddressInput {
                    path,
                    target,
                    generated,
                    parameters: parameters.unwrap_or_default(),
                }
            }


        rule wildcard() -> &'input str = s:$("::" / ":") { s }

        pub(crate) rule spec() -> SpecInput<'input>
            = address:address() wildcard:wildcard()? {
                SpecInput {
                    address,
                    wildcard,
                }
            }
    }
}

pub fn parse_address_spec(value: &str) -> Result<SpecInput, String> {
    parsers::spec(value).map_err(|e| format!("Failed to parse address spec `{value}`: {e}"))
}
