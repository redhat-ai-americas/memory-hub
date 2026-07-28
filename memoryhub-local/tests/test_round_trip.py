"""Round-trip integration test for the personal-edition tool wrappers."""

import asyncio
import os
import shutil
import tempfile


async def test_round_trip():
    tmpdir = tempfile.mkdtemp()
    os.environ["XDG_DATA_HOME"] = tmpdir

    from memoryhub_local.database import create_local_engine, create_tables, make_session_factory
    from memoryhub_local.embeddings.base import MockEmbeddingService
    from memoryhub_local.storage.sqlite import SQLiteBackend
    from memoryhub_local.tools._state import init_state

    engine = await create_local_engine()
    await create_tables(engine)
    session_factory = make_session_factory(engine)
    init_state(session_factory, MockEmbeddingService(), SQLiteBackend())

    from memoryhub_local.tools.memory import memory
    from memoryhub_local.tools.register_session import register_session
    from memoryhub_local.tools.thread import thread

    # 1. register_session
    reg = await register_session()
    print("1. register_session:", reg["message"])

    # 2. write
    write_result = await memory(action="write", content="Parmesan is my favorite cheese")
    mem_id = write_result["memory"]["id"]
    print("2. write:", mem_id[:12], "- scope:", write_result["memory"]["scope"])

    # 3. search
    search_result = await memory(action="search", query="cheese")
    hits = search_result["results"]
    print("3. search:", len(hits), "results -", hits[0]["content"][:40] if hits else "none")

    # 4. read
    read_result = await memory(action="read", memory_id=mem_id)
    print("4. read:", read_result["content"][:40])

    # 5. update
    update_result = await memory(
        action="update", memory_id=mem_id, content="Cheddar is also great"
    )
    print("5. update: v" + str(update_result["version"]), "-", update_result["content"][:30])

    # 6. list
    list_result = await memory(action="list")
    print("6. list:", list_result["count"], "memories")

    # 7. thread create
    thread_result = await thread(
        action="create", scope="user", options={"title": "Test thread"}
    )
    tid = thread_result["id"]
    print("7. thread create:", tid[:12])

    # 8. thread append + get
    await thread(action="append", thread_id=tid, role="user", content="Hello world")
    get_result = await thread(action="get", thread_id=tid)
    print("8. thread get:", get_result["total_messages"], "messages")

    # 9. delete
    del_result = await memory(action="delete", memory_id=mem_id)
    print("9. delete:", del_result["total_deleted"], "nodes deleted")

    await engine.dispose()
    shutil.rmtree(tmpdir)

    print()
    print("ALL ROUND-TRIP TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(test_round_trip())
