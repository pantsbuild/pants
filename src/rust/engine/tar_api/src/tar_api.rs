extern crate flate2;
extern crate tar;

use flate2::read::GzDecoder;
use std::fs::File;
use std::path::Path;
use tar::Archive;

pub fn main(tar_path: &Path, output_dir: &Path) -> Result<(), std::io::Error> {
  //  let path = "archive.tar.gz";
  //
  let tar_gz = File::open(tar_path)?;
  let tar = GzDecoder::new(tar_gz);
  let mut archive = Archive::new(tar);
  archive.unpack(output_dir)?;
  //  println!("{:?}\n{:?}", tar_path, output_dir);
  Ok(())
}
