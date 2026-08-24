import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile
from email.message import Message
from email.parser import Parser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PACKAGE_JSON = {
    "/".join(("agent_coach", "data", "agent_contract_bundle.json")),
    "/".join(("agent_coach", "data", "diploma_eval_cases.json")),
    "/".join(("agent_coach", "data", "diploma_knowledge_base.json")),
    "/".join(("agent_coach", "data", "mock_scenarios.json")),
}


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


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    source_dir = tmp_path_factory.mktemp("wheel-source")
    dist_dir = tmp_path_factory.mktemp("wheel-dist")
    _copy_tracked_worktree(source_dir)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(dist_dir),
            str(source_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = sorted(dist_dir.glob("agent_coach-*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def test_wheel_metadata_declares_direct_pydantic_runtime_dependency(
    built_wheel: Path,
) -> None:
    metadata = _wheel_metadata(built_wheel)
    pydantic_requires = [
        requirement
        for requirement in metadata.get_all("Requires-Dist") or []
        if _requirement_name(requirement) == "pydantic"
    ]

    assert pydantic_requires == ["pydantic<3,>=2"]


def test_wheel_contains_required_resources_and_runs_default_mock_path(
    built_wheel: Path,
    tmp_path: Path,
) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        names = set(archive.namelist())
    assert names >= REQUIRED_PACKAGE_JSON

    venv_dir = tmp_path / "venv"
    run_dir = tmp_path / "run-outside-checkout"
    run_dir.mkdir()
    venv.EnvBuilder(with_pip=True).create(venv_dir)
    venv_python = _venv_python(venv_dir)
    subprocess.run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            str(built_wheel),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        [
            str(venv_python),
            "-I",
            "-c",
            _PACKAGED_MOCK_SMOKE,
        ],
        cwd=run_dir,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == (
        "0.1.0 grounded True learner.get_profile,rag.search,quiz.generate"
    )


def _wheel_metadata(wheel_path: Path) -> Message:
    with zipfile.ZipFile(wheel_path) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata_text = archive.read(metadata_name).decode("utf-8")
    return Parser().parsestr(metadata_text)


def _copy_tracked_worktree(destination: Path) -> None:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    for raw_name in result.stdout.split(b"\0"):
        if not raw_name:
            continue
        relative = Path(raw_name.decode("utf-8"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe tracked path: {relative}")
        source = REPO_ROOT / relative
        target = destination / relative
        if not source.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _requirement_name(requirement: str) -> str:
    name = requirement.split(";", 1)[0].strip()
    for marker in (" ", "[", "<", ">", "=", "!", "~"):
        name = name.split(marker, 1)[0]
    return name.casefold()


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


_PACKAGED_MOCK_SMOKE = """
from importlib import resources

import agent_coach
from agent_coach.mock import build_mock_composition
from agent_coach.mock.fixtures import load_mock_fixture
from agent_coach.retrieval.corpus import load_diploma_knowledge_base

for resource_name in (
    "agent_contract_bundle.json",
    "diploma_eval_cases.json",
    "diploma_knowledge_base.json",
    "mock_scenarios.json",
):
    resources.files("agent_coach.data").joinpath(resource_name).read_text(
        encoding="utf-8"
    )

fixture = load_mock_fixture()
knowledge_base = load_diploma_knowledge_base()
composition = build_mock_composition("grounded_success")
run_result = composition.runner.run(composition.request)
assert fixture.scenarios["grounded_success"].expected["answer_status"] == "grounded"
assert knowledge_base.chunks
assert run_result.answer_status == "grounded"
assert run_result.success is True
print(
    agent_coach.__version__,
    run_result.answer_status,
    run_result.success,
    ",".join(run_result.trace["tool_calls"]),
)
"""
