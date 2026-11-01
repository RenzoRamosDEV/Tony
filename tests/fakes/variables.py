from collections.abc import Mapping

from tony.core.config.secrets import Variables


def secret_variables(values: Mapping[str, str]) -> Variables:
    """Variables whose every name counts as a secret, as if all came from config/.env."""
    return Variables(values=dict(values), env_file_values={}, secret_names=frozenset(values))
