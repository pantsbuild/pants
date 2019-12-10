# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.interpreter_selection_utils import PY_2 as PY_2  # noqa
from pants.testutil.interpreter_selection_utils import PY_3 as PY_3  # noqa
from pants.testutil.interpreter_selection_utils import PY_27 as PY_27  # noqa
from pants.testutil.interpreter_selection_utils import PY_36 as PY_36  # noqa
from pants.testutil.interpreter_selection_utils import PY_37 as PY_37  # noqa
from pants.testutil.interpreter_selection_utils import has_python_version as has_python_version  # noqa
from pants.testutil.interpreter_selection_utils import (
  python_interpreter_path as python_interpreter_path,
)  # noqa
from pants.testutil.interpreter_selection_utils import (
  skip_unless_all_pythons_present as skip_unless_all_pythons_present,
)  # noqa
from pants.testutil.interpreter_selection_utils import (
  skip_unless_python3_present as skip_unless_python3_present,
)  # noqa
from pants.testutil.interpreter_selection_utils import (
  skip_unless_python27_and_python3_present as skip_unless_python27_and_python3_present,
)  # noqa
from pants.testutil.interpreter_selection_utils import (
  skip_unless_python27_and_python36_present as skip_unless_python27_and_python36_present,
)  # noqa
from pants.testutil.interpreter_selection_utils import (
  skip_unless_python27_present as skip_unless_python27_present,
)  # noqa
from pants.testutil.interpreter_selection_utils import (
  skip_unless_python36_and_python37_present as skip_unless_python36_and_python37_present,
)  # noqa
from pants.testutil.interpreter_selection_utils import (
  skip_unless_python36_present as skip_unless_python36_present,
)  # noqa
from pants_test.deprecated_testinfra import deprecated_testinfra_module


deprecated_testinfra_module()
