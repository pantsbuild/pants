use std::path::PathBuf;
use std::process::Command;

/// This is the same as the python type `PantsDaemon.Handle`.
#[derive(Debug)]
struct PantsdHandle {
  pid: u32,
  port: u16,
  metadata_base_dir: String
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    println!("Args: {:?}", args);

    let env: Vec<(String, String)> = std::env::vars().collect();
    println!("Captured {} env vars", env.len());

    let pants_dir = PathBuf::from("/home/gregs/code/pants");
    let pants_binary = pants_dir.join("pants");

    let using_pantsd = args.iter().any(|arg| arg == "--enable-pantsd"); //TODO make this check more robust!

    println!("Using pantsd: {}", using_pantsd);
    if using_pantsd {
      std::process::exit(0);
    }

    let child_process = Command::new(pants_binary)
      .current_dir(pants_dir)
      .args(args)
      .envs(env)
      .spawn();

    match child_process {
      Ok(mut child) => {
        println!("Running pants from rust!");
        let result = child.wait();
        if let Err(e) = result {
          println!("Another err: {}", e);
        }
      },
      Err(e) => {
        println!("Error executing pants: {}", e)
      }
    }
}
