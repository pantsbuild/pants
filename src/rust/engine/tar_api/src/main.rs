extern crate clap;
extern crate flate2;
extern crate tar_api;

use clap::{App, Arg, SubCommand};
use std::path::PathBuf;
use std::process::exit;

// Small rust tar-cli tool. Used for sanity check purposes.
fn main() {
  let matches = &App::new("tar_api")
    .subcommand(SubCommand::with_name("tar"))
    .subcommand(
      SubCommand::with_name("untar")
        .arg(Arg::with_name("file").required(true).takes_value(true))
        .arg(Arg::with_name("dest").required(true).takes_value(true)),
    ).get_matches();

  if let Some(sub_matches) = matches.subcommand_matches("untar") {
    let tar_file = sub_matches.value_of("file").map(PathBuf::from).unwrap();

    let dest = sub_matches.value_of("dest").map(PathBuf::from).unwrap();

    match tar_api::decompress_tgz(&tar_file, &dest) {
      Ok(_) => {}
      Err(err) => {
        eprintln!("{}", err);
        exit(1)
      }
    };
  }
}
