from pants.dummies.example_transitive_source import add_four


def test_external_method():
    assert add_four(2) == 6
