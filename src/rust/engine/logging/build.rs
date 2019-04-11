use std::fs::File;
use std::io::Write;
use std::path::PathBuf;

fn main() {
  let manifest_path = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap())
    .parent()
    .unwrap()
    .join("Cargo.toml");
  println!("cargo:rerun-if-changed={}", manifest_path.display());
  let config = cargo::util::config::Config::default().unwrap();
  let workspace = cargo::core::Workspace::new(&manifest_path, &config).unwrap();
  let packages: Vec<_> = workspace
    .members()
    .map(|package| package.name().to_string())
    .collect();
  let mut out_file =
    File::create(PathBuf::from(std::env::var("OUT_DIR").unwrap()).join("packages.rs")).unwrap();
  writeln!(
    out_file,
    "pub const PANTS_PACKAGE_NAMES: &[&str] = &["
  )
  .unwrap();
  for package in packages {
    writeln!(out_file, "  \"{}::\",", package).unwrap();
  }
  writeln!(out_file, "];").unwrap();
}
