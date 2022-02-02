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
}

peg::parser! {
    grammar relative_address_parser() for str {
        rule path() -> &'input str = s:$([^':' | '#']*) {s}

        rule target_name() -> &'input str
            = quiet!{ s:$([^'#' | '@']+) { s } }
            / expected!("a non-empty target name to follow a `:`.")

        rule target() -> &'input str = ":" s:target_name() { s }

        rule generated_name() -> &'input str
            = quiet!{ s:$([_]+) { s } }
            / expected!("a non-empty generated target name to follow a `#`.")

        rule generated() -> &'input str = "#" s:generated_name() { s }

        pub(crate) rule relative_address() -> AddressInput<'input>
            = path:path() target:target()? generated:generated()? {
                AddressInput {
                    path,
                    target,
                    generated,
                }
            }
    }
}

pub fn parse_address(value: &str) -> Result<AddressInput, String> {
  let relative_address = relative_address_parser::relative_address(value)
    .map_err(|e| format!("Failed to parse Address `{value}`: {e}"))?;

  Ok(relative_address)
}
