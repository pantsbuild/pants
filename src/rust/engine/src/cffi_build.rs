extern crate gcc;

fn main() {
  gcc::Config::new()
    .file("src/cffi/native_engine.c")
    .compile("libnative_engine_ffi.a");
}
