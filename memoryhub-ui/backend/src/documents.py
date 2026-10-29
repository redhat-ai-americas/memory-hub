"""Documents: source text that memories can be written from, and point back to.

Upload a text document (Markdown, plain text, CSV, JSON, HTML source), read it
split into passages, select passages or any span, and write memories from
them. Each memory records the span it came from, so the memory page shows the
exact source passage and the document shows which passages became memories.

Uploading a new version reprocesses the links: a span whose text is still in
the document follows it ("moved"), one whose text is gone is flagged
("changed") so the memory can be reviewed. Reprocessing is a recorded job.

Documents hold content, so platform admins get none of this.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.access import ContentDep, LabsDep, ViewerDep, access_for
from src.config import Settings, get_settings
from src.database import get_db
from src.ui_common import Viewer, audit, now_utc, parse_uuid

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

DOCS = "memoryhub_ui_documents"
LINKS = "memoryhub_ui_document_links"
MAX_CHARS = 2_000_000


async def ensure_tables(db: AsyncSession) -> None:
    from src.schema import require

    await require(db)


def passages(body: str, target: int = 900) -> list[dict]:
    """Split text into passages on blank lines, keeping exact offsets (pure; unit-tested).

    Short paragraphs merge with the next one; long ones split at sentence ends.
    """
    spans: list[tuple[int, int]] = []
    for m in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\s*\Z)", body, flags=re.S):
        start, end = m.start(), m.end()
        while end - start > target * 1.6:
            cut = body.rfind(". ", start, start + target)
            cut = cut + 1 if cut > start + target // 3 else start + target
            spans.append((start, cut))
            start = cut
            while start < end and body[start].isspace():
                start += 1
        spans.append((start, end))
    # A heading or a one-liner joins the passage after it (once, not in a chain).
    merged: list[list[int]] = []
    carry: int | None = None
    carry_end = 0
    for s, e in spans:
        if carry is not None and e - carry <= target:
            merged.append([carry, e])
            carry = None
            continue
        if carry is not None:
            merged.append([carry, carry_end])
            carry = None
        if e - s < 40 or body[s] == "#":
            carry, carry_end = s, e
            continue
        merged.append([s, e])
    if carry is not None:
        merged.append([carry, carry_end])
    return [{"i": i, "start": s, "end": e, "text": body[s:e]} for i, (s, e) in enumerate(merged)]


def _without_headings(text_value: str) -> str:
    kept = "\n".join(line for line in text_value.split("\n") if not re.match(r"^\s*#{1,6}\s", line)).strip()
    return kept or text_value


def relocate(old_snippet: str, new_body: str, old_start: int) -> tuple[int, int] | None:
    """Where a linked span's text sits in a new version (closest match to the old offset)."""
    if not old_snippet:
        return None
    hits = [m.start() for m in re.finditer(re.escape(old_snippet), new_body)]
    if not hits:
        return None
    best = min(hits, key=lambda h: abs(h - old_start))
    return best, best + len(old_snippet)


def _load(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


async def _doc(db: AsyncSession, settings: Settings, viewer: Viewer, doc_id: str) -> Any:
    await ensure_tables(db)
    parsed = parse_uuid(doc_id, "document ID")
    row = (
        await db.execute(
            text(
                f"SELECT id, owner, title, mime, body, version, project, created_at, updated_at FROM {DOCS} WHERE id = :id AND tenant_id = :t"  # noqa: E501
            ),
            {"id": parsed, "t": settings.ui_tenant_id},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if row[1] != viewer.username:
        acc = await access_for(db, settings, viewer)
        shared = row[6] and (acc.grants is None or row[6] in acc.grants.projects)
        if not shared:
            raise HTTPException(status_code=404, detail="Document not found")
    return row


class DocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    body: str = Field(min_length=1, max_length=MAX_CHARS)
    mime: str = Field(default="text/plain", max_length=128)
    project: str | None = Field(default=None, max_length=255)


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    body: str | None = Field(default=None, min_length=1, max_length=MAX_CHARS)


class Span(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    content: str | None = Field(default=None, max_length=20_000)


class ExtractIn(BaseModel):
    spans: list[Span] = Field(min_length=1, max_length=50)
    scope: str = "user"
    scope_id: str | None = None
    weight: float = Field(default=0.7, ge=0, le=1)
    domains: list[str] | None = None


@router.get("/api/documents", dependencies=[LabsDep])
async def list_documents(db: DbDep, settings: SettingsDep, viewer: ContentDep):
    await ensure_tables(db)
    acc = await access_for(db, settings, viewer)
    projects = acc.grants.projects if acc.grants is not None else None
    rows = (
        await db.execute(
            text(
                f"""
                SELECT d.id, d.owner, d.title, d.mime, length(d.body), d.version, d.project, d.created_at, d.updated_at,
                       count(l.memory_id), count(l.memory_id) FILTER (WHERE l.status = 'changed')
                FROM {DOCS} d LEFT JOIN {LINKS} l ON l.document_id = d.id
                WHERE d.tenant_id = :t GROUP BY d.id ORDER BY d.updated_at DESC
                """
            ),
            {"t": settings.ui_tenant_id},
        )
    ).all()
    items = [
        {
            "id": str(r[0]),
            "owner": r[1],
            "title": r[2],
            "mime": r[3],
            "size": r[4],
            "version": r[5],
            "project": r[6],
            "created_at": r[7],
            "updated_at": r[8],
            "memories": r[9],
            "changed": r[10],
            "mine": r[1] == viewer.username,
        }
        for r in rows
        if r[1] == viewer.username or (r[6] and (projects is None or r[6] in projects))
    ]
    return {"items": items}


@router.post("/api/documents", status_code=201, dependencies=[LabsDep])
async def create_document(body: DocumentIn, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    from src.quality import _check_share

    await ensure_tables(db)
    if body.project:
        await _check_share(db, settings, viewer, "project", body.project)
    did = uuid.uuid4()
    await db.execute(
        text(
            f"INSERT INTO {DOCS} (id, tenant_id, owner, title, mime, body, project) VALUES (:id, :t, :o, :ti, :m, :b, :p)"  # noqa: E501
        ),
        {
            "id": did,
            "t": settings.ui_tenant_id,
            "o": viewer.username,
            "ti": body.title.strip(),
            "m": body.mime,
            "b": body.body,
            "p": body.project,
        },
    )
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="document.upload",
        scope="user",
        owner_id=viewer.username,
        memory_id=None,
        metadata={"document": str(did), "chars": len(body.body)},
    )
    await db.commit()
    return {"id": str(did)}


@router.get("/api/documents/{doc_id}", dependencies=[LabsDep])
async def get_document(doc_id: str, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    row = await _doc(db, settings, viewer, doc_id)
    links = (
        await db.execute(
            text(
                f"SELECT memory_id, start_at, end_at, status, doc_version FROM {LINKS} WHERE document_id = :d ORDER BY start_at"  # noqa: E501
            ),
            {"d": row[0]},
        )
    ).all()
    from memoryhub_core.models.memory import MemoryNode
    from sqlalchemy import select

    acc = await access_for(db, settings, viewer)
    nodes = {
        n.id: n
        for n in (
            await db.execute(select(MemoryNode).where(MemoryNode.id.in_([r[0] for r in links] or [uuid.uuid4()])))
        ).scalars()
    }
    link_out = []
    for mid, s, e, status, ver in links:
        n = nodes.get(mid)
        if n is None or not acc.can_read_row(n):
            continue
        link_out.append(
            {
                "memory_id": str(mid),
                "start": s,
                "end": e,
                "status": status if n.deleted_at is None else "deleted",
                "doc_version": ver,
                "stub": n.stub,
                "scope": n.scope,
                "is_current": n.is_current,
            }
        )
    parts = passages(row[4])
    for p in parts:
        p["memories"] = [lk["memory_id"] for lk in link_out if lk["start"] < p["end"] and lk["end"] > p["start"]]
    return {
        "id": str(row[0]),
        "owner": row[1],
        "title": row[2],
        "mime": row[3],
        "body": row[4],
        "version": row[5],
        "project": row[6],
        "created_at": row[7],
        "updated_at": row[8],
        "passages": parts,
        "links": link_out,
        "mine": row[1] == viewer.username,
    }


async def reprocess(db: AsyncSession, settings: Settings, viewer: Viewer, doc_id: str) -> dict:
    """Re-anchor every linked span on the current text of the document."""
    row = await _doc(db, settings, viewer, doc_id)
    body, version = row[4], row[5]
    links = (
        await db.execute(
            text(f"SELECT memory_id, start_at, snippet FROM {LINKS} WHERE document_id = :d"), {"d": row[0]}
        )
    ).all()
    counts = {"ok": 0, "moved": 0, "changed": 0}
    for mid, start, snippet in links:
        where = relocate(snippet, body, start)
        if where is None:
            status, s, e = "changed", start, start
        else:
            s, e = where
            status = "ok" if s == start else "moved"
        counts[status] += 1
        await db.execute(
            text(f"UPDATE {LINKS} SET start_at = :s, end_at = :e, status = :st, doc_version = :v WHERE memory_id = :m"),
            {"s": s, "e": e, "st": status, "v": version, "m": mid},
        )
    await db.commit()
    return {"document_id": str(row[0]), "version": version, **counts}


@router.put("/api/documents/{doc_id}", dependencies=[LabsDep])
async def update_document(doc_id: str, body: DocumentUpdate, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    from src.jobs import run_job

    row = await _doc(db, settings, viewer, doc_id)
    if row[1] != viewer.username:
        raise HTTPException(status_code=403, detail="Only the owner can upload a new version")
    changed_text = body.body is not None and body.body != row[4]
    await db.execute(
        text(f"UPDATE {DOCS} SET title = :ti, body = :b, version = version + :inc, updated_at = now() WHERE id = :id"),
        {
            "id": row[0],
            "ti": (body.title or row[2]).strip(),
            "b": body.body if changed_text else row[4],
            "inc": 1 if changed_text else 0,
        },
    )
    await db.commit()
    result = {"reprocessed": None}
    if changed_text:
        result["reprocessed"] = await run_job(
            settings,
            kind="document.reprocess",
            owner=viewer.username,
            detail={"document_id": str(row[0])},
            work=lambda: reprocess(db, settings, viewer, str(row[0])),
        )
    return result


@router.delete("/api/documents/{doc_id}", status_code=204, dependencies=[LabsDep])
async def delete_document(doc_id: str, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    row = await _doc(db, settings, viewer, doc_id)
    if row[1] != viewer.username:
        raise HTTPException(status_code=403, detail="Only the owner can delete a document")
    await db.execute(text(f"DELETE FROM {LINKS} WHERE document_id = :d"), {"d": row[0]})
    await db.execute(text(f"DELETE FROM {DOCS} WHERE id = :d"), {"d": row[0]})
    await db.commit()


@router.post("/api/documents/{doc_id}/memories", status_code=201, dependencies=[LabsDep])
async def memories_from_document(doc_id: str, body: ExtractIn, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    """Write one memory per selected span; each remembers where it came from."""
    from src.jobs import run_job
    from src.routes_dashboard import WriteMemoryRequest, create_dashboard_memory

    row = await _doc(db, settings, viewer, doc_id)
    text_body = row[4]

    async def work():
        created, failed = [], []
        for span in body.spans:
            if span.end > len(text_body) or span.start >= span.end:
                failed.append({"start": span.start, "detail": "Span is outside the document"})
                continue
            snippet = text_body[span.start : span.end]
            content = (span.content or _without_headings(snippet)).strip()
            try:
                res = await create_dashboard_memory(
                    db,
                    settings,
                    viewer,
                    WriteMemoryRequest(
                        content=content,
                        scope=body.scope,
                        scope_id=body.scope_id,
                        weight=body.weight,
                        domains=body.domains,
                    ),
                    metadata={
                        "source_document": {
                            "id": str(row[0]),
                            "title": row[2],
                            "start": span.start,
                            "end": span.end,
                            "version": row[5],
                        }
                    },
                )
            except HTTPException as exc:
                failed.append({"start": span.start, "detail": exc.detail})
                continue
            await db.execute(
                text(
                    f"INSERT INTO {LINKS} (memory_id, tenant_id, document_id, start_at, end_at, snippet, doc_version) "
                    "VALUES (:m, :t, :d, :s, :e, :sn, :v)"
                ),
                {
                    "m": uuid.UUID(res["id"]),
                    "t": settings.ui_tenant_id,
                    "d": row[0],
                    "s": span.start,
                    "e": span.end,
                    "sn": snippet,
                    "v": row[5],
                },
            )
            await db.commit()
            created.append(res["id"])
        return {
            "document_id": str(row[0]),
            "created": len(created),
            "failed": len(failed),
            "_value": {"created": created, "failed": failed},
        }

    return await run_job(
        settings, kind="document.extract", owner=viewer.username, work=work, detail={"document_id": str(row[0])}
    )


@router.get("/api/memory/{memory_id}/source")
async def memory_source(memory_id: str, db: DbDep, settings: SettingsDep, viewer: ViewerDep):
    """The document passage a memory was written from, with some context around it."""
    from src.routes_dashboard import _load_memory

    node = await _load_memory(db, settings.ui_tenant_id, memory_id)
    (await access_for(db, settings, viewer)).ensure_readable(node)
    await ensure_tables(db)
    link = (
        await db.execute(
            text(
                f"SELECT document_id, start_at, end_at, status, snippet, doc_version FROM {LINKS} WHERE memory_id = :m"
            ),
            {"m": node.id},
        )
    ).first()
    meta = (node.metadata_ or {}).get("source_document")
    if link is None:
        return {"linked": False, "title": meta.get("title") if meta else None}
    if viewer.redacts_content:
        return {"linked": True, "redacted": True, "status": link[3]}
    doc = (
        await db.execute(text(f"SELECT title, body, version, owner, project FROM {DOCS} WHERE id = :d"), {"d": link[0]})
    ).first()
    if doc is None:
        return {"linked": True, "document_deleted": True, "snippet": link[4], "status": link[3]}
    body = doc[1]
    s, e = link[1], link[2]
    can_open = doc[3] == viewer.username
    if not can_open and doc[4]:
        acc = await access_for(db, settings, viewer)
        can_open = acc.grants is None or doc[4] in acc.grants.projects
    return {
        "linked": True,
        "document_id": str(link[0]) if can_open else None,
        "title": doc[0],
        "status": link[3],
        "version": doc[2],
        "linked_version": link[5],
        "before": body[max(0, s - 240) : s],
        "passage": body[s:e] if link[3] != "changed" else link[4],
        "after": body[e : e + 240],
        "checked_at": now_utc(),
    }
