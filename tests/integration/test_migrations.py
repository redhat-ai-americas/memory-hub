"""Guards on the Alembic revision graph itself.

These tests read the migration scripts off disk and need no database. They
live under tests/integration/ because that is the only job whose path filter
watches `alembic/**`, so a bad revision graph is caught in CI rather than at
deploy time.

Motivating incident: #533 and #592 were both branched from 027 and merged in
the same batch, producing two revisions numbered 028 with no shared ancestor.
`alembic upgrade head` then failed with "Multiple head revisions are present",
which broke conftest's upgrade step and blocked every later schema PR.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "alembic" / "versions"


def _literal(node: ast.AST) -> object:
    """Best-effort literal eval; returns None for anything non-constant."""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def _parse_revision(path: Path) -> tuple[str | None, tuple[str, ...]]:
    """Read ``revision`` and ``down_revision`` out of one migration script.

    Parsed with ``ast`` rather than through alembic's own loader on purpose.
    When a ``down_revision`` names a revision that is not on disk, that loader
    raises a bare ``KeyError`` from inside ``alembic/script/revision.py`` and
    takes down every test that touches the graph, which is the opposite of a
    readable failure.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    revision: str | None = None
    down: tuple[str, ...] = ()

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "revision":
                value = _literal(node.value)
                revision = value if isinstance(value, str) else None
            elif target.id == "down_revision":
                value = _literal(node.value)
                if isinstance(value, str):
                    down = (value,)
                elif isinstance(value, (tuple, list)):
                    down = tuple(v for v in value if isinstance(v, str))
                else:  # None, for the base revision
                    down = ()

    return revision, down


@pytest.fixture(scope="module")
def on_disk() -> dict[str, tuple[str, ...]]:
    """Map revision id -> its down_revision ids, parsed straight off disk."""
    parsed: dict[str, tuple[str, ...]] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        revision, down = _parse_revision(path)
        if revision is not None:
            parsed[revision] = down
    return parsed


@pytest.fixture(scope="module")
def script_directory() -> ScriptDirectory:
    """The server's Alembic revision graph, loaded from alembic.ini."""
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def test_every_down_revision_resolves(on_disk: dict[str, tuple[str, ...]]) -> None:
    """Every ``down_revision`` must name a revision that exists on disk.

    Catches a rebase or rename that rewrote a parent reference, which alembic
    itself only reports as ``KeyError: '<name>'`` with no indication of which
    file is at fault.
    """
    assert on_disk, f"No migrations parsed out of {VERSIONS_DIR}"

    dangling = {
        revision: [parent for parent in parents if parent not in on_disk] for revision, parents in on_disk.items()
    }
    dangling = {rev: missing for rev, missing in dangling.items() if missing}

    assert not dangling, "These revisions name a down_revision that does not exist on disk: " + "; ".join(
        f"{rev} -> {sorted(missing)}" for rev, missing in sorted(dangling.items())
    )


def test_single_head(on_disk: dict[str, tuple[str, ...]], script_directory: ScriptDirectory) -> None:
    """`alembic upgrade head` is only unambiguous when there is exactly one head.

    If this fails, two migrations were branched from the same parent and merged
    without a merge revision. Fix with:

        alembic merge --rev-id NNN_merge_<what> -m "<why>" heads
    """
    _skip_if_dangling(on_disk)

    heads = script_directory.get_heads()
    assert len(heads) == 1, (
        f"Expected exactly 1 Alembic head, found {len(heads)}: {sorted(heads)}. "
        "Two migrations share a parent and need a merge revision."
    )


def test_every_revision_is_reachable_from_head(
    on_disk: dict[str, tuple[str, ...]], script_directory: ScriptDirectory
) -> None:
    """Every revision on disk must be walkable from the single head to base.

    Catches a migration that was added to the directory but orphaned, for
    example by a merge revision that only rejoined some of the branches.
    """
    _skip_if_dangling(on_disk)

    heads = script_directory.get_heads()
    if len(heads) != 1:
        pytest.skip(f"graph has {len(heads)} heads; see test_single_head")

    head = heads[0]
    reachable = {rev.revision for rev in script_directory.walk_revisions("base", head)}
    orphaned = set(on_disk) - reachable
    assert not orphaned, f"Revisions exist on disk but are not reachable from head {head!r}: {sorted(orphaned)}"


def _skip_if_dangling(on_disk: dict[str, tuple[str, ...]]) -> None:
    """Defer to test_every_down_revision_resolves for the readable message."""
    if any(parent not in on_disk for parents in on_disk.values() for parent in parents):
        pytest.skip("graph has a dangling down_revision; see test_every_down_revision_resolves")
