from codeassay.detection.profiles import load_profiles


def test_all_expected_profiles_load():
    names = {p.name for p in load_profiles()}
    expected = {
        "claude_code", "copilot", "cursor", "aider", "windsurf", "gpt", "gemini",
        # 9 new profiles added in v0.2
        "devin", "codex_cli", "v0_dev", "replit_ai", "continue_dev",
        "cline", "opencode", "amp", "codebuddy",
    }
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


def test_cursor_matches_made_with_trailer():
    from codeassay.detection.rules import match_message
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["cursor"]
    commit = {"message": "feat: improve UI\n\nMade with Cursor"}
    assert any(match_message(r, commit) for r in p.message_rules)


def test_aider_matches_co_authored_by_trailer():
    from codeassay.detection.rules import match_message, match_author
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["aider"]
    commit = {"message": "feat: refactor\n\nCo-authored-by: aider (gpt-4o) <noreply@aider.chat>"}
    assert any(match_message(r, commit) for r in p.message_rules)


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


# ── New profile smoke tests ──────────────────────────────────────────────────


def test_devin_matches_bot_author():
    from codeassay.detection.rules import match_author
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["devin"]
    commit = {
        "author": "devin-ai-integration[bot]",
        "author_email": "devin-ai-integration[bot]@users.noreply.github.com",
    }
    assert any(match_author(r, commit) for r in p.author_rules)


def test_codex_cli_matches_co_authored_by():
    from codeassay.detection.rules import match_message
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["codex_cli"]
    commit = {"message": "fix: patch bug\n\nCo-authored-by: Codex <noreply@openai.com>"}
    assert any(match_message(r, commit) for r in p.message_rules)


def test_v0_dev_profile_exists_with_branch_pattern():
    from codeassay.detection.rules import match_branch
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["v0_dev"]
    # v0 does not add Co-Authored-By; only a branch signal is available
    assert any(match_branch(r, {}, branches=["v0/landing-page-abc123"])
               for r in p.branch_rules)


def test_replit_ai_matches_author_email():
    from codeassay.detection.rules import match_author
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["replit_ai"]
    commit = {"author": "Replit Agent", "author_email": "no-reply@replit.com"}
    assert any(match_author(r, commit) for r in p.author_rules)


def test_continue_dev_profile_exists_even_if_empty():
    profiles = {p.name: p for p in load_profiles()}
    assert "continue_dev" in profiles
    # No strong positive matcher test: Continue has no default authorship
    # signature; detection only fires if the user manually adds the trailer.


def test_cline_profile_exists_even_if_empty():
    profiles = {p.name: p for p in load_profiles()}
    assert "cline" in profiles
    # No strong positive matcher test: Cline has no default authorship
    # signature; detection only fires if the user manually adds the trailer.


def test_opencode_matches_co_authored_by():
    from codeassay.detection.rules import match_message
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["opencode"]
    commit = {"message": "feat: add feature\n\nCo-Authored-By: opencode <noreply@opencode.ai>"}
    assert any(match_message(r, commit) for r in p.message_rules)


def test_opencode_matches_generated_with_footer():
    from codeassay.detection.rules import match_message
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["opencode"]
    commit = {"message": "feat: add feature\n\n\U0001f916 Generated with [opencode]"}
    assert any(match_message(r, commit) for r in p.message_rules)


def test_amp_matches_co_authored_by():
    from codeassay.detection.rules import match_message
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["amp"]
    commit = {"message": "refactor: simplify handler\n\nCo-authored-by: Amp <amp@ampcode.com>"}
    assert any(match_message(r, commit) for r in p.message_rules)


def test_codebuddy_matches_co_authored_by():
    from codeassay.detection.rules import match_message
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["codebuddy"]
    commit = {"message": "feat: new endpoint\n\nCo-authored-by: CodeBuddy <bot@codebuddy.ai>"}
    assert any(match_message(r, commit) for r in p.message_rules)
