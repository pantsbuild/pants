from setuptools import setup

setup(
  name = 'not_zipsafe_egg',
  packages = ['lib'],
  zip_safe = False
)
