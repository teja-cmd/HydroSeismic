from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend import main


class StatePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_state_file = main.STATE_FILE

    def tearDown(self) -> None:
        main.STATE_FILE = self.original_state_file

    def test_save_state_replaces_state_atomically(self) -> None:
        with TemporaryDirectory() as directory:
            main.STATE_FILE = Path(directory) / "state.json"

            main.save_state({"version": 1})

            self.assertEqual(json.loads(main.STATE_FILE.read_text(encoding="utf-8")), {"version": 1})
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_failed_replace_preserves_previous_state_and_cleans_temp(self) -> None:
        with TemporaryDirectory() as directory:
            main.STATE_FILE = Path(directory) / "state.json"
            main.STATE_FILE.write_text('{"version":1}', encoding="utf-8")

            with patch("backend.main.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    main.save_state({"version": 2})

            self.assertEqual(main.STATE_FILE.read_text(encoding="utf-8"), '{"version":1}')
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()