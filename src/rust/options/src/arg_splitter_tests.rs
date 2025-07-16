// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::Scope;
use crate::arg_splitter::{ArgSplitter, Args, NO_GOAL_NAME, PantsCommand, UNKNOWN_GOAL_NAME};
use crate::flags::Flag;
use crate::scope::GoalInfo;
use std::fs::File;
use std::path::Path;
use tempfile::TempDir;

fn _sv(v: &[&str]) -> Vec<String> {
    v.iter().map(|s| String::from(*s)).collect()
}

fn shlex_and_split_args(build_root: Option<&Path>, args_str: &str) -> PantsCommand {
    ArgSplitter::new(
        build_root.unwrap_or(TempDir::new().unwrap().path()),
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
    .split_args(Args::new(
        shlex::split(args_str)
            .unwrap()
            .into_iter()
            .skip(1)
            .collect::<Vec<_>>(),
    ))
    // Note that for readability the cmd lines in the test include the arg[0] binary name,
    // which we skip here.
}

#[test]
fn test_spec_detection() {
    #[track_caller]
    fn assert_spec(build_root: Option<&Path>, maybe_spec: &str) {
        assert_eq!(
            PantsCommand {
                builtin_or_auxiliary_goal: Some(NO_GOAL_NAME.to_string()),
                goals: vec![],
                unknown_goals: vec![],
                specs: _sv(&[maybe_spec]),
                flags: vec![],
                passthru: None
            },
            shlex_and_split_args(build_root, &format!("pants {maybe_spec}"))
        );
    }

    #[track_caller]
    fn assert_goal(build_root: Option<&Path>, spec: &str) {
        assert_eq!(
            PantsCommand {
                builtin_or_auxiliary_goal: Some(UNKNOWN_GOAL_NAME.to_string()),
                goals: vec![],
                unknown_goals: _sv(&[spec]),
                specs: vec![],
                flags: vec![],
                passthru: None,
            },
            shlex_and_split_args(build_root, &format!("pants {spec}"))
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
        assert_spec(Some(temp_dir.path()), &format!("-{spec}"));
    }
    for spec in directories_vs_goals {
        assert_goal(Some(temp_dir.path()), spec);
        File::create(temp_dir.path().join(Path::new(spec))).unwrap();
        assert_spec(Some(temp_dir.path()), spec);
        assert_spec(Some(temp_dir.path()), &format!("-{spec}"));
    }
}

#[test]
fn test_valid_arg_splits() {
    #[track_caller]
    fn assert(goals: &[&str], specs: &[&str], flags: &[Flag], args_str: &str) {
        assert_eq!(
            PantsCommand {
                builtin_or_auxiliary_goal: None,
                goals: _sv(goals),
                unknown_goals: vec![],
                specs: _sv(specs),
                flags: flags.iter().map(Flag::clone).collect::<Vec<_>>(),
                passthru: None,
            },
            shlex_and_split_args(None, args_str)
        )
    }

    // Basic arg splitting, various flag combos.

    assert(
        &["check", "test"],
        &[
            "src/java/org/pantsbuild/foo",
            "-src/java/org/pantsbuild/foo/ignore.py",
            "src/java/org/pantsbuild/bar:baz",
            "-folder::",
        ],
        &[
            Flag {
                context: Scope::Global,
                key: "--check-long-flag".to_string(),
                value: None,
            },
            Flag {
                context: Scope::Global,
                key: "--gg".to_string(),
                value: None,
            },
            Flag {
                context: Scope::Global,
                key: "-l".to_string(),
                value: Some("trace".to_string()),
            },
            Flag {
                context: Scope::Scope("check".to_string()),
                key: "--cc".to_string(),
                value: None,
            },
            Flag {
                context: Scope::Scope("test".to_string()),
                key: "--ii".to_string(),
                value: None,
            },
        ],
        "pants --check-long-flag --gg -ltrace check --cc test --ii \
        src/java/org/pantsbuild/foo -src/java/org/pantsbuild/foo/ignore.py \
        src/java/org/pantsbuild/bar:baz -folder::",
    );
    assert(
        &["check", "test"],
        &[
            "-how/about/ignoring/this/spec", // Note: Starts with `-h`.
            "src/java/org/pantsbuild/foo",
            "src/java/org/pantsbuild/bar:baz",
        ],
        &[
            Flag {
                context: Scope::Global,
                key: "--fff".to_string(),
                value: Some("arg".to_string()),
            },
            Flag {
                context: Scope::Scope("check".to_string()),
                key: "--gg-gg".to_string(),
                value: Some("arg-arg".to_string()),
            },
            Flag {
                context: Scope::Scope("test".to_string()),
                key: "--iii".to_string(),
                value: None,
            },
            Flag {
                context: Scope::Scope("test".to_string()),
                key: "--check-long-flag".to_string(),
                value: None,
            },
            Flag {
                context: Scope::Global,
                key: "-l".to_string(),
                value: Some("trace".to_string()),
            },
            Flag {
                context: Scope::Global,
                key: "--another-global".to_string(),
                value: None,
            },
        ],
        "pants -how/about/ignoring/this/spec --fff=arg check --gg-gg=arg-arg test --iii \
        --check-long-flag src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz \
        -ltrace --another-global",
    );

    // Distinguish goals from specs.

    assert(
        &["check", "test"],
        &["foo::"],
        &[],
        "pants check test foo::",
    );
    assert(&["check"], &["test:test"], &[], "pants check test:test");
    assert(&["test"], &["test:test"], &[], "pants test test:test");

    assert(&["test"], &["./test"], &[], "pants test ./test");
    assert(&["test"], &["//test"], &[], "pants test //test");
    assert(&["test"], &["./test.txt"], &[], "pants test ./test.txt");
    assert(
        &["test"],
        &["test/test.txt"],
        &[],
        "pants test test/test.txt",
    );
    assert(&["test"], &["test/test"], &[], "pants test test/test");

    assert(&["test"], &["."], &[], "pants test .");
    assert(&["test"], &["*"], &[], "pants test *");
    assert(&["test"], &["test/*.txt"], &[], "pants test test/*.txt");
    assert(&["test"], &["test/**/*"], &[], "pants test test/**/*");
    assert(&["test"], &["-"], &[], "pants test -");
    assert(&["test"], &["-a/b"], &[], "pants test -a/b");
    assert(&["test"], &["check.java"], &[], "pants test check.java");
}

#[test]
fn test_passthru_args() {
    assert_eq!(
        PantsCommand {
            builtin_or_auxiliary_goal: None,
            goals: _sv(&["test"]),
            unknown_goals: vec![],
            specs: _sv(&["foo/bar"]),
            flags: vec![],
            passthru: Some(_sv(&["-t", "this is the arg"])),
        },
        shlex_and_split_args(None, "pants test foo/bar -- -t 'this is the arg'")
    );

    assert_eq!(
        PantsCommand {
            builtin_or_auxiliary_goal: None,
            goals: _sv(&["check", "test"]),
            unknown_goals: vec![],
            specs: _sv(&[
                "src/java/org/pantsbuild/foo",
                "src/java/org/pantsbuild/bar:baz"
            ]),
            flags: vec![
                Flag {
                    context: Scope::Global,
                    key: "-l".to_string(),
                    value: Some("error".to_string())
                },
                Flag {
                    context: Scope::Global,
                    key: "--fff".to_string(),
                    value: Some("arg".to_string())
                },
                Flag {
                    context: Scope::Scope("check".to_string()),
                    key: "--gg-gg".to_string(),
                    value: Some("arg-arg".to_string())
                },
                Flag {
                    context: Scope::Scope("test".to_string()),
                    key: "--iii".to_string(),
                    value: None,
                },
                Flag {
                    context: Scope::Scope("test".to_string()),
                    key: "--check-long-flag".to_string(),
                    value: None,
                }
            ],
            passthru: Some(_sv(&["passthru1", "passthru2", "-linfo"])),
        },
        shlex_and_split_args(
            None,
            "pants -lerror --fff=arg check --gg-gg=arg-arg test --iii \
                             --check-long-flag src/java/org/pantsbuild/foo \
                             src/java/org/pantsbuild/bar:baz -- passthru1 passthru2 -linfo"
        )
    );

    assert_eq!(
        PantsCommand {
            builtin_or_auxiliary_goal: None,
            goals: _sv(&["check"]),
            unknown_goals: vec![],
            specs: _sv(&["src/java/org/pantsbuild/foo",]),
            flags: vec![
                Flag {
                    context: Scope::Global,
                    key: "-l".to_string(),
                    value: Some("error".to_string())
                },
                Flag {
                    context: Scope::Global,
                    key: "--fff".to_string(),
                    value: Some("arg".to_string())
                },
                Flag {
                    context: Scope::Scope("check".to_string()),
                    key: "--gg-gg".to_string(),
                    value: Some("arg-arg".to_string())
                },
                Flag {
                    context: Scope::Scope("check".to_string()),
                    key: "--check-long-flag".to_string(),
                    value: None
                },
            ],
            passthru: Some(_sv(&[])),
        },
        shlex_and_split_args(
            None,
            "pants -lerror --fff=arg check --gg-gg=arg-arg \
                           --check-long-flag src/java/org/pantsbuild/foo --"
        )
    );
}

#[test]
fn test_split_args_simple() {
    assert_eq!(
        PantsCommand {
            builtin_or_auxiliary_goal: Some(NO_GOAL_NAME.to_string()),
            goals: vec![],
            unknown_goals: vec![],
            specs: vec![],
            flags: vec![],
            passthru: None
        },
        shlex_and_split_args(None, "pants")
    );

    assert_eq!(
        PantsCommand {
            builtin_or_auxiliary_goal: Some("help".to_string()),
            goals: vec![],
            unknown_goals: vec![],
            specs: vec![],
            flags: vec![],
            passthru: None
        },
        shlex_and_split_args(None, "pants help")
    );

    assert_eq!(
        PantsCommand {
            builtin_or_auxiliary_goal: None,
            goals: _sv(&["fmt", "check"]),
            unknown_goals: vec![],
            specs: _sv(&["::"]),
            flags: vec![],
            passthru: None
        },
        shlex_and_split_args(None, "pants fmt check ::")
    );

    assert_eq!(
        PantsCommand {
            builtin_or_auxiliary_goal: None,
            goals: _sv(&["fmt", "check"]),
            unknown_goals: vec![],
            specs: _sv(&["path/to/dir", "file.py", ":target",]),
            flags: vec![
                Flag {
                    context: Scope::Global,
                    key: "-l".to_string(),
                    value: Some("debug".to_string()),
                },
                Flag {
                    context: Scope::Global,
                    key: "--global-flag1".to_string(),
                    value: None,
                },
                Flag {
                    context: Scope::Global,
                    key: "--global-flag2".to_string(),
                    value: Some("val".to_string()),
                },
                Flag {
                    context: Scope::Scope("fmt".to_string()),
                    key: "--scoped-flag1".to_string(),
                    value: None,
                },
                Flag {
                    context: Scope::Scope("check".to_string()),
                    key: "--scoped-flag2".to_string(),
                    value: None,
                }
            ],
            passthru: None
        },
        shlex_and_split_args(
            None,
            "pants -ldebug --global-flag1 --global-flag2=val fmt \
        --scoped-flag1 check --scoped-flag2 path/to/dir file.py :target"
        )
    );

    assert_eq!(
        PantsCommand {
            builtin_or_auxiliary_goal: None,
            goals: _sv(&["run"]),
            unknown_goals: vec![],
            specs: _sv(&["path/to:bin"]),
            flags: vec![Flag {
                context: Scope::Global,
                key: "--global-flag1".to_string(),
                value: None,
            },],
            passthru: None
        },
        shlex_and_split_args(None, "pants --global-flag1 run path/to:bin")
    );

    assert_eq!(
        PantsCommand {
            builtin_or_auxiliary_goal: Some("help".to_string()),
            goals: vec![],
            unknown_goals: vec![],
            specs: vec![],
            flags: vec![],
            passthru: None
        },
        shlex_and_split_args(None, "pants -h")
    );

    assert_eq!(
        PantsCommand {
            builtin_or_auxiliary_goal: Some("help".to_string()),
            goals: _sv(&["test"]),
            unknown_goals: vec![],
            specs: vec![],
            flags: vec![],
            passthru: None
        },
        shlex_and_split_args(None, "pants test --help")
    );

    assert_eq!(
        PantsCommand {
            builtin_or_auxiliary_goal: Some("help".to_string()),
            goals: _sv(&["test"]),
            unknown_goals: vec![],
            specs: vec![],
            flags: vec![],
            passthru: None
        },
        shlex_and_split_args(None, "pants test --help")
    );
}

#[test]
fn test_split_args_short_flags() {
    assert_eq!(
        PantsCommand {
            builtin_or_auxiliary_goal: None,
            goals: _sv(&["run"]),
            unknown_goals: vec![],
            specs: _sv(&["path/to:bin"]),
            flags: vec![Flag {
                context: Scope::Global,
                key: "-l".to_string(),
                value: Some("warn".to_string())
            }],
            passthru: None
        },
        shlex_and_split_args(None, "pants -lwarn run path/to:bin")
    );

    assert_eq!(
        PantsCommand {
            builtin_or_auxiliary_goal: None,
            goals: _sv(&["run"]),
            unknown_goals: vec![],
            // An unknown short flag reads as a negative spec.
            specs: _sv(&["-x", "path/to:bin"]),
            flags: vec![],
            passthru: None
        },
        shlex_and_split_args(None, "pants -x run path/to:bin")
    );
}

#[test]
fn test_help() {
    #[track_caller]
    fn assert_help(args_str: &str, expected_goals: Vec<&str>, expected_specs: Vec<&str>) {
        assert_eq!(
            PantsCommand {
                builtin_or_auxiliary_goal: Some("help".to_string()),
                goals: _sv(&expected_goals),
                unknown_goals: vec![],
                specs: _sv(&expected_specs),
                flags: vec![],
                passthru: None
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
            PantsCommand {
                builtin_or_auxiliary_goal: Some("help-advanced".to_string()),
                goals: _sv(&expected_goals),
                unknown_goals: vec![],
                specs: _sv(&expected_specs),
                flags: vec![],
                passthru: None
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
        PantsCommand {
            builtin_or_auxiliary_goal: Some("help-all".to_string()),
            goals: vec![],
            unknown_goals: vec![],
            specs: vec![],
            flags: vec![],
            passthru: None
        },
        shlex_and_split_args(None, "pants help-all")
    );
}
