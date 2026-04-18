from codeassay.detection.profiles import load_profiles


def test_all_expected_profiles_load():
    names = {p.name for p in load_profiles()}
    expected = {"claude_code", "copilot", "cursor", "aider", "windsurf", "gpt", "gemini"}
    assert expected <= names


def test_claude_code_matches_co_author_trailer():
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["claude_code"]
    from codeassay.detection.rules import match_message
    commit = {"message": "feat: x\n\nCo-Authored-By: Claude <c@anthropic.com>"}
    assert any(match_message(r, commit) for r in p.message_rules)


def test_copilot_matches_trailer():
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["copilot"]
    from codeassay.detection.rules import match_message
    commit = {"message": "feat: x\n\nCo-Authored-By: GitHub Copilot <copilot@github.com>"}
    assert any(match_message(r, commit) for r in p.message_rules)


def test_gpt_and_gemini_trailers():
    from codeassay.detection.rules import match_message
    profiles = {p.name: p for p in load_profiles()}
    assert any(match_message(r, {"message": "x\n\nCo-Authored-By: ChatGPT <x@openai.com>"})
               for r in profiles["gpt"].message_rules)
    assert any(match_message(r, {"message": "x\n\nCo-Authored-By: Gemini <g@google.com>"})
               for r in profiles["gemini"].message_rules)


def test_cursor_matches_author_email():
    from codeassay.detection.rules import match_author
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["cursor"]
    commit = {"author": "Cursor Agent", "author_email": "cursor-agent@cursor.com"}
    assert any(match_author(r, commit) for r in p.author_rules)


def test_aider_matches_message_prefix():
    from codeassay.detection.rules import match_message
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["aider"]
    assert any(match_message(r, {"message": "aider: refactor foo"}) for r in p.message_rules)


def test_human_commit_matches_no_profile():
    from codeassay.detection.rules import match_message, match_author
    commit = {
        "message": "feat: ordinary human commit",
        "author": "Jane Dev",
        "author_email": "jane@example.com",
    }
    for p in load_profiles():
        assert not any(match_message(r, commit) for r in p.message_rules)
        assert not any(match_author(r, commit) for r in p.author_rules)
