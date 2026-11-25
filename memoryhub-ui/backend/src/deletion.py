"""HTTP error mapping around the shared Core deletion workflow."""

from fastapi import HTTPException
from memoryhub_core.queries.deletion import delete_capabilities as delete_capabilities
from memoryhub_core.queries.mutations import RelationshipBoundaryError
from memoryhub_core.services.exceptions import (
    MemoryAccessDeniedError,
    MemoryAlreadyDeletedError,
    MemoryNotFoundError,
)
from memoryhub_core.services.memory import prepare_memory_delete


async def prepare_human_delete(db, access, ids):
    try:
        return await prepare_memory_delete(
            ids, db, access.principal.tenant_id, can_delete=access.can_delete,
        )
    except MemoryNotFoundError:
        raise HTTPException(status_code=404, detail="Memory not found") from None
    except MemoryAlreadyDeletedError:
        raise HTTPException(status_code=409, detail="Memory is already deleted") from None
    except MemoryAccessDeniedError:
        raise HTTPException(status_code=403, detail="Memory delete forbidden") from None
    except RelationshipBoundaryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
