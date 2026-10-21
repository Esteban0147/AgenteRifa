import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main


class OpenAIKeyConfigurationTests(unittest.TestCase):
    def test_ignores_inherited_key_when_dotenv_key_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("OPENAI_API_KEY=\n", encoding="utf-8")
            with (
                patch.object(main, "ENV_FILE", env_file),
                patch.dict("os.environ", {"OPENAI_API_KEY": "inherited-key"}),
            ):
                self.assertIsNone(main.configured_openai_api_key())

    def test_reads_key_from_project_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("OPENAI_API_KEY=local-key\n", encoding="utf-8")
            with (
                patch.object(main, "ENV_FILE", env_file),
                patch.dict("os.environ", {"OPENAI_API_KEY": "inherited-key"}),
            ):
                self.assertEqual(main.configured_openai_api_key(), "local-key")


if __name__ == "__main__":
    unittest.main()
