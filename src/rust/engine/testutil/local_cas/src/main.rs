#[macro_use(value_t)]
extern crate clap;
extern crate env_logger;
extern crate mock;

use clap::{App, Arg};
use mock::StubCAS;
use std::process::exit;

/// TODO:
///   - Implement custom ports as flags
///   - Remove the while(true)
///   - Better logging
///   - Proper error handling

fn main() {
  env_logger::init();

  match execute(
    &App::new("local_cas")
      .about("")
      .arg(Arg::with_name("port").required(false).takes_value(true))
      .get_matches(),
  ) {
    Ok(_) => {}
    Err(err) => {
      eprintln!("{}", err);
      exit(1)
    }
  };
}

fn execute(top_match: &clap::ArgMatches) -> Result<(), String> {
  let cas = StubCAS::empty();
  println!("Started CAS at address: {}", cas.address());
  while true {}
  Ok(())
}
