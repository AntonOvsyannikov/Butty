from os import environ

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from butty import Engine

BUTTY_TESTS_MONGO_HOST = environ.get("BUTTY_TESTS_MONGO_HOST", "localhost")
BUTTY_TESTS_MONGO_DB_NAME = environ.get("BUTTY_TESTS_MONGO_DB_NAME", "butty_test")


@pytest.fixture
def engine_options():
    return {}


@pytest.fixture
async def engine(engine_options):
    motor = AsyncIOMotorClient("localhost")
    await motor.drop_database("butty_test")
    engine = Engine(motor["butty_test"], **engine_options)
    yield engine
    engine.unbind()
