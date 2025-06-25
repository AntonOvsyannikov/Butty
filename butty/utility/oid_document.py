# mypy: ignore-errors
from abc import ABC
from typing import Annotated, ClassVar

from bson import ObjectId

from butty import Document, IdentityField, compat

match compat.pydantic_version:
    case 1:
        class OIDDocument(Document[ObjectId], ABC):
            id: ObjectId | None = IdentityField(None, alias="_id")

            class Config:
                arbitrary_types_allowed = True
                allow_population_by_field_name = True

    case 2:
        from pydantic import ConfigDict


        class OIDDocument(Document[ObjectId], ABC):
            id: Annotated[ObjectId | None, IdentityField(alias="_id")] = None

            model_config: ClassVar[ConfigDict] = ConfigDict(
                arbitrary_types_allowed=True,
                populate_by_name=True,
            )
