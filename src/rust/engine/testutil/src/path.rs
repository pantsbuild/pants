use std::env;
use std::path::PathBuf;

pub fn find_bash() -> String {
    which("bash")
        .expect("No bash on PATH")
        .to_str()
        .expect("Path to bash not unicode")
        .to_owned()
}

pub fn which(executable: &str) -> Option<PathBuf> {
    if let Some(paths) = env::var_os("PATH") {
        for path in env::split_paths(&paths) {
            let executable_path = path.join(executable);
            if executable_path.exists() && crate::file::is_executable(&executable_path) {
                return Some(executable_path);
            }
        }
    }
    None
}
