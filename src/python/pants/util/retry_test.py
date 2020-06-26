# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
import unittest.mock

from pants.util.retry import retry_on_exception


class RetryTest(unittest.TestCase):
    @unittest.mock.patch("time.sleep", autospec=True, spec_set=True)
    def test_retry_on_exception(self, mock_sleep):
        broken_func = unittest.mock.Mock()
        broken_func.side_effect = OSError("broken")

        with self.assertRaises(OSError):
            retry_on_exception(broken_func, 3, (OSError,))

        self.assertEqual(broken_func.call_count, 3)

    def test_retry_on_exception_immediate_success(self):
        working_func = unittest.mock.Mock()
        working_func.return_value = "works"

        self.assertEqual(retry_on_exception(working_func, 3, (OSError,)), "works")
        self.assertEqual(working_func.call_count, 1)

    @unittest.mock.patch("time.sleep", autospec=True, spec_set=True)
    def test_retry_on_exception_eventual_success(self, mock_sleep):
        broken_func = unittest.mock.Mock()
        broken_func.side_effect = [OSError("broken"), OSError("broken"), "works now"]

        retry_on_exception(broken_func, 3, (OSError,))

        self.assertEqual(broken_func.call_count, 3)

    @unittest.mock.patch("time.sleep", autospec=True, spec_set=True)
    def test_retry_on_exception_not_caught(self, mock_sleep):
        broken_func = unittest.mock.Mock()
        broken_func.side_effect = OSError("broken")

        with self.assertRaises(OSError):
            retry_on_exception(broken_func, 3, (TypeError,))

        self.assertEqual(broken_func.call_count, 1)

    @unittest.mock.patch("time.sleep", autospec=True, spec_set=True)
    def test_retry_default_backoff(self, mock_sleep):
        broken_func = unittest.mock.Mock()
        broken_func.side_effect = OSError("broken")

        with self.assertRaises(OSError):
            retry_on_exception(broken_func, 4, (OSError,))

        mock_sleep.assert_has_calls(
            (unittest.mock.call(0), unittest.mock.call(0), unittest.mock.call(0))
        )
