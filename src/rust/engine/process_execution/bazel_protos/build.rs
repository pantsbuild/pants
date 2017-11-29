use std::env::home_dir;
use std::process::{Command, exit};

fn main() {
  println!("cargo:rerun-if-changed=../../../../../3rdparty/protobuf");
  println!("cargo:rerun-if-changed=generate-grpc.sh");

  let cachedir = home_dir().unwrap().join(".cache").join("pants").join("rust").join("cargo").join("bin");
  println!("cargo:rerun-if-changed={}", cachedir.join("grpc_rust_plugin").to_str().unwrap());
  println!("cargo:rerun-if-changed={}", cachedir.join("protoc-gen-rust").to_str().unwrap());

  let output = Command::new("./generate-grpc.sh").output().unwrap();

  print!("{}", String::from_utf8(output.stdout).unwrap());
  eprint!("{}", String::from_utf8(output.stderr).unwrap());
  exit(output.status.code().unwrap());
}
