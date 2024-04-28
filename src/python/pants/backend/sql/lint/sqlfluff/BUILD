resource(name="lockfile", source="sqlfluff.lock")

python_sources(
    overrides={"subsystem.py": {"dependencies": [":lockfile"]}},
)

python_tests(
    name="tests",
)
