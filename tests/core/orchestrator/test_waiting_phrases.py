import random

from tony.core.orchestrator.waiting_phrases import ORIGINAL_PHRASE, WAITING_PHRASES, WaitingPhrases

MAX_SPOKEN_LENGTH = 60


def test_there_are_exactly_fifty_phrases():
    assert len(WAITING_PHRASES) == 50


def test_phrases_are_unique():
    assert len(set(WAITING_PHRASES)) == len(WAITING_PHRASES)


def test_phrases_are_clean_single_line_text():
    for phrase in WAITING_PHRASES:
        assert phrase and phrase == phrase.strip()
        assert "\n" not in phrase and "\r" not in phrase


def test_phrases_are_short_enough_to_speak():
    assert max(len(phrase) for phrase in WAITING_PHRASES) <= MAX_SPOKEN_LENGTH


def test_original_phrase_is_included():
    assert ORIGINAL_PHRASE == "Un momento, señor; estoy en ello."
    assert ORIGINAL_PHRASE in WAITING_PHRASES


def test_every_phrase_addresses_the_user_formally():
    assert all("señor" in phrase.lower() for phrase in WAITING_PHRASES)


def test_chooser_receives_the_phrases_and_its_pick_is_returned():
    seen = []

    def choose(options):
        seen.append(tuple(options))
        return options[7]

    assert WaitingPhrases(choose).next() == WAITING_PHRASES[7]
    assert seen == [WAITING_PHRASES]


def test_never_repeats_the_previous_phrase_even_if_the_chooser_tries():
    phrases = WaitingPhrases(lambda options: options[0])

    picks = [phrases.next() for _ in range(5)]

    assert all(a != b for a, b in zip(picks, picks[1:], strict=False))
    assert all(pick in WAITING_PHRASES for pick in picks)


def test_first_pick_may_be_any_phrase():
    assert WaitingPhrases(lambda options: options[0]).next() == WAITING_PHRASES[0]


def test_default_chooser_is_random_and_never_repeats():
    phrases = WaitingPhrases(random.Random(1).choice)

    picks = [phrases.next() for _ in range(200)]

    assert all(a != b for a, b in zip(picks, picks[1:], strict=False))
    assert len(set(picks)) > 10
