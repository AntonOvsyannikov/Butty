from typing import Annotated

import pytest
from bson import ObjectId

from butty import Engine, F, IndexedField
from butty.errors import DocumentNotFound
from butty.utility.oid_document import OIDDocument
from tests.misc import get_indices_names

BaseDocument = OIDDocument


class Department(BaseDocument):
    name: Annotated[str, IndexedField()]


class User(BaseDocument):
    department: Department
    name: str


async def test_basic(engine: Engine):
    await engine.bind(User, Department).init()

    # API
    it_department = await Department(name="IT").save()
    sales_department = await Department(name="Sales").save()

    vasya = await User(name="Vasya Pupkin", department=it_department).save()
    frosya = await User(name="Frosya Taburetkina", department=it_department).save()
    vova = await User(name="Vova Kastryulkin", department=sales_department).save()

    assert await User.find(F(User.department.name) == "IT", sort={User.name: 1}) == [frosya, vasya]
    assert await User.find(F(User.department.id) == sales_department.id) == [vova]
    assert await User.find(F(User.name) % ("vova", "i")) == [vova]
    assert await User.find(sort={User.department.name: 1, User.name: 1}) == [frosya, vasya, vova]
    assert await User.find(sort={User.department.name: -1, User.name: -1}) == [vova, vasya, frosya]

    assert await User.get(vasya.id) == vasya
    assert await User.find_one({F(User.id): vasya.id}) == vasya
    assert await User.find_one_or_none({F(User.id): vasya.id}) == vasya

    with pytest.raises(DocumentNotFound):
        await User.get(ObjectId())
    with pytest.raises(DocumentNotFound):
        await User.find_one({F(User.id): ObjectId()})
    assert await User.find_one_or_none({F(User.id): ObjectId()}) is None

    assert await User.count_documents(F(User.department.id) == it_department.id) == 2
    assert await User.find_and_count(F(User.department.id) == it_department.id, limit=1) == (
        [vasya],
        2,
    )

    # Underhood
    assert await get_indices_names(Department.__collection__) == {"_id_", "name_1"}
    assert await get_indices_names(User.__collection__) == {"_id_"}

    vasya_raw = await User.__collection__.find_one({"_id": vasya.id})
    assert vasya_raw == {
        "_id": vasya.id,
        "department": it_department.id,
        "name": "Vasya Pupkin",
    }
