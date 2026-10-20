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

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def script_directory() -> ScriptDirectory:
    """The server's Alembic revision graph, loaded from alembic.ini."""
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def test_single_head(script_directory: ScriptDirectory) -> None:
    """`alembic upgrade head` is only unambiguous when there is exactly one head.

    If this fails, two migrations were branched from the same parent and merged
    without a merge revision. Fix with:

        alembic merge --rev-id NNN_merge_<what> -m "<why>" heads
    """
    heads = script_directory.get_heads()
    assert len(heads) == 1, (
        f"Expected exactly 1 Alembic head, found {len(heads)}: {sorted(heads)}. "
        "Two migrations share a parent and need a merge revision."
    )


def test_every_revision_is_reachable_from_head(
    script_directory: ScriptDirectory,
) -> None:
    """Every revision on disk must be walkable from the single head to base.

    Catches a migration that was added to the directory but orphaned, for
    example by a rebase that rewrote its `down_revision` to a revision that no
    longer exists under a different name.
    """
    head = script_directory.get_current_head()
    reachable = {rev.revision for rev in script_directory.walk_revisions("base", head)}
    on_disk = {rev.revision for rev in script_directory.walk_revisions()}
    orphaned = on_disk - reachable
    assert not orphaned, (
        f"Revisions exist on disk but are not reachable from head {head!r}: "
        f"{sorted(orphaned)}"
    )
