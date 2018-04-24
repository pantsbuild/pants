#[macro_use(execute)]
extern crate build_utils;
extern crate cc;

/*

N.B. This build script is invoked by `cargo` by way of this configuration
in our Cargo.toml:

    [project]
    ...
    build = "src/cffi_build.rs"

Within, we use the `gcc` crate to compile the CFFI C sources (`native_engine.c`)
generated by `bootstrap.sh` into a (private) static lib (`libnative_engine_ffi.a`),
which then gets linked into the final `cargo build` product (the native engine binary).
This process mixes the Python module initialization function and other symbols into the
native engine binary, allowing us to address it both as an importable python module
(`from _native_engine import X`) as well as a C library (`ffi.dlopen(native_engine.so)`).

*/

use std::fs;
use std::io::{Read, Result};
use std::path::{Path, PathBuf};

use build_utils::BuildRoot;

fn main() {
  // We depend on grpcio, which uses C++.
  // On Linux, with g++, some part of that compilation depends on
  // __gxx_personality_v0 which is present in the C++ standard library.
  // I don't know why. It shouldn't, and before grpcio 0.2.0, it didn't.
  //
  // So we need to link against the C++ standard library. Nothing under us
  // in the dependency tree appears to export this fact.
  // Ideally, we would be linking dynamically, because statically linking
  // against libstdc++ is kind of scary. But we're only doing it to pull in a
  // bogus symbol anyway, so what's the worst that can happen?
  //
  // The only way I can find to dynamically link against libstdc++ is to pass
  // `-C link-args=lstdc++` to rustc, but we can only do this from a
  // .cargo/config file, which applies that argument to every compile/link which
  // happens in a subdirectory of that directory, which isn't what we want to do.
  // So we'll statically link. Because what's the worst that can happen?
  //
  // The following do not work:
  //  * Using the link argument in Cargo.toml to specify stdc++.
  //  * Specifying `rustc-flags=-lstdc++`
  //    (which is equivalent to `-ldylib=stdc++`).
  //  * Specifying `rustc-link-lib=stdc++`
  //    (which is equivalent to `rustc-link-lib=dylib=stdc++).
  if cfg!(target_os = "linux") {
    println!("cargo:rustc-link-lib=static=stdc++");
  }

  // Generate the cffi c sources.
  let build_root = BuildRoot::find().unwrap();
  let cffi_bootstrapper = build_root.join("build-support/bin/native/bootstrap_cffi.sh");

  // N.B. The filename of this source code - at generation time - must line up 1:1 with the
  // python import name, as python keys the initialization function name off of the import name.
  let cffi_dir = Path::new("src/cffi");
  let c_path = mark_for_change_detection(cffi_dir.join("native_engine.c"));
  let env_script_path = mark_for_change_detection(cffi_dir.join("native_engine.cflags"));

  execute!(cffi_bootstrapper, cffi_dir);

  // Now compile the cffi c sources.
  let mut config = cc::Build::new();

  config.file(c_path.to_str().unwrap());
  for flag in make_flags(env_script_path).unwrap() {
    config.flag(flag.as_str());
  }

  // cffi generates missing field initializers :(
  config.flag("-Wno-missing-field-initializers");

  config.compile("libnative_engine_ffi.a");
}

fn mark_for_change_detection(path: PathBuf) -> PathBuf {
  // Restrict re-compilation check to just our input files.
  // See: http://doc.crates.io/build-script.html#outputs-of-the-build-script
  println!("cargo:rerun-if-changed={}", path.to_str().unwrap());
  path
}

fn make_flags(env_script_path: PathBuf) -> Result<Vec<String>> {
  let mut contents = String::new();
  fs::File::open(env_script_path)?.read_to_string(&mut contents)?;
  // It would be a shame if someone were to include a space in an actual quoted value.
  // If they did that, I guess we'd need to implement shell tokenization or something.
  return Ok(
    contents
      .trim()
      .split_whitespace()
      .map(str::to_owned)
      .collect(),
  );
}
