# mypy: ignore-errors
from __future__ import annotations

import typing
from dataclasses import dataclass
from typing import Annotated, Any, ForwardRef, Type, TypeAlias, TypeVar, cast

import pydantic
from pydantic import BaseModel, Field
from typing_inspect import get_args, get_origin, is_optional_type

from butty.errors import _validate

pydantic_version = int(pydantic.VERSION[0])

pydantic_undefined: Any
match pydantic_version:
    case 1:
        from pydantic.fields import Undefined  # noqa

        pydantic_undefined = Undefined
    case 2:
        from pydantic_core import PydanticUndefined  # noqa

        pydantic_undefined = PydanticUndefined
    case _:
        assert False, f"Pydantic major version {pydantic_version} is not supported"

FieldName: TypeAlias = str


class AnnotationCompat:
    def __init__(self, annotation_raw: Any):
        _validate(
            not isinstance(annotation_raw, str),
            f"Can not parse string annotation {annotation_raw}",
        )
        _validate(
            not isinstance(annotation_raw, ForwardRef),
            f"Can not parse {annotation_raw} make sure update_forward_refs()"
            f" or model_rebuild() are called for all documents",
        )
        self.annotation_raw = annotation_raw
        self.outer_type: type | None = None
        self.optional: bool = False

        t = annotation_raw

        if is_optional_type(t):
            self.optional = True
            t = get_args(t)[0]

        o = get_origin(t)

        if o in (list, tuple, dict):
            self.outer_type = o
            t = get_args(t)[1 if o is dict else 0]

            if is_optional_type(t):
                t = get_args(t)[0]

        self.core_type: type = t


@dataclass(frozen=True, kw_only=True)
class ModelFieldInfo:
    name: str
    alias: str
    required: bool
    annotation: AnnotationCompat
    extra: dict[str, Any]


def get_field_info(model: Type[BaseModel], name: FieldName) -> ModelFieldInfo:
    match pydantic_version:
        case 1:
            f = model.__fields__[name]  # noqa
            t = (
                f.outer_type_
                if typing.get_origin(f.outer_type_) is not Annotated
                else typing.get_args(f.outer_type_)[0]
            )
            required = cast(bool, f.required)
            if not required:
                t = t | None

            return ModelFieldInfo(
                name=name,
                alias=f.alias,
                required=required,
                annotation=AnnotationCompat(t),
                extra=f.field_info.extra,
            )
        case 2:
            f = model.model_fields[name]  # noqa
            return ModelFieldInfo(
                name=name,
                alias=f.alias or name,
                required=f.is_required(),
                annotation=AnnotationCompat(f.annotation),
                extra=cast(dict[str, Any], f.json_schema_extra or {}),
            )
        case _:
            assert False, f"Pydantic major version {pydantic_version} is not supported"


def get_fields_names(model: Type[BaseModel]) -> set[FieldName]:
    match pydantic_version:
        case 1:
            return {*model.__fields__}  # noqa
        case 2:
            return {*model.model_fields}  # noqa
        case _:
            assert False, f"Pydantic major version {pydantic_version} is not supported"


def get_fields_info(model: Type[BaseModel]) -> dict[FieldName, ModelFieldInfo]:
    return {name: get_field_info(model, name) for name in get_fields_names(model)}


T = TypeVar("T")


def parse_obj_as_compat(t: Type[T], obj: Any) -> T:
    match pydantic_version:
        case 1:
            from pydantic import parse_obj_as  # noqa

            return parse_obj_as(t, obj)
        case 2:
            from pydantic import TypeAdapter  # noqa

            return TypeAdapter(t).validate_python(obj)
        case _:
            assert False, f"Pydantic major version {pydantic_version} is not supported"


def to_dict(model: BaseModel, exclude: set[str], by_alias: bool) -> dict[str, Any]:
    match pydantic_version:
        case 1:
            return model.dict(  # noqa
                exclude=exclude,
                by_alias=by_alias,
            )
        case 2:
            return model.model_dump(  # noqa
                exclude=exclude,
                by_alias=by_alias,
            )
        case _:
            assert False, f"Pydantic major version {pydantic_version} is not supported"


def FieldCompat(
        default: Any,
        extra: dict[Any, Any],
        **kwargs: Any,
) -> Any:
    match pydantic_version:
        case 1:
            return Field(default, **extra, **kwargs)
        case 2:
            return Field(default, json_schema_extra=extra, **kwargs)


def model_rebuild_compat(model: Type[BaseModel]) -> None:
    match pydantic_version:
        case 1:
            model.update_forward_refs()
        case 2:
            model.model_rebuild()
