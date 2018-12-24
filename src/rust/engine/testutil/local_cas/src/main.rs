use env_logger;

use clap::{App, Arg};
use mock::StubCAS;
use std::io;
use std::io::Read;

fn main() -> Result<(), String> {
  env_logger::init();
  let mut stdin = io::stdin();

  let matches = &App::new("local_cas")
    .about("An in-memory implementation of a CAS, to test remote execution utilities.")
    .arg(
      Arg::with_name("port")
        .long("port")
        .short("p")
        .required(false)
        .takes_value(true)
        .help("Port that the CAS should listen to.")
        .default_value("0"),
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
    .build();
  println!("Started CAS at address: {}", cas.address());
  println!("Press enter to exit.");
  let _ = stdin.read(&mut [0u8]).unwrap();
  Ok(())
}
