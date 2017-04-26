import pytest


V = {}


@pytest.fixture(scope='session', autouse=True)
def myfixture():
  V['ok'] = 1
