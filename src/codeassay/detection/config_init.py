"""Starter .codeassay.toml content, emitted by `codeassay config init`."""

STARTER_TEMPLATE = '''\
# codeassay detection config
# Docs: see docs/superpowers/specs in the codeassay source.

# ---------- Built-in AI tool profiles ----------
# Enabled by default. Set enabled = false to disable any profile for this repo.

[profiles.claude_code]
enabled = true
[profiles.copilot]
enabled = true
[profiles.cursor]
enabled = true
[profiles.aider]
enabled = true
[profiles.windsurf]
enabled = true
[profiles.gpt]
enabled = true
[profiles.gemini]
enabled = true

# ---------- User-defined rules (highest priority) ----------
# Examples — uncomment and edit to fit your team's conventions.

# [[detect.author]]
# pattern = "cursor-agent@.*"   # regex, matched against author email then name
# tool = "cursor"
# confidence = "high"

# [[detect.branch]]
# pattern = "^(ai|claude|copilot)/.*"
# tool = "claude_code"
# confidence = "medium"

# [[detect.message]]
# pattern = '^\\[AI\\]'          # team convention: AI commits prefixed with [AI]
# tool = "unknown"
# confidence = "high"

# [[detect.window]]
# author = "jeff@example.com"
# start = "2026-01-01"
# end = "2026-03-15"
# tool = "claude_code"
# confidence = "high"
# note = "AI-heavy sprint"

# ---------- Probabilistic scorer (opt-in, heuristic) ----------
# Runs only for commits no deterministic rule caught.
# Intended as a diagnostic; expect some false positives.

[score]
enabled = false
threshold = 0.7

[score.weights]
diff_wholesale_rewrite = 0.20
message_structured_body = 0.15
commit_velocity = 0.15
emoji_indicator = 0.10
message_boilerplate = 0.15
file_diversity = 0.10
perfect_punctuation = 0.15
'''
