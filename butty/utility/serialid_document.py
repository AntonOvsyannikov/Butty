from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Annotated, Awaitable, Callable

from butty import Document, F, IdentityField, Inc

if TYPE_CHECKING:
    from butty.engine import DocModel


class SerialIDCounter(Document[str]):
    name: Annotated[str, IdentityField()]
    count: int


def _serial(doc_model: DocModel) -> Callable[[], Awaitable[int]]:
    async def identity_provider() -> int:
        return (
            await SerialIDCounter.update_document(
                doc_model.__collection__.name,
                Inc({F(SerialIDCounter.count): 1}),
                upsert=True,
            )
        ).count

    return identity_provider


class SerialIDDocument(Document[int], ABC):
    id: Annotated[int | None, IdentityField(identity_provider_factory=_serial)] = None
