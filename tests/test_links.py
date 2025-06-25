from __future__ import annotations

import pytest

from butty import BackLinkField, Engine, LinkField
from butty.compat import model_rebuild_compat
from butty.utility.serialid_document import SerialIDCounter, SerialIDDocument

BaseDocument = SerialIDDocument


class Foo(BaseDocument):
    name: str


class Bar(BaseDocument):
    name: str
    foo: Foo | None = LinkField(None, on_delete="propagate")
    foos: list[Foo] | None = LinkField(None, on_delete="propagate")
    foos_d: dict[str, Foo] | None = LinkField(None, on_delete="propagate")
    bazs: list[Baz] | None = BackLinkField(None)


class Baz(BaseDocument):
    name: str
    bar: Bar = LinkField(on_delete="cascade")
    foo: Foo | None = LinkField(None, link_name="foo_ref", on_delete="propagate")
    foos: list[Foo] | None = LinkField(None, link_name="foos_ref", on_delete="propagate")
    foos_d: dict[str, Foo] | None = LinkField(None, link_name="foos_d_ref", on_delete="propagate")


model_rebuild_compat(Bar)


@pytest.fixture
def engine_options():
    return {
        "collection_name_format": lambda m: m.__name__.lower() + "s",
        "link_name_format": lambda f: f.alias.lower() + "_id",
    }


async def test_basic(engine: Engine):
    await engine.bind(SerialIDCounter, Foo, Bar, Baz).init()

    foos = [
        await Foo(name=f"foo{i + 1}").save()
        for i in range(20)
    ]

    bars = [
        await Bar(
            name=f"bar{i + 1}",
            foo=foos[i * 5],
            foos=[foos[i * 5 + 1], foos[i * 5 + 2]],
            foos_d={"one": foos[i * 5 + 3], "two": foos[i * 5 + 4]},
        ).save()
        for i in range(2)
    ]

    bazs = [
        await Baz(
            name=f"baz{i + 1}",
            bar=bars[i],
            foo=foos[10 + i * 5],
            foos=[foos[10 + i * 5 + 1], foos[10 + i * 5 + 2]],
            foos_d={"one": foos[10 + i * 5 + 3], "two": foos[10 + i * 5 + 4]},
        ).save()
        for i in range(2)
    ]

    res = await engine.db["foos"].find_one({"id": 1})
    del res["_id"]
    assert res == {
        "id": 1,
        "name": "foo1",
    }

    res = await engine.db["bars"].find_one({"id": 1})
    del res["_id"]
    assert res == {
        "id": 1,
        "name": "bar1",
        "foo_id": 1,
        "foos_id": [2, 3],
        "foos_d_id": {"one": 4, "two": 5},
    }

    res = await engine.db["bazs"].find_one({"id": 1})
    del res["_id"]
    assert res == {
        "id": 1,
        "name": "baz1",
        "bar_id": 1,
        "foo_ref": 11,
        "foos_ref": [12, 13],
        "foos_d_ref": {"one": 14, "two": 15},
    }

    assert await Foo.find(sort={"id": 1}) == foos
    assert await Baz.find(sort={"id": 1}) == bazs

    assert await Bar.get(1) == Bar(
        id=1,
        name="bar1",
        foo=foos[0],
        foos=[foos[1], foos[2]],
        foos_d={"one": foos[3], "two": foos[4]},
        bazs=[bazs[0]],
    )

    await bars[0].delete()
    assert await Foo.find(sort={"id": 1}) == foos[5:10] + foos[15:]
    assert await Bar.count_documents() == 1
    assert await Baz.find() == [bazs[1]]
