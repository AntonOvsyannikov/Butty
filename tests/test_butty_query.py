from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from butty import ALL, F, Q
from butty.errors import ButtyValueError
from butty.query import ButtyField


class Foo(BaseModel):
    key: Annotated[str, Field(alias="key_alias")]


class Bar(BaseModel):
    foo: Annotated[Foo, Field(alias="foo_alias")]
    foo_l: Annotated[list[Foo], Field(alias="foo_l_alias")]
    foo_d: Annotated[dict[str, Foo], Field(alias="foo_d_alias")]


class Baz(BaseModel):
    bar: Annotated[Bar, Field(alias="bar_alias")]


ButtyField._inject(Baz)


def test_butty_field():
    assert F(Baz.bar.foo.key)._name == "bar.foo.key"
    assert F(Baz.bar.foo.key)._alias == "bar_alias.foo_alias.key_alias"

    assert F(Baz.bar.foo_l[0].key)._name == "bar.foo_l.0.key"
    assert F(Baz.bar.foo_l[0].key)._alias == "bar_alias.foo_l_alias.0.key_alias"

    assert F(Baz.bar.foo_l[...].key)._name == "bar.foo_l.key"
    assert F(Baz.bar.foo_l[...].key)._alias == "bar_alias.foo_l_alias.key_alias"

    assert F(Baz.bar.foo_l[ALL].key)._name == "bar.foo_l.key"
    assert F(Baz.bar.foo_l[ALL].key)._alias == "bar_alias.foo_l_alias.key_alias"

    assert F(Baz.bar.foo_d["some"].key)._name == "bar.foo_d.some.key"
    assert F(Baz.bar.foo_d["some"].key)._alias == "bar_alias.foo_d_alias.some.key_alias"

    with pytest.raises(AttributeError):
        F(Baz.baz)

    with pytest.raises(ButtyValueError):
        F(Baz.bar.baz)


def test_butty_query():
    assert Q({"$match": F(Baz.bar.foo.key) == 1}) == {"$match": {"bar_alias.foo_alias.key_alias": {"$eq": 1}}}
    assert Q({"$match": {Baz.bar.foo.key: {"$eq": 1}}}) == {"$match": {"bar_alias.foo_alias.key_alias": {"$eq": 1}}}
