# 5. Utility Features

## 5.1 Indexes

Butty supports MongoDB index configuration through the `IndexedField` marker. Identity fields are always indexed by
default. Indexes are created during engine initialization and support single-field indexing with optional unique
constraints, raising `DuplicateKeyError` on constraint violations. The current implementation does not support compound
indexes. All index operations execute asynchronously during the engine setup phase. 

Example of indexed field declaration:

```python
class User(SerialIDDocument):
    login: Annotated[str, IndexedField(unique=True)]
```

## 5.2 Hooks

The hook system currently supports only delete operations through a single hook type. Hooks are registered using the
`@hook` decorator, which requires both the document class and hook type parameter.

Hook functions receive the document instance as input and must return it, optionally modifying it in-place. The system
executes hooks as part of the delete operation flow, processing them in reverse registration order. For inherited
documents, base class hooks execute in reverse Method Resolution Order (MRO).

The available hooks are:

- `before_delete`: Executes custom logic immediately before document deletion

Example of hook:

```python
class User(BaseDocument):
    name: str
    image_url: str | None


@hook(User, "before_delete")
async def before_user_delete(user: User) -> User:
    if user.image_url:
        await httpx.delete(user.image_url)
        user.image_url = None
    return user
```

## 5.3 Predefined Document Types

Butty provides two base document types, which are not part of the core, primarily for testing and prototyping purposes:

**SerialIDDocument**

- Uses auto-incremented integer IDs
- Implements sequential ID generation via counter collection
- Serves as example for custom identity providers
- Requires binding of `SerialIDCounter` class when manual engine setup is used

**OIDDocument**

- Uses MongoDB native `ObjectId` identifiers
- Includes required Pydantic configuration for `ObjectId` handling
- Demonstrates alias `_id` and BSON type integration

Both classes are abstract (ABC) and not intended for production use. Applications should define their own base document
class with appropriate identity strategy, project-specific model configuration, custom validation rules, etc.
