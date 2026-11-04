"""Shared query contract for memory browsing, visualization and export."""

from datetime import date
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel


class BrowseQuery(BaseModel):
    tab: str = "current"
    q: str | None = None
    mode: str = "semantic"
    scope: list[str] | None = None
    actor: list[str] | None = None
    project: str | None = None
    domain: list[str] | None = None
    min_weight: float | None = None
    max_weight: float | None = None
    created_from: date | None = None
    created_to: date | None = None
    branch_type: str | None = None
    flag: list[str] | None = None
    entity: str | None = None


def browse_query(
    tab: str = Query(default="current", pattern="^(current|all|quarantined|deleted)$"),
    q: str | None = Query(default=None, max_length=1000),
    mode: str = Query(default="semantic", pattern="^(semantic|text)$"),
    scope: list[str] | None = Query(default=None),
    actor: list[str] | None = Query(default=None),
    project: str | None = Query(default=None, max_length=255),
    domain: list[str] | None = Query(default=None),
    min_weight: float | None = Query(default=None, ge=0, le=1),
    max_weight: float | None = Query(default=None, ge=0, le=1),
    created_from: date | None = Query(default=None),
    created_to: date | None = Query(default=None),
    branch_type: str | None = Query(default=None, min_length=1, max_length=50),
    flag: list[str] | None = Query(default=None),
    entity: str | None = Query(default=None, max_length=64),
) -> BrowseQuery:
    if min_weight is not None and max_weight is not None and min_weight > max_weight:
        raise HTTPException(status_code=422, detail="Minimum weight must not exceed maximum weight")
    if created_from is not None and created_to is not None and created_from > created_to:
        raise HTTPException(status_code=422, detail="Start date must not be after end date")
    return BrowseQuery(**locals())


BrowseDep = Annotated[BrowseQuery, Depends(browse_query)]
