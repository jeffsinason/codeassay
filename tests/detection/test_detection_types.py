from codeassay.detection import Detection


def test_detection_dataclass_fields():
    d = Detection(
        tool="claude_code",
        confidence="high",
        method="profile",
        source="profile:claude_code",
    )
    assert d.tool == "claude_code"
    assert d.confidence == "high"
    assert d.method == "profile"
    assert d.source == "profile:claude_code"


def test_detection_is_frozen():
    import dataclasses
    d = Detection(tool="t", confidence="high", method="rule", source="s")
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        d.tool = "other"
