// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
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

use clap::{Arg, Command};
use mock::StubCAS;
use std::io;
use std::io::Read;

fn main() -> Result<(), String> {
    env_logger::init();
    let mut stdin = io::stdin();

    let matches = &Command::new("local_cas")
        .about("An in-memory implementation of a CAS, to test remote execution utilities.")
        .arg(
            Arg::new("port")
                .long("port")
                .short('p')
                .required(false)
                .takes_value(true)
                .help("Port that the CAS should listen to.")
                .default_value("0"),
        )
        .arg(
            Arg::new("instance-name")
                .long("instance-name")
                .short('i')
                .required(false)
                .takes_value(true)
                .default_value(""),
        )
        .get_matches();

    let cas = StubCAS::builder()
        .port(
            matches
                .value_of("port")
                .unwrap()
                .parse::<u16>()
                .expect("port must be a non-negative number"),
        )
        .instance_name(matches.value_of("instance-name").unwrap().to_owned())
        .build();
    println!("Started CAS at address: {}", cas.address());
    println!("Press enter to exit.");
    let _ = stdin.read(&mut [0_u8]).unwrap();
    Ok(())
}
