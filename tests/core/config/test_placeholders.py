import pytest

from tony.core.config.placeholders import (
    SecretMasker,
    UndefinedVariableError,
    resolve_placeholders,
)

VARS = {"HOME": "/home/u", "TOKEN": "s3cr3t", "EMPTY": ""}


class TestResolvePlaceholders:
    def test_resolves_string(self):
        assert resolve_placeholders("${HOME}/notas", VARS) == ("/home/u/notas", {"/home/u"})

    def test_resolves_multiple_variables_in_one_string(self):
        value, used = resolve_placeholders("${HOME}:${TOKEN}:${HOME}", VARS)

        assert value == "/home/u:s3cr3t:/home/u"
        assert used == {"/home/u", "s3cr3t"}

    def test_resolves_list_items(self):
        value, _ = resolve_placeholders(["-y", "${HOME}/notas"], VARS)

        assert value == ["-y", "/home/u/notas"]

    def test_resolves_dict_values_but_not_keys(self):
        value, used = resolve_placeholders({"${TOKEN}": "Bearer ${TOKEN}"}, VARS)

        assert value == {"${TOKEN}": "Bearer s3cr3t"}
        assert used == {"s3cr3t"}

    def test_resolves_nested_structures(self):
        value, _ = resolve_placeholders({"a": ["${TOKEN}", {"b": "${HOME}"}]}, VARS)

        assert value == {"a": ["s3cr3t", {"b": "/home/u"}]}

    @pytest.mark.parametrize(
        "literal", ["plain", "$HOME", "${}", "${1BAD}", "$ {HOME}", "{HOME}", "", None, 7, True]
    )
    def test_literal_without_placeholder_is_unchanged(self, literal):
        assert resolve_placeholders(literal, VARS) == (literal, set())

    def test_empty_variable_resolves_to_empty_string(self):
        assert resolve_placeholders("x${EMPTY}y", VARS) == ("xy", {""})

    def test_undefined_variable_names_variable_without_leaking_values(self):
        with pytest.raises(UndefinedVariableError) as info:
            resolve_placeholders({"a": "${TOKEN}", "b": "${MISSING_VAR}"}, VARS)

        assert info.value.variable == "MISSING_VAR"
        assert "MISSING_VAR" in str(info.value)
        assert "s3cr3t" not in str(info.value)

    def test_does_not_mutate_input(self):
        original = {"a": ["${TOKEN}"]}

        resolve_placeholders(original, VARS)

        assert original == {"a": ["${TOKEN}"]}


class TestSecretMasker:
    def test_masks_registered_value_in_string(self):
        masker = SecretMasker({"s3cr3t"})

        assert masker.mask("token=s3cr3t;again s3cr3t") == "token=***;again ***"

    def test_without_secrets_returns_text_unchanged(self):
        assert SecretMasker().mask("s3cr3t") == "s3cr3t"

    def test_ignores_empty_values(self):
        masker = SecretMasker({""})

        assert masker.mask("abc") == "abc"

    def test_register_adds_values(self):
        masker = SecretMasker()
        masker.register({"one", ""})
        masker.register({"two"})

        assert masker.mask("one two three") == "*** *** three"

    def test_longer_secret_wins_over_its_prefix(self):
        masker = SecretMasker({"abc", "abcdef"})

        assert masker.mask("abcdef abc") == "*** ***"

    def test_masks_nested_json(self):
        masker = SecretMasker({"s3cr3t"})
        data = {"s3cr3t-key": ["a s3cr3t", {"n": 1, "t": "s3cr3t"}], "flag": None}

        assert masker.mask_json(data) == {
            "***-key": ["a ***", {"n": 1, "t": "***"}],
            "flag": None,
        }

    @pytest.mark.parametrize("scalar", [1, 2.5, True, None])
    def test_mask_json_leaves_non_strings(self, scalar):
        assert SecretMasker({"1"}).mask_json(scalar) == scalar
