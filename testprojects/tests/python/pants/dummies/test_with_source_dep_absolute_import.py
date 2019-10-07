from pants.dummies.example_source import add_two


def test_external_method():
    assert add_two(2) == 4
