"""Live session: build and walk a procedural graph via personal-edition tools.

Run:
    cd memoryhub-local && .venv/bin/python -m tests.test_procedural_live
or:
    pytest memoryhub-local/tests/test_procedural_live.py -s
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile


async def test_procedural_graph_live_session():
    tmpdir = tempfile.mkdtemp()
    os.environ["XDG_DATA_HOME"] = tmpdir

    from memoryhub_local.database import auto_migrate, create_local_engine, make_session_factory
    from memoryhub_local.embeddings.base import MockEmbeddingService
    from memoryhub_local.storage.sqlite import SQLiteBackend
    from memoryhub_local.tools._state import init_state
    from memoryhub_local.tools.memory import memory
    from memoryhub_local.tools.register_session import register_session

    engine = await create_local_engine()
    await auto_migrate(engine)
    session_factory = make_session_factory(engine)
    init_state(session_factory, MockEmbeddingService(), SQLiteBackend())

    await register_session(ctx=None)

    root = await memory(
        action="write",
        content="Deploy to staging: smoke test, promote, verify health",
        scope="user",
        options={"content_type": "procedural", "weight": 0.9},
    )
    root_id = root["memory"]["id"]
    print("1. procedure root:", root_id[:12], "content_type=", root["memory"]["content_type"])
    assert root["memory"]["content_type"] == "procedural"

    async def step(text: str, meta: dict) -> str:
        result = await memory(
            action="write",
            content=text,
            scope="user",
            options={
                "content_type": "procedural",
                "parent_id": root_id,
                "branch_type": "procedure_step",
                "metadata": {"procedure": meta},
            },
        )
        return result["memory"]["id"]

    smoke = await step(
        "Run the pre-deploy smoke test suite",
        {
            "action": "Run the pre-deploy smoke test suite",
            "tool_ref": "run_tests.sh --suite=smoke",
            "preconditions": ["staging environment is healthy"],
        },
    )
    promote = await step(
        "Promote the image to staging", {"action": "Promote the image to staging"}
    )
    rollback = await step(
        "Roll back the last deploy", {"action": "Roll back the last deploy"}
    )
    print("2. steps:", smoke[:12], promote[:12], rollback[:12])

    await memory(
        action="relate",
        options={
            "source_id": smoke,
            "target_id": promote,
            "relationship_type": "precedes",
            "metadata": {"condition": "smoke tests passed"},
        },
    )
    await memory(
        action="relate",
        options={"source_id": promote, "target_id": rollback, "relationship_type": "precedes"},
    )
    await memory(
        action="relate",
        options={
            "source_id": rollback,
            "target_id": smoke,
            "relationship_type": "precedes",
            "metadata": {"condition": "health check failed after promote"},
        },
    )
    await memory(
        action="relate",
        options={"source_id": promote, "target_id": smoke, "relationship_type": "requires"},
    )
    await memory(
        action="relate",
        options={
            "source_id": rollback,
            "target_id": promote,
            "relationship_type": "alternative_to",
        },
    )
    print("3. edges: precedes cycle + requires + alternative_to")

    listed = await memory(action="list", options={"content_type": "procedural"})
    print("4. list procedural:", listed["count"], "nodes")
    assert listed["count"] >= 4
    assert all(item["content_type"] == "procedural" for item in listed["results"])

    reconstruct = await memory(action="reconstruct")
    reconstruct_ids = {item["id"] for item in reconstruct.get("results", [])}
    print("5. reconstruct hits:", len(reconstruct_ids), "(procedural must not leak in)")
    assert root_id not in reconstruct_ids
    assert smoke not in reconstruct_ids

    rels = await memory(action="relationships", memory_id=smoke)
    types = {edge["relationship_type"] for edge in rels["relationships"]}
    print("6. smoke neighbor types:", sorted(types))
    assert "precedes" in types

    read_smoke = await memory(action="read", memory_id=smoke)
    print("7. smoke metadata:", read_smoke["metadata"])
    assert read_smoke["metadata"]["procedure"]["tool_ref"] == "run_tests.sh --suite=smoke"

    await engine.dispose()
    shutil.rmtree(tmpdir)
    print()
    print("PROCEDURAL GRAPH LIVE SESSION PASSED")


if __name__ == "__main__":
    asyncio.run(test_procedural_graph_live_session())
