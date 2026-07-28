from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from memoryhub.models import ExtractionResult


PATCH_TARGET = "memory_bench.memory.memoryhub.MemoryHubClient"


@patch(PATCH_TARGET)
async def test_client_receives_url_and_api_key(MockClient, provider, mock_client, make_document):
    MockClient.return_value = mock_client
    await provider._run_dreaming_ingest([make_document()])
    MockClient.assert_called_once_with(url=provider._url, api_key=provider._api_key)


@patch(PATCH_TARGET)
async def test_thread_owner_from_persona_id(MockClient, provider, mock_client, make_document):
    MockClient.return_value = mock_client
    await provider._run_dreaming_ingest([make_document(user_id="alice")])
    mock_client.create_thread.assert_called_once()
    assert mock_client.create_thread.call_args.kwargs["owner_id"] == "amb-alice"


@patch(PATCH_TARGET)
async def test_thread_owner_defaults_when_no_user_id(MockClient, provider, mock_client, make_document):
    MockClient.return_value = mock_client
    await provider._run_dreaming_ingest([make_document(user_id=None)])
    mock_client.create_thread.assert_called_once()
    assert mock_client.create_thread.call_args.kwargs["owner_id"] == "amb-default"


@patch(PATCH_TARGET)
async def test_thread_scope_and_project(MockClient, provider, mock_client, make_document):
    MockClient.return_value = mock_client
    await provider._run_dreaming_ingest([make_document()])
    kwargs = mock_client.create_thread.call_args.kwargs
    assert kwargs["scope"] == "project"
    assert kwargs["scope_id"] == "amb-benchmark"


@patch(PATCH_TARGET)
async def test_thread_tenant_id_forwarded(MockClient, provider, mock_client, make_document):
    MockClient.return_value = mock_client
    provider._tenant_id = "test-tenant"
    await provider._run_dreaming_ingest([make_document()])
    assert mock_client.create_thread.call_args.kwargs["tenant_id"] == "test-tenant"


@patch(PATCH_TARGET)
async def test_thread_tenant_id_omitted_when_none(MockClient, provider, mock_client, make_document):
    MockClient.return_value = mock_client
    provider._tenant_id = None
    await provider._run_dreaming_ingest([make_document()])
    assert "tenant_id" not in mock_client.create_thread.call_args.kwargs


@patch(PATCH_TARGET)
async def test_extraction_model_forwarded(MockClient, provider, mock_client, make_document):
    MockClient.return_value = mock_client
    provider._extraction_model = "gemini-2.0-flash"
    await provider._run_dreaming_ingest([make_document()])
    assert mock_client.extract_thread.call_args.kwargs["model"] == "gemini-2.0-flash"


@patch(PATCH_TARGET)
async def test_extraction_model_url_forwarded(MockClient, provider, mock_client, make_document):
    MockClient.return_value = mock_client
    provider._extraction_model = "gemini-2.0-flash"
    provider._extraction_model_url = "https://llm.example.com/v1"
    await provider._run_dreaming_ingest([make_document()])
    kwargs = mock_client.extract_thread.call_args.kwargs
    assert kwargs["model"] == "gemini-2.0-flash"
    assert kwargs["model_url"] == "https://llm.example.com/v1"


@patch(PATCH_TARGET)
async def test_extraction_omits_model_when_none(MockClient, provider, mock_client, make_document):
    MockClient.return_value = mock_client
    provider._extraction_model = None
    provider._extraction_model_url = None
    await provider._run_dreaming_ingest([make_document()])
    kwargs = mock_client.extract_thread.call_args.kwargs
    assert "model" not in kwargs
    assert "model_url" not in kwargs


@patch(PATCH_TARGET)
async def test_extraction_tenant_id_forwarded(MockClient, provider, mock_client, make_document):
    MockClient.return_value = mock_client
    provider._tenant_id = "test-tenant"
    await provider._run_dreaming_ingest([make_document()])
    assert mock_client.extract_thread.call_args.kwargs["tenant_id"] == "test-tenant"


@patch(PATCH_TARGET)
async def test_failures_accumulated(MockClient, provider, mock_client_factory, make_document, caplog):
    failing_client = mock_client_factory(
        extract_result=ExtractionResult(extracted_count=1, cursor=5, failures=3),
    )
    MockClient.return_value = failing_client
    docs = [
        make_document(id="session-1", user_id="bob"),
        make_document(id="session-2", user_id="bob"),
    ]
    with caplog.at_level(logging.INFO, logger="memory_bench.memory.memoryhub"):
        await provider._run_dreaming_ingest(docs)
    summary_lines = [r for r in caplog.records if "Dreaming ingestion complete" in r.message]
    assert len(summary_lines) == 1
    assert "6 failures" in summary_lines[0].message


@patch(PATCH_TARGET)
async def test_empty_messages_skipped(MockClient, provider, mock_client, make_document):
    MockClient.return_value = mock_client
    doc = make_document(messages=[
        {"role": "user", "content": ""},
        {"role": "user", "content": "   "},
        {"role": "assistant", "content": "real"},
    ])
    await provider._run_dreaming_ingest([doc])
    mock_client.append_message.assert_called_once()
    assert mock_client.append_message.call_args.kwargs["content"] == "real"


@patch(PATCH_TARGET)
async def test_message_metadata_includes_doc_id(MockClient, provider, mock_client, make_document):
    MockClient.return_value = mock_client
    doc = make_document(id="doc-xyz")
    await provider._run_dreaming_ingest([doc])
    first_call_meta = mock_client.append_message.call_args_list[0].kwargs["metadata"]
    assert first_call_meta["session_doc_id"] == "doc-xyz"


@patch(PATCH_TARGET)
async def test_message_metadata_includes_timestamp(MockClient, provider, mock_client, make_document):
    MockClient.return_value = mock_client
    doc = make_document(timestamp="2024-01-15T10:00:00Z")
    await provider._run_dreaming_ingest([doc])
    first_call_meta = mock_client.append_message.call_args_list[0].kwargs["metadata"]
    assert first_call_meta["session_timestamp"] == "2024-01-15T10:00:00Z"


@patch(PATCH_TARGET)
async def test_message_metadata_omits_timestamp_when_none(MockClient, provider, mock_client, make_document):
    MockClient.return_value = mock_client
    doc = make_document(timestamp=None)
    await provider._run_dreaming_ingest([doc])
    first_call_meta = mock_client.append_message.call_args_list[0].kwargs["metadata"]
    assert "session_timestamp" not in first_call_meta


@patch(PATCH_TARGET)
async def test_multiple_personas_create_separate_threads(MockClient, provider, mock_client, make_document):
    MockClient.return_value = mock_client
    docs = [
        make_document(user_id="alice"),
        make_document(user_id="bob"),
        make_document(user_id="carol"),
    ]
    await provider._run_dreaming_ingest(docs)
    assert mock_client.create_thread.call_count == 3
    owner_ids = {
        call.kwargs["owner_id"]
        for call in mock_client.create_thread.call_args_list
    }
    assert owner_ids == {"amb-alice", "amb-bob", "amb-carol"}
