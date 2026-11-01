from tony.core.voice.voices import kokoro_voices


def test_blend_splits_into_voice_names():
    assert kokoro_voices("kokoro/ef_dora,bf_emma") == ("ef_dora", "bf_emma")


def test_single_voice_is_one_tuple():
    assert kokoro_voices("kokoro/em_alex") == ("em_alex",)


def test_three_voice_blend_keeps_order():
    assert kokoro_voices("kokoro/bf_emma,ef_dora,em_alex") == ("bf_emma", "ef_dora", "em_alex")
