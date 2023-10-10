# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import psutil

if __name__ == "__main__":
    print(f"Running on {psutil.cpu_count()} CPUs")
