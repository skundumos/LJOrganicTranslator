"""Pure-function unit tests (no FFmpeg or external API calls)."""
from app.services.tts_elevenlabs import _split_sentences, _expected_duration
from app.services.translator import _parse_json, _strip_code_fences, _lint_overlay


def test_split_sentences_short():
    out = _split_sentences("Hello world. This is great! Buy now.")
    assert len(out) == 3
    assert all(len(c) < 250 for c in out)


def test_split_sentences_hard_wrap_for_long_chunk():
    text = ("This is one super long sentence with no punctuation that should be wrapped "
            "across word boundaries because elevenlabs does not handle very long requests well " * 5)
    out = _split_sentences(text)
    assert all(len(c) <= 250 for c in out)
    assert len(out) >= 2


def test_expected_duration_floor():
    assert _expected_duration("") >= 0.5
    assert _expected_duration("hello world") > 0.5


def test_parse_json_strips_fences():
    raw = '```json\n{"text": "नमस्ते"}\n```'
    assert _parse_json(raw) == {"text": "नमस्ते"}


def test_parse_json_picks_first_object():
    raw = 'sure, here it is:\n{"text": "Hello"}\nlet me know if...'
    assert _parse_json(raw) == {"text": "Hello"}


def test_lint_overlay_strips_devanagari_digits():
    out = _lint_overlay("₹१,४९९ में पाएं", "₹1,499 right now")
    assert "१" not in out and "1" in out
