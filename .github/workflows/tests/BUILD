# COMMENT

shell_sources(name="tests")

def _run_test(filename):
    filepath = build_file_dir() / 'smoke_test_auth_cherry_picker.sh'
    return f"chmod +x {filepath} && {filepath}"



experimental_test_shell_command(
    name="Test auto-cherry-picker prereqs",
    command=_run_test("smoke_test_auth_cherry_picker.sh"),
    tools=["chmod", "cat"],
    execution_dependencies=[
        "//build-support/bin/act:act-at-root",
        "./smoke_test_auth_cherry_picker.sh",
        ".github/workflows/auto-cherry-picker.yaml",
        "//build-support/bin/cherry_pick/package.json:support_files",
        "//build-support/bin/cherry_pick/package-lock.json:support_files",
    ],
    workdir="/",
    timeout=120,
)
