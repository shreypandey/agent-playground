from __future__ import annotations

import io
import unittest

from fit_check_agent.native_host import read_native_message, write_native_message


class NativeHostProtocolTests(unittest.TestCase):
    def test_round_trips_native_message(self) -> None:
        stream = io.BytesIO()
        write_native_message(stream, {"action": "list_profiles"})
        stream.seek(0)

        self.assertEqual(read_native_message(stream), {"action": "list_profiles"})


if __name__ == "__main__":
    unittest.main()
