import agent_coach


def test_package_exposes_version() -> None:
    assert agent_coach.__version__ == "0.1.0"
