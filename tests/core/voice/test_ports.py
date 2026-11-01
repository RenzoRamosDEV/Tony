from tony.core.voice.ports import INPUT_RATE, OUTPUT_RATE, WINDOW_BYTES, WINDOW_SAMPLES, Clip


def test_audio_formats():
    assert (INPUT_RATE, OUTPUT_RATE, WINDOW_SAMPLES, WINDOW_BYTES) == (16_000, 24_000, 512, 2048)


def test_clip_defaults_to_the_output_rate():
    assert Clip(b"x") == Clip(pcm=b"x", rate=24_000)
