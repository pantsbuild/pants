# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from example.tensorflow_custom_op.zero_out_custom_op import zero_out_module


def main():
  zeroed = dir(zero_out_module())
  print(f'op lib: {zeroed}')


if __name__ == '__main__':
  main()
