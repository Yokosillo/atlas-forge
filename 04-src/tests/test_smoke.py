from brain.cli.main import main


def test_package_importable() -> None:
    assert callable(main)
