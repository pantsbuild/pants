extern crate flate2;
extern crate tar;

use std::fs::File;
use std::path::Path;
use flate2::read::GzDecoder;
use tar::Archive;

pub fn main(
  tar_path: &Path,
  output_dir: &Path,
) -> Result<(), std::io::Error> {
//  let path = "archive.tar.gz";
//
//  let tar_gz = File::open(path)?;
//  let tar = GzDecoder::new(tar_gz);
//  let mut archive = Archive::new(tar);
//  archive.unpack(".")?;
  println!("{:?}\n{:?}", tar_path, output_dir);
  Ok(())
}