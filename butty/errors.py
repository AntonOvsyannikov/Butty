from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from butty.engine import DocModel
    from butty.query import Query


class ButtyError(Exception):
    """Base exception class for all Butty-specific errors."""
    pass


class ButtyValueError(ButtyError):
    """Raised when invalid values are provided to Butty operations.

    This covers:
    - Field values violating model constraints
    - Invalid method parameters
    - Type mismatches in operations
    """
    pass


class DocumentNotFound(ButtyError):
    def __init__(self, doc_model: DocModel, op: str, query: Query):
        """Raised when a requested document cannot be found in the database.

        :param doc_model: Document model class that was queried
        :param op: Operation being performed ('get', 'update', etc.)
        :param query: Query that failed to match documents
        :ivar doc_model: The document model class involved
        :ivar op: Name of the failed operation
        :ivar query: The query that returned no results
        """
        super().__init__(f"No document found for query {query} while {op} {doc_model.__name__}.")
        self.doc_model = doc_model
        self.op = op
        self.query = query


def _validate(
        condition: bool,
        message: str,
) -> None | NoReturn:
    if not condition:
        raise ButtyValueError(message)
    return None
