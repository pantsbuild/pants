use nails;
use std::path::PathBuf;
use std::process::Command;

/// This is the same as the python type `PantsDaemon.Handle`.
#[derive(Debug)]
struct PantsdHandle {
  pid: u32,
  port: u16,
  metadata_base_dir: String
}

struct PantsCommandSetup {
  python_interpreter_path: String,
  pants_dir: PathBuf,
  argument_list: Vec<String>,
  env: Vec<(String, String)>,
}

/// We expect to invoke this from the `pants` script, with the first argument being the
/// path to the specific python interpreter set up by the venv.
fn main() {
    let mut args = std::env::args();
    args.next();
    let python_interpreter_path = args.next().expect("Expected a path to the pants venv python interpreter");
    //TODO should read PYTHONPATH from config and set it explicitly, instead of being an env var
    let env: Vec<(String, String)> = std::env::vars().collect();

    let pants_dir = PathBuf::from("/home/gregs/code/pants"); //TODO fix this
    let entry_point_file = "src/python/pants/bin/pants_runner.py";
    let python_entry_point = pants_dir.join(entry_point_file)
      .display().to_string();

    let mut argument_list: Vec<String> = vec![python_entry_point];
    for arg in args {
      argument_list.push(arg);
    }
    println!("Effective args: {:?}", argument_list);

    let using_pantsd = argument_list.iter().any(|arg| arg == "--enable-pantsd"); //TODO make this check more robust!

    let setup = PantsCommandSetup {
      python_interpreter_path,
      pants_dir,
      argument_list,
      env
    };

    if using_pantsd {
      run_with_pantsd(setup)
    } else {
      run_locally(setup)
    }
}

fn run_locally(setup: PantsCommandSetup) {
    let child_process = Command::new(setup.python_interpreter_path)
      .current_dir(setup.pants_dir)
      .args(setup.argument_list)
      .envs(setup.env)
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

fn run_with_pantsd(setup: PantsCommandSetup) {
  println!("Running with pantsd");
  std::process::exit(0);
}
