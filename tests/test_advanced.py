from __future__ import annotations

from typing import Annotated

import pytest

from butty import BackLinkField, Engine, F, LinkField, compat
from butty.compat import model_rebuild_compat
from butty.document import hook
from butty.utility.serialid_document import SerialIDCounter, SerialIDDocument

BaseDocument = SerialIDDocument


class Category(BaseDocument):
    name: str


class Product(BaseDocument):
    name: str
    category: Category
    price: float


class Customer(BaseDocument):
    name: str


class Recipe(BaseDocument):
    total: float


class Order(BaseDocument):
    customer: Annotated[Customer, LinkField(on_delete="cascade")]
    recipe: Annotated[Recipe | None, LinkField(on_delete="propagate")] = None

    match compat.pydantic_version:
        case 2:
            # normal declaration
            order_items: Annotated[list[OrderItem] | None, BackLinkField()] = None
        case 1:
            # workaround due to bug in pydantic v1,
            # only if "from __future__ import annotations" is used
            # see https://github.com/pydantic/pydantic/issues/10509
            order_items: list[OrderItem] | None = BackLinkField(None)


class OrderItem(BaseDocument):
    order: Annotated[Order, LinkField(on_delete="cascade")]
    product: Product
    amount: int


model_rebuild_compat(Order)

hooks_called = []


@hook(OrderItem, "before_delete")
async def order_item_before_delete_hook(order_item: OrderItem) -> OrderItem:
    hooks_called.append(("order_item_hook", order_item.id))
    return order_item


@hook(Recipe, "before_delete")
async def recipe_before_delete_hook1(recipe: Recipe) -> Recipe:
    hooks_called.append(("recipe_hook1", recipe.total))
    return recipe


@hook(Recipe, "before_delete")
async def recipe_before_delete_hook2(recipe: Recipe) -> Recipe:
    hooks_called.append(("recipe_hook2", recipe.total))
    recipe.total = 0
    return recipe


@pytest.fixture
def engine_options():
    return {
        "collection_name_format": lambda m: m.__name__.lower() + "s",
        "link_name_format": lambda f: f.alias.lower() + "_id",
    }


async def test_advanced(engine: Engine):
    await engine.bind(
        SerialIDCounter,
        Customer,
        Recipe,
        Order,
        Category,
        Product,
        OrderItem,
    ).init()

    vasya = await Customer(name="Vasya Pupkin").save()
    frosya = await Customer(name="Frosya Taburetkina").save()

    house = await Category(name="House").save()
    garden = await Category(name="Garden").save()

    cup = await Product(name="Cup", category=house, price=10).save()
    bowl = await Product(name="Bowl", category=house, price=12).save()
    spoon = await Product(name="Spoon", category=house, price=1).save()
    knife = await Product(name="Knife", category=house, price=1.5).save()
    bench = await Product(name="Bench", category=garden, price=25).save()
    grill = await Product(name="Grill", category=garden, price=120).save()

    order1 = await Order(customer=vasya).save()
    await OrderItem(order=order1, product=cup, amount=1).save()
    await OrderItem(order=order1, product=knife, amount=5).save()
    await OrderItem(order=order1, product=bench, amount=1).save()

    order2 = await Order(customer=vasya).save()
    await OrderItem(order=order2, product=grill, amount=1).save()

    order3 = await Order(customer=frosya).save()
    await OrderItem(order=order3, product=bowl, amount=3).save()
    await OrderItem(order=order3, product=spoon, amount=3).save()

    # ----------------------------------------------------

    assert Customer.__collection__.name == "customers"
    customers = await engine.db["customers"].find({}).to_list(None)
    for d in customers:
        del d["_id"]
    assert customers == [
        {"id": 1, "name": "Vasya Pupkin"},
        {"id": 2, "name": "Frosya Taburetkina"},
    ]

    # ----------------------------------------------------

    assert Product.__collection__.name == "products"
    products = await engine.db["products"].find({}).to_list(None)
    for d in products:
        del d["_id"]
    assert products == [
        {"id": 1, "name": "Cup", "category_id": 1, "price": 10},
        {"id": 2, "name": "Bowl", "category_id": 1, "price": 12},
        {"id": 3, "name": "Spoon", "category_id": 1, "price": 1},
        {"id": 4, "name": "Knife", "category_id": 1, "price": 1.5},
        {"id": 5, "name": "Bench", "category_id": 2, "price": 25},
        {"id": 6, "name": "Grill", "category_id": 2, "price": 120},
    ]

    assert await Product.find(F(Product.price) == 1.5) == [knife]
    assert await Product.find({F(Product.price): 1.5}) == [knife]
    assert await Product.find(F(Product.price) != 1.5) == [cup, bowl, spoon, bench, grill]
    assert await Product.find(F(Product.price) > 1.5) == [cup, bowl, bench, grill]
    assert await Product.find(F(Product.price) >= 1.5) == [cup, bowl, knife, bench, grill]
    assert await Product.find(F(Product.price) < 1.5) == [spoon]
    assert await Product.find(F(Product.price) <= 1.5) == [spoon, knife]
    assert await Product.find(F(Product.name) % "oo") == [spoon]
    assert await Product.find(F(Product.name) % ("b", "i")) == [bowl, bench]

    assert await Product.find(F(Product.category.name) == "House") == [cup, bowl, spoon, knife]
    assert await Product.find(F(Product.category.id) == garden.id) == [bench, grill]

    assert await Product.count_documents(F(Product.price) > 1.5) == 4
    assert await Product.find_and_count(
        F(Product.price) >= 1.5,
        sort={F(Product.price): -1},
        skip=1,
        limit=3,
    ) == ([bench, bowl, cup], 5)

    # ----------------------------------------------------

    order1i = await Order.get(1)
    assert order1i.order_items == [
        OrderItem(id=1, order=order1, product=cup, amount=1),
        OrderItem(id=2, order=order1, product=knife, amount=5),
        OrderItem(id=3, order=order1, product=bench, amount=1),
    ]
    order2i = await Order.get(2)
    order3i = await Order.get(3)

    assert await Order.find(F(Order.order_items[...].product.category.name) == "Garden") == [order1i, order2i]
    assert await Order.find(F(Order.order_items[...].product.price) == 12) == [order3i]

    # ----------------------------------------------------

    hooks_called.clear()
    assert order1i.recipe is None
    assert await OrderItem.count_documents() == 6
    await order1i.delete()
    assert await OrderItem.count_documents() == 3
    assert hooks_called == [('order_item_hook', 1), ('order_item_hook', 2), ('order_item_hook', 3)]

    # ----------------------------------------------------

    async for o in Order.find_iter():
        o.recipe = await Recipe(total=sum(i.amount * i.product.price for i in o.order_items)).save()
        await o.save()

    assert (await Order.get(2)).recipe == Recipe(id=1, total=120)
    assert (await Order.get(3)).recipe == Recipe(id=2, total=39)

    hooks_called.clear()
    assert await Recipe.count_documents() == 2
    order = await Order.get(3)
    await order.delete()
    assert await OrderItem.count_documents() == 1
    assert await Recipe.count_documents() == 1
    assert hooks_called == [
        ('order_item_hook', 5),
        ('order_item_hook', 6),
        ('recipe_hook2', 39.0),
        ('recipe_hook1', 0),
    ]
