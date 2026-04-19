# Contributing AI Tool Profiles

This guide explains how to add a new AI tool detection profile to codeassay.

## Profile schema

Each profile is a TOML file in `src/codeassay/profiles/<tool_name>.toml`.
The parser in `src/codeassay/detection/config.py` accepts these sections:

```toml
# One or more of these table-array sections:

[[detect.author]]
pattern = 'regex matched against author email, then author name'
tool = "tool_name"       # must match the file stem
confidence = "high"      # high | medium | low

[[detect.branch]]
pattern = 'regex matched against branch names'
tool = "tool_name"
confidence = "medium"

[[detect.message]]
pattern = 'regex matched against the full commit message'
tool = "tool_name"
confidence = "high"

[[detect.window]]
author  = 'regex matched against author email or name'
start   = "2025-01-01"  # YYYY-MM-DD, inclusive
end     = "2025-12-31"  # YYYY-MM-DD, inclusive
tool    = "tool_name"
confidence = "medium"
note    = "optional human-readable explanation"
```

The `RuleSpec` and `WindowSpec` dataclasses in `config.py` are the
authoritative schema reference.

## Confidence convention

| Level    | Meaning |
|----------|---------|
| `high`   | Documented explicit marker — e.g., a published default Co-Authored-By trailer, a bot email confirmed in official docs or verified real commits. |
| `medium` | Heuristic signal — branch prefix, author name pattern, or flag-enabled trailer that is not on by default. May produce false positives. |
| `low`    | Weak/inference — e.g., a vague keyword present in commit messages of many tools. Use sparingly. |

## Finding real signatures

1. **Official docs first.** Check the tool's homepage and changelog for any
   mention of commit attribution, `Co-Authored-By`, or `git.commit` settings.

2. **GitHub code search.** Search `"Co-Authored-By: ToolName"` or the bot
   email in GitHub code search to find real commits in the wild.

3. **Source-repo issues.** Search the tool's GitHub issues/discussions for
   "commit attribution", "co-author", or "git trailer".

4. **botcommits.dev.** Tracks AI-generated commits in public repos and
   documents which signals each tool emits.

5. **`git log` trawling.** Clone a repo known to use the tool and run:
   ```
   git log --format="%H %ae %s" | grep -i toolname
   ```

## Template profile

```toml
# Tool Name — https://tool.example.com
# One-sentence description of what the tool is and how it commits.
# Cite the specific source that confirmed each pattern.

[[detect.message]]
pattern = 'Co-[Aa]uthored-[Bb]y:.*ToolName'
tool = "tool_name"
confidence = "high"

[[detect.author]]
pattern = 'bot@tool\.example\.com'
tool = "tool_name"
confidence = "high"

[[detect.branch]]
pattern = '^tool/'
tool = "tool_name"
confidence = "medium"
```

Use **single-quoted** TOML strings for all `pattern` values so the string is
literal (no TOML escape processing). The regex engine receives the raw text.

If no verifiable signature exists, ship the profile anyway with a comment:

```toml
# CAUTION: currently no strong default signature. Add user rules in
# .codeassay.toml if your team uses this tool.
```

## Adding the required test

Add your profile name to the `expected` set in
`tests/detection/test_builtin_profiles.py::test_all_expected_profiles_load`.

Add at least one smoke test that exercises the primary signal:

```python
def test_mytool_matches_co_authored_by():
    from codeassay.detection.rules import match_message
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["tool_name"]
    commit = {"message": "feat: thing\n\nCo-authored-by: ToolName <bot@tool.example.com>"}
    assert any(match_message(r, commit) for r in p.message_rules)
```

If the tool has no verifiable signal, document the gap instead:

```python
def test_mytool_profile_exists_even_if_empty():
    profiles = {p.name: p for p in load_profiles()}
    assert "tool_name" in profiles
    # No positive matcher: ToolName has no default authorship signature.
```

## Opening a PR

1. Create your branch from `main`:
   ```
   git checkout -b feat/profile-<tool_name>
   ```
2. Add `src/codeassay/profiles/<tool_name>.toml` and update the test file.
3. Run `pytest -q` and confirm all tests pass.
4. Open a pull request against `main`. In the PR description, include:
   - The tool's homepage URL
   - The source(s) you used to verify each pattern
   - Confidence level for each signal and your reasoning
5. A maintainer will review the signals and merge when satisfied.

Reviewers look for: accurate confidence labels, a cited source for `high`
confidence patterns, and at least one passing test assertion per profile.
