from butty import DocumentConfigBase, Engine
from butty.utility.oid_document import OIDDocument

BaseDocument = OIDDocument


class User(BaseDocument):
    name: str
    password: str


class UserView(BaseDocument):
    name: str

    class DocumentConfig(DocumentConfigBase):
        collection_name_from_model = User


async def test_basic(engine: Engine):
    await engine.bind(User, UserView).init()

    user = await User(name="Vasya", password="123").save()

    assert user.id is not None

    user_view = await UserView.get(user.id)
    assert user_view == UserView(id=user.id, name="Vasya")

    user.password = "321"
    await user.save()

    user_view = await UserView.get(user.id)
    assert user_view == UserView(id=user.id, name="Vasya")

    user_view.name = "Pupkin"
    await user_view.save()

    user = await User.get(user_view.id)
    assert user == User(id=user_view.id, name="Pupkin", password="321")
