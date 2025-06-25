from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

from butty.compat import FieldCompat, pydantic_undefined

if TYPE_CHECKING:
    from butty.engine import IdentityProvider, IdentityProviderFactory, VersionProvider


class KnownExtra(str, Enum):
    is_identity = "is_identity"
    identity_provider = "identity_provider"
    identity_provider_factory = "identity_provider_factory"
    link_name = "link_name"
    link_ignore = "link_ignore"
    is_index = "is_index"
    index_unique = "index_unique"
    on_delete = "on_delete"
    is_version = "is_version"
    version_provider = "version_provider"
    is_back_link = "is_back_link"


OnDelete = Literal["nothing", "propagate", "cascade"]
"""Defines possible behaviors when linked document is deleted.

Possible values:
- nothing: Take no action (default)
- cascade: Delete this document when linked document is deleted
- propagate: Delete linked documents when this document is deleted
"""


def IndexedField(
        default: Any = pydantic_undefined,
        *,
        unique: bool = False,
        **kwargs: Any,
) -> Any:
    """Creates an indexed field in MongoDB.

    :param default: Default field value.
    :param unique: Whether to create unique index (defaults to False if not specified).
    :param kwargs: Additional Pydantic Field arguments.
    :return: Field definition with index metadata.
    """
    extra: dict[Any, Any] = {}
    extra[KnownExtra.is_index] = True
    extra[KnownExtra.index_unique] = unique
    return FieldCompat(default, extra, **kwargs)


def IdentityField(
        default: Any = pydantic_undefined,
        *,
        identity_provider: IdentityProvider | None = None,
        identity_provider_factory: IdentityProviderFactory | None = None,
        **kwargs: Any,
) -> Any:
    """Creates a document identity field.

    :param default: Default field value.
    :param identity_provider: Identity provider.
    :param identity_provider_factory: Factory for identity provider.
    :param kwargs: Additional Pydantic Field arguments.
    :return: Field definition with identity metadata.
    """
    extra: dict[Any, Any] = {}
    extra[KnownExtra.is_identity] = True
    extra[KnownExtra.identity_provider] = identity_provider
    extra[KnownExtra.identity_provider_factory] = identity_provider_factory
    return FieldCompat(default, extra, **kwargs)


def VersionField(
        default: Any = pydantic_undefined,
        *,
        version_provider: VersionProvider,
        **kwargs: Any,
) -> Any:
    """Creates a document version field for optimistic concurrency control.

    :param default: Default field value.
    :param version_provider: Version provider implementation.
    :param kwargs: Additional Pydantic Field arguments.
    :return: Field definition with version metadata.
    """
    extra: dict[Any, Any] = {}
    extra[KnownExtra.is_version] = True
    extra[KnownExtra.version_provider] = version_provider
    return FieldCompat(default, extra, **kwargs)


def LinkField(
        default: Any = pydantic_undefined,
        *,
        link_name: str | None = None,
        link_ignore: bool = False,
        on_delete: OnDelete = "nothing",
        **kwargs: Any,
) -> Any:
    """Creates a field that links to another document.

    :param default: Default field value.
    :param link_name: Custom field name for storing link in MongoDB.
    :param link_ignore: If True, skip this field during link processing.
    :param on_delete: Behavior when linked document is deleted.
    :param kwargs: Additional Pydantic Field arguments.
    :return: Field definition with link metadata.
    """
    extra: dict[Any, Any] = {}
    extra[KnownExtra.link_name] = link_name
    extra[KnownExtra.link_ignore] = link_ignore
    extra[KnownExtra.on_delete] = on_delete
    return FieldCompat(default, extra, **kwargs)


def BackLinkField(
        default: Any = pydantic_undefined,
        **kwargs: Any,
) -> Any:
    """Creates a field that represents a back reference from another document.

    :param default: Default field value.
    :param kwargs: Additional Pydantic Field arguments.
    :return: Field definition with backlink metadata.
    """
    extra: dict[Any, Any] = {}
    extra[KnownExtra.is_back_link] = True
    return FieldCompat(default, extra, **kwargs)
