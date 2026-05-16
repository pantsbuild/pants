python_requirements(
    name="reqs",
    source="requirements.in",
    resolve="bug2",
)

python_test(
    name="test",
    source="test_transitive_extras_bug.py",
    resolve="bug2",
    # pkg-f → pkg-g → pkg-h[myextra] → pkg-i  (extras at depth 2 from BUILD dep)
    # pkg-j → pkg-h (no extras)                 (competing path to pkg-h)
    # If PEX satisfies pkg-h from pkg-j first (without [myextra]),
    # pkg-i will be absent from requirements.pex.
    dependencies=[":reqs#pkg-f", ":reqs#pkg-j"],
)
