python_requirements(
    name="reqs",
    source="requirements.in",
    resolve="bug1",
)

python_test(
    name="test",
    source="test_multi_extras_bug.py",
    resolve="bug1",
    # Two req_strings for pkg-a: one without extras, one with.
    # PEX satisfies pkg-a from the no-extras entry first →
    # pkg-a[x,y,z] is treated as already resolved →
    # pkg-c, pkg-d, pkg-e are never added to the PEX.
    dependencies=[":reqs#pkg-a"],
)
