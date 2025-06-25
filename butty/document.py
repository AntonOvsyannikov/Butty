"""Public API"""

from __future__ import annotations

from abc import ABC
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    Awaitable,
    Callable,
    ClassVar,
    Generic,
    Literal,
    Type,
    TypeAlias,
    TypeVar,
    cast,
)

from motor.core import AgnosticCollection
from pydantic import BaseModel

from butty.errors import _validate

if TYPE_CHECKING:
    from butty.engine import Engine
    from butty.query import Query

T = TypeVar("T", bound="Document[Any]")
""" Document type """

ID_T = TypeVar("ID_T")
""" Identity type """


class DocumentConfigBase:
    """DocumentConfig class base."""

    collection_name: str
    """Explicit MongoDB collection name to use for this document type."""

    collection_name_from_model: Type[Document[Any]]
    """Document class whose collection should be reused (creates a collection view)."""


SaveMode: TypeAlias = Literal["auto", "update", "insert", "upsert"]
"""Defines the available modes for document save operations.

Possible values:
- "auto": Automatically determine insert or update based on identity existence
- "update": Force update operation (requires identity)
- "insert": Force insert operation 
- "upsert": Insert or update existing document (requires identity)
"""

HookKind: TypeAlias = Literal["before_delete"]
"""Specifies the types of hooks supported by the document lifecycle.

Currently only supports:
- "before_delete": Executed prior to document deletion
"""

Hook: TypeAlias = Callable[[T], Awaitable[T]]
"""Type signature for document hook functions."""


def hook(cls: Type[T], hook_kind: HookKind) -> Callable[[Hook[T]], Hook[T]]:
    """Decorator to register a hook function for a document model.

    :param cls: The document model class to register the hook for
    :param hook_kind: Type of hook to register (only "before_delete" supported for now)
    :return: Decorator function that registers the hook
    """
    from butty.engine import _get_register_hook_wrapper

    return _get_register_hook_wrapper(cls, hook_kind)


_documents_registry: list[Type[Document[Any]]] = []


class Document(BaseModel, Generic[ID_T]):
    __engine__: ClassVar[Engine]
    __collection__: ClassVar[AgnosticCollection[Any]]

    def __init_subclass__(cls, registry: bool | None = None, **kwargs: Any) -> None:
        """Initialize a subclass and optionally register it in the documents registry.

        :param registry: Whether to register the subclass. If None, auto-detect based on:
            - Not being a pydantic.main module
            - Not having ABC as base class
            - Not being a generic type (no '[' in name)
        :param kwargs: Additional keyword arguments passed to parent class
        """
        if (
                registry
                if registry is not None
                else all(
                    [
                        cls.__module__ != "pydantic.main",
                        ABC not in cls.__bases__,
                        "[" not in cls.__name__,
                    ]
                )
        ):
            _documents_registry.append(cls)

    async def save(
            self: T,
            *,
            mode: SaveMode = "auto",
    ) -> T:
        """Save the document instance to database.

        :param mode: Save operation mode:
            - "auto": Insert if document has no identity (None), otherwise update
            - "insert": Force insert (raises DuplicateKeyError if identity exists)
            - "update": Force update (raises DocumentNotFound if identity doesn't exist)
            - "upsert": Insert or update(instance must have an identity).
        :return: The saved document instance (with generated identity if new).
        :raises:
            - DuplicateKeyError: In insert mode when document with same identity exists.
            - DocumentNotFound: In update mode when document doesn't exist.
        """
        _validate(
            hasattr(self, "__engine__"),
            f"Document {self.__class__.__name__} is not bound.",
        )
        return cast(T, await self.__class__.__engine__._save(self, mode))

    @classmethod
    async def get(
            cls: Type[T],
            id_: ID_T,
            /,
    ) -> T:
        """Get document by its identity value.

        :param id_: Document identity value.
        :return: Found document.
        :raises:
            - DocumentNotFound: If document doesn't exist.
        """
        _validate(
            hasattr(cls, "__engine__"),
            f"Document {cls.__name__} is not bound.",
        )
        return cast(T, await cls.__engine__._get(cls, id_))

    @classmethod
    async def find_one(
            cls: Type[T],
            query: Query,
            /,
    ) -> T:
        """Find a single document matching the query.

        :param query: Query to match documents against.
        :return: First matching document.
        :raises:
            - DocumentNotFound: If no document matches the query.
        """
        _validate(
            hasattr(cls, "__engine__"),
            f"Document {cls.__name__} is not bound.",
        )
        return cast(T, await cls.__engine__._find_one(cls, query))

    @classmethod
    async def find_one_or_none(
            cls: Type[T],
            query: Query,
            /,
    ) -> T | None:
        """Find a single document matching the query or return None if not found.

        :param query: Query to match documents against.
        :return: First matching document or None if none match.
        """
        _validate(
            hasattr(cls, "__engine__"),
            f"Document {cls.__name__} is not bound.",
        )
        return cast(T, await cls.__engine__._find_one_or_none(cls, query))

    @classmethod
    async def find(
            cls: Type[T],
            query: Query | None = None,
            /,
            *,
            sort: Query | None = None,
            skip: int | None = None,
            limit: int | None = None,
    ) -> list[T]:
        """Find documents matching the query.

        :param query: Optional query to filter documents.
        :param sort: Optional sorting criteria.
        :param skip: Optional number of documents to skip.
        :param limit: Optional maximum number of documents to return.
        :return: List of matching documents.
        """
        _validate(
            hasattr(cls, "__engine__"),
            f"Document {cls.__name__} is not bound.",
        )
        return cast(list[T], await cls.__engine__._find(
            cls,
            query,
            sort=sort,
            skip=skip,
            limit=limit,
        ))

    @classmethod
    def find_iter(
            cls: Type[T],
            query: Query | None = None,
            /,
            *,
            sort: Query | None = None,
            skip: int | None = None,
            limit: int | None = None,
    ) -> AsyncIterable[T]:
        """Find documents matching the query.

        :param query: Optional query to filter documents.
        :param sort: Optional sorting criteria.
        :param skip: Optional number of documents to skip.
        :param limit: Optional maximum number of documents to return.
        :return: Async iterable of matching documents.
        """
        _validate(
            hasattr(cls, "__engine__"),
            f"Document {cls.__name__} is not bound.",
        )
        return cast(AsyncIterable[T], cls.__engine__._find_iter(
            cls,
            query,
            sort=sort,
            skip=skip,
            limit=limit,
        ))

    @classmethod
    async def count_documents(
            cls: Type[T],
            query: Query | None = None,
            /,
    ) -> int:
        """Count documents matching the query.

        :param query: Optional query to filter documents.
        :return: Number of matching documents.
        """
        _validate(
            hasattr(cls, "__engine__"),
            f"Document {cls.__name__} is not bound.",
        )
        return await cls.__engine__._count_documents(
            cls,
            query,
        )

    @classmethod
    async def find_and_count(
            cls: Type[T],
            query: Query | None = None,
            /,
            *,
            sort: Query | None = None,
            skip: int | None = None,
            limit: int | None = None,
    ) -> tuple[list[T], int]:
        """Find documents and get total count in one operation.

        :param query: Optional query to filter documents.
        :param sort: Optional sorting criteria.
        :param skip: Optional number of documents to skip.
        :param limit: Optional maximum number of documents to return.
        :return: Tuple of (list of matching documents, total count).
        """
        _validate(
            hasattr(cls, "__engine__"),
            f"Document {cls.__name__} is not bound.",
        )
        return cast(tuple[list[T], int], await cls.__engine__._find_and_count(
            cls,
            query,
            sort=sort,
            skip=skip,
            limit=limit,
        ))

    @classmethod
    async def update_document(
            cls: Type[T],
            id_: ID_T,
            update: Query,
            /,
            *,
            upsert: bool = False,
    ) -> T:
        """Update document by identity value.

        :param id_: Document identity value to update.
        :param update: Update operations i.g. Inc, Set etc.
        :param upsert: Create document if doesn't exist.
        :return: Updated/upserted document.
        :raises:
            - DocumentNotFound: If document doesn't exist and upsert=False.
        """
        _validate(
            hasattr(cls, "__engine__"),
            f"Document {cls.__name__} is not bound.",
        )
        return cast(T, await cls.__engine__._update_document(cls, id_, update, upsert))

    async def delete(self: T) -> T:
        """Delete the current document fromDB.

        :return: The deleted document instance with None identity.
        :raises:
            - DocumentNotFound: If document doesn't exist in database.
        """
        _validate(
            hasattr(self, "__engine__"),
            f"Document {self.__class__.__name__} is not bound.",
        )
        return cast(T, await self.__class__.__engine__._delete(self))

    # ----------------------------------------------------
    # hooks

    async def before_delete(self: T) -> T:
        """Hook called before deleting a document.

        :return: The document instance.
        """
        from butty.engine import _call_hooks

        return cast(T, await _call_hooks(self, "before_delete"))
