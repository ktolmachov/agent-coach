import subprocess
import sys
import tempfile


def test_package_imports_from_outside_checkout() -> None:
    with tempfile.TemporaryDirectory() as workdir:
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                "import agent_coach; print(agent_coach.__version__)",
            ],
            cwd=workdir,
            check=True,
            capture_output=True,
            text=True,
        )

    assert result.stdout.strip() == "0.1.0"
