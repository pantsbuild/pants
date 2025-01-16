// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::arg_splitter::{ArgSplitter, SplitArgs, NO_GOAL_NAME, UNKNOWN_GOAL_NAME};
use crate::scope::GoalInfo;
use shlex;
use std::fs::File;
use std::path::Path;
use tempfile::TempDir;

fn _sv(v: &[&str]) -> Vec<String> {
    v.iter().map(|s| String::from(*s)).collect()
}

fn shlex_and_split_args(build_root: Option<&Path>, args_str: &str) -> SplitArgs {
    ArgSplitter::new(
        &build_root.unwrap_or(TempDir::new().unwrap().path()),
        vec![
            GoalInfo::new("run", false, false, vec![]),
            GoalInfo::new("check", false, false, vec![]),
            GoalInfo::new("fmt", false, false, vec![]),
            GoalInfo::new("test", false, false, vec![]),
            GoalInfo::new("help", true, false, vec!["-h", "--help"]),
            GoalInfo::new("help-advanced", true, false, vec!["--help-advanced"]),
            GoalInfo::new("help-all", true, false, vec![]),
            GoalInfo::new("bsp", false, true, vec![]),
            GoalInfo::new("version", true, false, vec!["-v", "-V"]),
        ],
    )
    .split_args(shlex::split(args_str).unwrap())
}

#[test]
fn test_spec_detection() {
    #[track_caller]
    fn assert_spec(build_root: Option<&Path>, maybe_spec: &str) {
        assert_eq!(
            SplitArgs {
                builtin_or_auxiliary_goal: Some(NO_GOAL_NAME.to_string()),
                goals: vec![],
                unknown_goals: vec![],
                specs: _sv(&[maybe_spec]),
                passthru: vec![]
            },
            shlex_and_split_args(build_root, &format!("pants {}", maybe_spec))
        );
    }

    #[track_caller]
    fn assert_goal(build_root: Option<&Path>, spec: &str) {
        assert_eq!(
            SplitArgs {
                builtin_or_auxiliary_goal: Some(UNKNOWN_GOAL_NAME.to_string()),
                goals: vec![],
                unknown_goals: _sv(&[spec]),
                specs: vec![],
                passthru: vec![]
            },
            shlex_and_split_args(build_root, &format!("pants {}", spec))
        );
    }

    let unambiguous_specs = [
        "a/b/c",
        "a/b/c/",
        "a/b:c",
        "a/b/c.txt",
        ":c",
        "::",
        "a/",
        "./a.txt",
        ".",
        "*",
        "a/b/*.txt",
        "a/b/test*",
        "a/**/*",
        "a/b.txt:tgt",
        "a/b.txt:../tgt",
        "dir#gen",
        "//:tgt#gen",
        "cache.java",
        "cache.tmp.java",
    ];

    let directories_vs_goals = ["foo", "a_b_c"];
    let temp_dir = TempDir::new().unwrap();

    for spec in unambiguous_specs {
        assert_spec(Some(temp_dir.path()), spec);
        assert_spec(Some(temp_dir.path()), &format!("-{}", spec));
    }
    for spec in directories_vs_goals {
        assert_goal(Some(temp_dir.path()), spec);
        File::create(temp_dir.path().join(Path::new(spec))).unwrap();
        assert_spec(Some(temp_dir.path()), spec);
        assert_spec(Some(temp_dir.path()), &format!("-{}", spec));
    }
}

#[test]
fn test_valid_arg_splits() {
    #[track_caller]
    fn assert(goals: &[&str], specs: &[&str], args_str: &str) {
        assert_eq!(
            SplitArgs {
                builtin_or_auxiliary_goal: None,
                goals: _sv(goals),
                unknown_goals: vec![],
                specs: _sv(specs),
                passthru: vec![],
            },
            shlex_and_split_args(None, args_str)
        )
    }

    // Basic arg splitting, various flag combos.

    assert(
        &["check", "test"],
        &[
            "src/java/org/pantsbuild/foo",
            "src/java/org/pantsbuild/bar:baz",
        ],
        "pants --check-long-flag --gg -ltrace check --cc test --ii \
        src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz",
    );
    assert(
        &["check", "test"],
        &[
            "src/java/org/pantsbuild/foo",
            "src/java/org/pantsbuild/bar:baz",
        ],
        "pants --fff=arg check --gg-gg=arg-arg test --iii --check-long-flag \
        src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz -ltrace --another-global",
    );

    // Distinguish goals from specs.

    assert(&["check", "test"], &["foo::"], "pants check test foo::");
    assert(&["check"], &["test:test"], "pants check test:test");
    assert(&["test"], &["test:test"], "pants test test:test");

    assert(&["test"], &["./test"], "pants test ./test");
    assert(&["test"], &["//test"], "pants test //test");
    assert(&["test"], &["./test.txt"], "pants test ./test.txt");
    assert(&["test"], &["test/test.txt"], "pants test test/test.txt");
    assert(&["test"], &["test/test"], "pants test test/test");

    assert(&["test"], &["."], "pants test .");
    assert(&["test"], &["*"], "pants test *");
    assert(&["test"], &["test/*.txt"], "pants test test/*.txt");
    assert(&["test"], &["test/**/*"], "pants test test/**/*");
    assert(&["test"], &["-"], "pants test -");
    assert(&["test"], &["-a/b"], "pants test -a/b");
    assert(&["test"], &["check.java"], "pants test check.java");
}

#[test]
fn test_passthru_args() {
    assert_eq!(
        SplitArgs {
            builtin_or_auxiliary_goal: None,
            goals: _sv(&["test"]),
            unknown_goals: vec![],
            specs: _sv(&["foo/bar"]),
            passthru: _sv(&["-t", "this is the arg"]),
        },
        shlex_and_split_args(None, "pants test foo/bar -- -t 'this is the arg'")
    );

    assert_eq!(
        SplitArgs {
            builtin_or_auxiliary_goal: None,
            goals: _sv(&["check", "test"]),
            unknown_goals: vec![],
            specs: _sv(&[
                "src/java/org/pantsbuild/foo",
                "src/java/org/pantsbuild/bar:baz"
            ]),
            passthru: _sv(&["passthru1", "passthru2", "-linfo"]),
        },
        shlex_and_split_args(
            None,
            "pants -lerror --fff=arg check --gg-gg=arg-arg test --iii \
                             --check-long-flag src/java/org/pantsbuild/foo \
                             src/java/org/pantsbuild/bar:baz -- passthru1 passthru2 -linfo"
        )
    );
}

#[test]
fn test_split_args_simple() {
    assert_eq!(
        SplitArgs {
            builtin_or_auxiliary_goal: Some(NO_GOAL_NAME.to_string()),
            goals: vec![],
            unknown_goals: vec![],
            specs: vec![],
            passthru: vec![]
        },
        shlex_and_split_args(None, "pants")
    );

    assert_eq!(
        SplitArgs {
            builtin_or_auxiliary_goal: Some("help".to_string()),
            goals: vec![],
            unknown_goals: vec![],
            specs: vec![],
            passthru: vec![]
        },
        shlex_and_split_args(None, "pants help")
    );

    assert_eq!(
        SplitArgs {
            builtin_or_auxiliary_goal: None,
            goals: _sv(&["fmt", "check"]),
            unknown_goals: vec![],
            specs: _sv(&["::"]),
            passthru: vec![]
        },
        shlex_and_split_args(None, "pants fmt check ::")
    );

    assert_eq!(
        SplitArgs {
            builtin_or_auxiliary_goal: None,
            goals: _sv(&["fmt", "check"]),
            unknown_goals: vec![],
            specs: _sv(&["path/to/dir", "file.py", ":target",]),
            passthru: vec![]
        },
        shlex_and_split_args(
            None,
            "pants -ldebug --global-flag1 --global-flag2=val fmt \
        --scoped-flag1 check --scoped-flag2 path/to/dir file.py :target"
        )
    );

    assert_eq!(
        SplitArgs {
            builtin_or_auxiliary_goal: None,
            goals: _sv(&["run"]),
            unknown_goals: vec![],
            specs: _sv(&["path/to:bin"]),
            passthru: vec![]
        },
        shlex_and_split_args(None, "pants --global-flag1 run path/to:bin")
    );

    assert_eq!(
        SplitArgs {
            builtin_or_auxiliary_goal: Some("help".to_string()),
            goals: vec![],
            unknown_goals: vec![],
            specs: vec![],
            passthru: vec![]
        },
        shlex_and_split_args(None, "pants -h")
    );

    assert_eq!(
        SplitArgs {
            builtin_or_auxiliary_goal: Some("help".to_string()),
            goals: _sv(&["test"]),
            unknown_goals: vec![],
            specs: vec![],
            passthru: vec![]
        },
        shlex_and_split_args(None, "pants test --help")
    );

    assert_eq!(
        SplitArgs {
            builtin_or_auxiliary_goal: Some("help".to_string()),
            goals: _sv(&["test"]),
            unknown_goals: vec![],
            specs: vec![],
            passthru: vec![]
        },
        shlex_and_split_args(None, "pants test --help")
    );
}

#[test]
fn test_split_args_short_flags() {
    assert_eq!(
        SplitArgs {
            builtin_or_auxiliary_goal: None,
            goals: _sv(&["run"]),
            unknown_goals: vec![],
            specs: _sv(&["path/to:bin"]),
            passthru: vec![]
        },
        shlex_and_split_args(None, "pants -lwarn run path/to:bin")
    );

    assert_eq!(
        SplitArgs {
            builtin_or_auxiliary_goal: None,
            goals: _sv(&["run"]),
            unknown_goals: vec![],
            // An unknown short flag reads as a negative spec.
            specs: _sv(&["-x", "path/to:bin"]),
            passthru: vec![]
        },
        shlex_and_split_args(None, "pants -x run path/to:bin")
    );
}

#[test]
fn test_help() {
    #[track_caller]
    fn assert_help(args_str: &str, expected_goals: Vec<&str>, expected_specs: Vec<&str>) {
        assert_eq!(
            SplitArgs {
                builtin_or_auxiliary_goal: Some("help".to_string()),
                goals: _sv(&expected_goals),
                unknown_goals: vec![],
                specs: _sv(&expected_specs),
                passthru: vec![]
            },
            shlex_and_split_args(None, args_str)
        );
    }

    assert_help("pants help", vec![], vec![]);
    assert_help("pants -h", vec![], vec![]);
    assert_help("pants --help", vec![], vec![]);
    assert_help("pants help test", vec!["test"], vec![]);
    assert_help("pants test help", vec!["test"], vec![]);
    assert_help("pants test --help", vec!["test"], vec![]);
    assert_help("pants --help test", vec!["test"], vec![]);
    assert_help("pants test --help check", vec!["test", "check"], vec![]);
    assert_help(
        "pants test src/foo/bar:baz -h",
        vec!["test"],
        vec!["src/foo/bar:baz"],
    );
    assert_help(
        "pants help src/foo/bar:baz",
        vec![],
        vec!["src/foo/bar:baz"],
    );
    assert_help(
        "pants --help src/foo/bar:baz",
        vec![],
        vec!["src/foo/bar:baz"],
    );

    #[track_caller]
    fn assert_help_advanced(args_str: &str, expected_goals: Vec<&str>, expected_specs: Vec<&str>) {
        assert_eq!(
            SplitArgs {
                builtin_or_auxiliary_goal: Some("help-advanced".to_string()),
                goals: _sv(&expected_goals),
                unknown_goals: vec![],
                specs: _sv(&expected_specs),
                passthru: vec![]
            },
            shlex_and_split_args(None, args_str)
        );
    }

    assert_help_advanced("pants help-advanced", vec![], vec![]);
    assert_help_advanced("pants --help-advanced", vec![], vec![]);
    assert_help_advanced(
        "pants test help-advanced check",
        vec!["test", "check"],
        vec![],
    );
    assert_help_advanced(
        "pants --help-advanced test check",
        vec!["test", "check"],
        vec![],
    );

    assert_help_advanced(
        "pants test help-advanced src/foo/bar:baz",
        vec!["test"],
        vec!["src/foo/bar:baz"],
    );

    assert_help("pants help help-advanced", vec!["help-advanced"], vec![]);
    assert_help_advanced("pants help-advanced help", vec!["help"], vec![]);
    assert_help("pants --help help-advanced", vec!["help-advanced"], vec![]);
    assert_help_advanced("pants --help-advanced help", vec!["help"], vec![]);

    assert_eq!(
        SplitArgs {
            builtin_or_auxiliary_goal: Some("help-all".to_string()),
            goals: vec![],
            unknown_goals: vec![],
            specs: vec![],
            passthru: vec![]
        },
        shlex_and_split_args(None, "pants help-all")
    );
}
