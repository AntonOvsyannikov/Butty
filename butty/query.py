from __future__ import annotations

from abc import ABC, abstractmethod
from types import EllipsisType
from typing import TYPE_CHECKING, Any, Literal, Mapping, Type, TypeAlias, cast

from pydantic import BaseModel

from butty.compat import AnnotationCompat, ModelFieldInfo, get_field_info, get_fields_info, get_fields_names
from butty.errors import _validate

if TYPE_CHECKING:
    pass

ALL = -1
# ----------------------------------------------------

CompareOp = Literal["__eq__", "__gt__", "__ge__", "__lt__", "__le__", "__ne__"]

compare_ops_repr: Mapping[CompareOp, str] = cast(
    Mapping[CompareOp, str],
    {"__eq__": "==", "__gt__": ">", "__ge__": ">=", "__lt__": "<", "__le__": "<=", "__ne__": "!="},
)

compare_ops_mongo: Mapping[CompareOp, str] = cast(
    Mapping[CompareOp, str],
    {"__eq__": "$eq", "__gt__": "$gt", "__ge__": "$gte", "__lt__": "$lt", "__le__": "$lte", "__ne__": "$ne"},
)

LogicalOp = Literal["__and__", "__or__"]

logical_ops_repr: Mapping[LogicalOp, str] = cast(Mapping[LogicalOp, str], {"__and__": "AND", "__or__": "OR"})

logical_ops_mongo: Mapping[LogicalOp, str] = cast(Mapping[LogicalOp, str], {"__and__": "$and", "__or__": "$or"})


# ----------------------------------------------------


class ButtyQuery(ABC):
    def __and__(self, other: ButtyQuery) -> ButtyQueryNode:
        return ButtyQueryNode(self, "__and__", other)

    def __or__(self, other: ButtyQuery) -> ButtyQueryNode:
        return ButtyQueryNode(self, "__or__", other)

    @abstractmethod
    def to_mongo_query(self) -> MongoQuery:
        raise NotImplementedError()


# ----------------------------------------------------


class ButtyQueryLeaf(ButtyQuery, ABC):
    def __init__(self, butty_field: ButtyField):
        self.butty_field = butty_field


class ButtyQueryLeafCompare(ButtyQueryLeaf):
    def __init__(self, butty_field: ButtyField, op: CompareOp, literal: Any):
        super().__init__(butty_field)
        self.op = op
        self.literal = literal

    def __str__(self) -> str:
        return f"{self.butty_field._alias}{compare_ops_repr[self.op]}{self.literal}"

    def to_mongo_query(self) -> MongoQuery:
        return {self.butty_field._alias: {compare_ops_mongo[self.op]: self.literal}}


class ButtyQueryLeafRegex(ButtyQueryLeaf):
    def __init__(self, butty_field: ButtyField, pattern: str, options: str):
        super().__init__(butty_field)
        self.pattern = pattern
        self.options = options

    def __str__(self) -> str:
        return f"{self.butty_field._alias}~=/{self.pattern}/{self.options}"

    def to_mongo_query(self) -> MongoQuery:
        return {self.butty_field._alias: {"$regex": self.pattern, "$options": self.options}}


# ----------------------------------------------------


class ButtyQueryNode(ButtyQuery):
    def __init__(self, left: ButtyQuery, op: LogicalOp, right: ButtyQuery):
        self.left = left
        self.op = op
        self.right = right

    def __str__(self) -> str:
        return f"({self.left} {logical_ops_repr[self.op]} {self.right})"

    def to_mongo_query(self) -> MongoQuery:
        return {logical_ops_mongo[self.op]: [self.left.to_mongo_query(), self.right.to_mongo_query()]}


# ----------------------------------------------------


class ButtyField:
    def __init__(
            self,
            base_model_name: str,
            name: str,
            alias: str,
            annotation: AnnotationCompat,
    ):
        self._base_model_name = base_model_name
        self._name = name
        self._alias = alias
        self._annotation = annotation

    def __hash__(self) -> int:
        return hash(self._alias)

    def __eq__(self, other: Any) -> ButtyQueryLeaf:  # type: ignore[override]
        return ButtyQueryLeafCompare(self, "__eq__", other)

    def __gt__(self, other: Any) -> ButtyQueryLeaf:
        return ButtyQueryLeafCompare(self, "__gt__", other)

    def __ge__(self, other: Any) -> ButtyQueryLeaf:
        return ButtyQueryLeafCompare(self, "__ge__", other)

    def __lt__(self, other: Any) -> ButtyQueryLeaf:
        return ButtyQueryLeafCompare(self, "__lt__", other)

    def __le__(self, other: Any) -> ButtyQueryLeaf:
        return ButtyQueryLeafCompare(self, "__le__", other)

    def __ne__(self, other: Any) -> ButtyQueryLeaf:  # type: ignore[override]
        return ButtyQueryLeafCompare(self, "__ne__", other)

    def __mod__(self, other: Any) -> ButtyQueryLeaf:
        return self.__regex__(*other) if isinstance(other, tuple) else self.__regex__(other)

    def __regex__(self, pattern: str, options: str = "") -> ButtyQueryLeaf:
        return ButtyQueryLeafRegex(self, pattern, options)

    def __getattr__(self, item: str) -> ButtyField:
        return self._get_butty_field(item)

    def __getitem__(self, item: str | int | EllipsisType) -> ButtyField:
        return self._get_butty_field(item)

    def _get_butty_field(self, item: str | int | EllipsisType) -> ButtyField:
        err = f"Can not address {self._full_name} with {item}"

        t = self._annotation.core_type
        o = self._annotation.outer_type

        if o in (list, tuple, dict) and isinstance(item, int | EllipsisType) or o is dict:
            if item == ALL or item is ...:
                return self
            return ButtyField(
                self._base_model_name,
                self._name + f".{item}",
                self._alias + f".{item}",
                AnnotationCompat(t),
            )

        _validate(issubclass(t, BaseModel), f"{err} ({t} is not BaseModel)")
        assert issubclass(t, BaseModel)
        _validate(isinstance(item, str), f"{err} (not a string)")
        assert isinstance(item, str)
        _validate(item in get_fields_names(t), f"{err} (not a field)")

        f = get_field_info(t, item)
        return ButtyField(
            self._base_model_name,
            self._name + f".{f.name}",
            self._alias + f".{f.alias}",
            f.annotation,
        )

    @staticmethod
    def _inject(model: Type[BaseModel]) -> None:
        field_info: ModelFieldInfo
        for field_name, field_info in get_fields_info(model).items():
            setattr(
                model,
                field_name,
                ButtyField(model.__name__, field_info.name, field_info.alias, field_info.annotation),
            )

    @property
    def _full_name(self) -> str:
        return self._base_model_name + "." + self._name


# ----------------------------------------------------


def _build_mongo_query(query: Query) -> MongoQuery:
    """Builds raw MongoDB query from supported variants.

    :param query: Compatible query variant.
    :return: Raw MongoDB query.
    """

    if isinstance(query, ButtyQuery):
        return query.to_mongo_query()

    _validate(
        isinstance(query, dict),
        f"Query {query} is nor ButtyQuery nor dict",
    )

    return {
        k._alias if isinstance(k, ButtyField) else
        k: _build_mongo_query(v) if isinstance(v, dict | ButtyQuery) else
        v
        for k, v in query.items()
    }


# ----------------------------------------------------


def F(butty_field: Any) -> ButtyField:
    """Casts model field to ButtyField to use in queries."""
    return cast(ButtyField, butty_field)


def Q(query: Query | None) -> MongoQuery:
    """Builds MongoDB query from ButtyQuery or dict, where keys can be ButtyFields."""
    return _build_mongo_query(query) if query is not None else {}


# ----------------------------------------------------
# Update operations


def Set(query: Query) -> Query:
    """Create a MongoDB $set update operation.

    :param query: Field/value mappings to set
    :return: MongoDB update query with $set operator
    """
    return {"$set": query}


def Inc(query: Query) -> Query:
    """Create a MongoDB $inc update operation.

    :param query: Field/value mappings to set
    :return: MongoDB update query with $inc operator
    """
    return {"$inc": query}


# ----------------------------------------------------

MongoQuery: TypeAlias = dict[str, Any]
ButtyDictQuery: TypeAlias = dict[ButtyField, Any]
Query: TypeAlias = MongoQuery | ButtyDictQuery | ButtyQuery
