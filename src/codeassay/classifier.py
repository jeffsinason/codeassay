"""Heuristic rework classification based on commit signals."""

import re
from dataclasses import dataclass

CATEGORIES = [
    "bug_fix",
    "misunderstanding",
    "test_failure",
    "style_violation",
    "security_issue",
    "incomplete_implementation",
    "over_engineering",
]

KEYWORD_RULES = [
    (re.compile(r"security|vulnerab|injection|xss|csrf|cve", re.IGNORECASE), "security_issue"),
    (re.compile(r"misunderst|wrong approach|not what|rewrite.*wrong", re.IGNORECASE), "misunderstanding"),
    (re.compile(r"test.*fail|tests? (were|was) failing|fix.*test", re.IGNORECASE), "test_failure"),
    (re.compile(r"TODO|placeholder|implement.*left|stub|incomplete", re.IGNORECASE), "incomplete_implementation"),
    (re.compile(r"simplif|unnecessary|over.?engineer|remove.*abstraction|strip.*out", re.IGNORECASE), "over_engineering"),
    (re.compile(r"style|naming|convention|format|lint|pep8|flake8", re.IGNORECASE), "style_violation"),
    (re.compile(r"fix|bug|broken|crash|error|typo", re.IGNORECASE), "bug_fix"),
]


@dataclass
class ClassificationResult:
    category: str
    confidence: str
    signals: list[str]


def classify_rework(
    *, commit_message: str, lines_added: int, lines_removed: int,
    total_original_lines: int, files_affected: list[str],
) -> ClassificationResult:
    signals = []

    keyword_category = None
    for pattern, category in KEYWORD_RULES:
        if pattern.search(commit_message):
            keyword_category = category
            signals.append(f"keyword_match:{category}")
            break

    diff_category = None
    if total_original_lines > 0:
        removal_ratio = lines_removed / total_original_lines
        replacement_ratio = (lines_added + lines_removed) / max(total_original_lines, 1)

        if lines_removed > lines_added * 3 and removal_ratio > 0.3:
            diff_category = "over_engineering"
            signals.append("diff:mostly_removed")
        elif replacement_ratio > 0.7 and lines_added > 10:
            diff_category = "misunderstanding"
            signals.append("diff:wholesale_replacement")
        elif lines_added > lines_removed * 5 and lines_removed <= 3:
            diff_category = "incomplete_implementation"
            signals.append("diff:mostly_added")
        elif lines_added == lines_removed and lines_added > 0:
            diff_category = "style_violation"
            signals.append("diff:equal_churn")
        elif lines_added <= 5 and lines_removed <= 5:
            diff_category = "bug_fix"
            signals.append("diff:small_targeted_fix")

    if keyword_category and diff_category and keyword_category == diff_category:
        return ClassificationResult(category=keyword_category, confidence="high", signals=signals)
    elif keyword_category:
        return ClassificationResult(category=keyword_category, confidence="medium", signals=signals)
    elif diff_category:
        return ClassificationResult(category=diff_category, confidence="low", signals=signals)
    else:
        return ClassificationResult(category="bug_fix", confidence="low", signals=["default:no_strong_signal"])
