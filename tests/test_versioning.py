from typing import Annotated

import pytest

from butty import Engine
from butty.errors import DocumentNotFound
from butty.fields import VersionField
from butty.utility.oid_document import OIDDocument


class BaseDocument(OIDDocument):
    version: Annotated[int | None, VersionField(version_provider=lambda v: 0 if v is None else v + 1)] = None


class User(BaseDocument):
    name: str
    password: str


async def test_basic(engine: Engine):
    await engine.bind(User).init()

    user = await User(name="Vasya", password="123").save()
    assert user.version == 0

    user1 = await User.get(user.id)
    user2 = await User.get(user.id)

    user1.password = "321"
    await user1.save()

    assert user1.version == 1

    user2.password = "456"
    with pytest.raises(DocumentNotFound):
        await user2.save()
