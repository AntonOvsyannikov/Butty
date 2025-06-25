import asyncio
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from butty import Engine, F
from butty.utility.serialid_document import SerialIDDocument


class Department(SerialIDDocument):
    name: str


class User(SerialIDDocument):
    department: Department
    name: str


async def main() -> None:
    motor: AsyncIOMotorClient[Any] = AsyncIOMotorClient("localhost")
    await motor.drop_database("butty_test")  # uncomment for following runs
    await Engine(motor["butty_test"], link_name_format=lambda f: f.alias + "_id").bind().init()

    it_department = await Department(name="IT").save()
    sales_department = await Department(name="Sales").save()

    vasya = await User(name="Vasya Pupkin", department=it_department).save()
    frosya = await User(name="Frosya Taburetkina", department=it_department).save()
    vova = await User(name="Vova Kastryulkin", department=sales_department).save()

    assert await User.find(F(User.department.name) == "IT", sort={User.name: 1}) == [frosya, vasya]
    assert await User.find(F(User.department.id) == sales_department.id) == [vova]
    assert await User.find(F(User.name) % "Pupkin") == [vasya]

    vasya_raw = await User.__collection__.find_one({"id": vasya.id})
    assert vasya_raw is not None
    del vasya_raw["_id"]
    assert vasya_raw == {
        "id": 1,
        "name": "Vasya Pupkin",
        "department_id": 1,
    }


asyncio.run(main())
