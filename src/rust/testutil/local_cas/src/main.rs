// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use clap::{Arg, Command};
use mock::StubCAS;
use std::io;
use std::io::Read;

#[tokio::main]
async fn main() -> Result<(), String> {
    env_logger::init();
    let mut stdin = io::stdin();

    let matches = &Command::new("local_cas")
        .about("An in-memory implementation of a CAS, to test remote execution utilities.")
        .arg(
            Arg::new("port")
                .long("port")
                .short('p')
                .required(false)
                .num_args(1)
                .help("Port that the CAS should listen to.")
                .default_value("0"),
        )
        .arg(
            Arg::new("instance-name")
                .long("instance-name")
                .short('i')
                .required(false)
                .num_args(1)
                .default_value(""),
        )
        .get_matches();

    let cas = StubCAS::builder()
        .port(*matches.get_one("port").unwrap())
        .instance_name(
            matches
                .get_one::<String>("instance-name")
                .unwrap()
                .to_owned(),
        )
        .build()
        .await;
    println!("Started CAS at address: {}", cas.address());
    println!("Press enter to exit.");
    let _ = stdin.read(&mut [0_u8]).unwrap();
    Ok(())
}
