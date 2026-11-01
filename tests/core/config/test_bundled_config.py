from pathlib import Path

from tony.core.config.settings import CONFIG_FILE, TonyConfig, load_config

REPO = Path(__file__).resolve().parents[3]


def test_bundled_tony_yaml_documents_the_defaults():
    assert (REPO / CONFIG_FILE).is_file()
    assert load_config(REPO) == TonyConfig()
