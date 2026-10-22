"""System prompt and prompt-building behaviour.

The Tanglish-only rule and the conversation modes are core product behaviour,
so they are asserted here rather than trusted to the model.
"""

from __future__ import annotations

from app.services.prompt_service import PromptService


def test_prompt_file_exists_and_loads():
    service = PromptService()
    assert len(service.base_prompt) > 400
    assert "{name}" in service.base_prompt  # name is injected at request time


def test_tanglish_rules_are_present():
    text = PromptService().base_prompt.lower()
    assert "tanglish" in text
    assert "never output tamil script" in text
    assert "romanized" in text or "romanised" in text
    assert "english letters" in text


def test_prompt_forbids_claiming_humanity():
    text = " ".join(PromptService().base_prompt.split())
    assert "Never claim to be human" in text
    assert "real human feelings" in text


def test_prompt_avoids_generic_filler():
    text = PromptService().base_prompt
    assert "How can I assist you today?" in text  # explicitly banned in prompt
    assert "generic greetings" in text.lower()


def test_mode_directives_appear_in_system_prompt():
    service = PromptService()
    for mode in ("friendly", "respectful", "playful", "supportive", "focused"):
        prompt = service.system_prompt(mode)
        assert f"MODE: {mode}" in prompt
        # The base prompt is included with the name substituted.
        assert service.apply_name(service.base_prompt, None) in prompt


def test_default_name_is_used_when_none_given():
    service = PromptService()
    prompt = service.system_prompt("friendly")
    assert "You are Gethu," in prompt
    assert "{name}" not in prompt


def test_custom_name_replaces_the_placeholder():
    service = PromptService()
    prompt = service.system_prompt("friendly", "Mithu")
    assert "You are Mithu," in prompt
    assert "{name}" not in prompt
    assert "Your name is Mithu." in prompt


def test_name_is_sanitised_so_it_cannot_alter_the_prompt():
    service = PromptService()
    prompt = service.system_prompt("friendly", "Bad\nName {injected}")
    assert "Bad Name (injected)" in prompt
    # The name may not carry a brace through, so it cannot close a placeholder.
    assert "{injected}" not in prompt
    # The name may not carry a newline through, so it cannot start a new
    # instruction line in the prompt.
    safe = service.apply_name("{name}", "Bad\nName {injected}")
    assert safe == "Bad Name (injected)"
    assert "\n" not in safe


def test_blank_name_falls_back_to_the_default():
    service = PromptService()
    assert "You are Gethu," in service.system_prompt("friendly", "   ")


def test_unknown_mode_falls_back_to_friendly():
    service = PromptService()
    assert "MODE: friendly" in service.system_prompt("banana")


def test_build_contents_maps_roles_for_gemini():
    service = PromptService()
    contents = service.build_contents(
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hey"}],
        "new question",
    )
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model"  # Gemini's name for assistant turns
    assert contents[-1] == {"role": "user", "parts": [{"text": "new question"}]}


def test_build_contents_trims_history_but_keeps_new_message():
    service = PromptService()
    history = [{"role": "user", "content": f"msg {i}"} for i in range(50)]
    contents = service.build_contents(history, "latest", limit=10)
    assert len(contents) == 10  # 9 history turns + the new one
    assert contents[-1]["parts"][0]["text"] == "latest"


def test_build_contents_puts_attachments_before_text():
    service = PromptService()
    part = {"inline_data": {"mime_type": "image/png", "data": b"..."}}
    contents = service.build_contents([], "what is this?", [part])
    parts = contents[-1]["parts"]
    assert parts[0] is part
    assert parts[-1]["text"] == "what is this?"


def test_missing_prompt_file_falls_back_gracefully(tmp_path):
    service = PromptService(tmp_path / "nope.txt")
    assert "Gethu" in service.system_prompt("friendly")
