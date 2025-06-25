# Butty

Lightweight fully typed async ODM (Object-Document Mapper) for MongoDB, powered by Pydantic and Motor.

## Quickstart

```
pip install butty
```

```python
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
    await motor.drop_database("butty_test")
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
```

## 1. Introduction

Butty is a lightweight async ODM for MongoDB designed to enable type-safe document handling and relationship management
in CRUD applications while maintaining full compatibility with Pydantic's tooling ecosystem. MongoDB's schema-less
nature makes it ideal for rapid iteration, and Butty builds on this by adding structured typing through Pydantic without
requiring migrations or DDL, while providing automatic MongoDB pipeline generation for complex document graphs.

The library supports both Pydantic v1 and v2, maintaining compatibility with IDE plugins and type checkers. Identity
management is flexible - developers can choose between MongoDB's native `_id`, serial auto-incremented integers, or
custom identity providers (both sync and async) for generating identifiers during save operations. Custom IDs are
preferable when JSON serialization of the entire database structure is needed, as they avoid BSON-specific formats like
`ObjectID`.

Relationships between documents are automatically detected when fields are annotated with `Document` types, simplifying
common linking scenarios while still allowing explicit reference declarations. Optional optimistic concurrency control
via version fields helps prevent race conditions during updates.

Butty implements a type-safe query builder by augmenting Pydantic models with MongoDB-aware field operations. During
model initialization, standard attributes are replaced with `ButtyField` instances that maintain original field aliases
and document nesting structure. This enables expressions like `F(User.contacts[...].address.city) == "Moscow"` to
generate properly aliased MongoDB queries while preserving IDE attribute existence checking. The builder supports
standard comparison operators (`==`, `>`, `>=`) and special cases like `%` for regex matching, with `Q()` converting
these expressions directly to native MongoDB query syntax.

As one of several Python MongoDB ODMs, Butty was inspired by Beanie but diverges in key aspects to preserve type safety.
Where Beanie modifies Pydantic's internals (like `__new__`) and introduces custom types (`Link[]`, `Indexed[]`) that
break IDE tooling, Butty uses plain Pydantic models for relationships, maintaining full type checker compatibility. It
replaces Beanie's MongoDB-centric `_id`/`DBRef` system with customizable identity providers and plain ID references,
using standard Pydantic `Field()` instead of proprietary syntax for configuration. This approach ensures greater
consistency with Python's type system and development tools.

The name Butty derives from "BUT TYped", reflecting its core design principle of maintaining strict typing.

## 2. Core Concepts

### 2.1 Document Definition

Butty documents are Pydantic models that inherit from `Document[ID_T]`, where the generic parameter specifies the
identity type (e.g., `int`, `str`, or `ObjectId`). These behave as standard Pydantic models while adding MongoDB
persistence capabilities through the generic CRUD API built into the `Document` base class, parameterized with identity
type and concrete `Document` type. This gives IDE and type tooling the ability to check function calls and infer result
types, whether for single documents or sequences. The class definition should include an identity field declaration,
corresponding with the generic parameter, annotated with `IdentityField()`.

When acting as a base class for all concrete `Documents` in the application, it should be marked as `ABC` to prevent
inclusion in the document registry for autobinding.

Example of custom `str` identity `Document`:

```python
class BaseDocument(Document[str], ABC):
    id: Annotated[str | None, IdentityField(identity_provider=lambda: str(uuid4()))] = None
```

Example of MongoDB `ObjectId` identity `Document`:

```python
class BaseDocument(Document[ObjectId], ABC):
    id: Annotated[ObjectId | None, IdentityField(alias="_id")] = None

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )
```

> **Note:** `arbitrary_types_allowed` option in model config (v2 syntax is used here), because `ObjectId` is not
> supported by Pydantic by default. Full model configuration to support e.g. JSON serialization of `ObjectId` is up to
> developers and out of scope of this guide.

The collection name for a bound `Document` is generated automatically, and the name of the class itself by default.
Collection naming can be customized either through the `collection_name_format` callable during engine setup or via the
`collection_name` and `collection_name_from_model` fields of the `DocumentConfig` class (see 2.3 Document Config).

Example of `DocumentConfig` with `collection_name`:

```python
class User(BaseDocument):
    name: str
    
    class DocumentConfig(DocumentConfigBase):
        collection_name = "users_collection"
```

### 2.2 Identity Management

Butty offers flexible identity management for both MongoDB-native and custom identifiers. Each document must declare
exactly one identity field marked with `IdentityField()`, with its type matching the document's `ID_T` generic
parameter. This field acts as the primary key for all persistence operations.

The identity lifecycle differentiates between transient documents (with `None` identity) and persisted ones, requiring
the identity field to be optional in most cases. When saving a transient document, the system generates a new identity
based on the configured strategy and inserts the document. For documents with existing identities, save operations
perform updates by default, though this can be configured via the `save()` method's `mode` parameter.

Three primary identity strategies are supported through `IdentityField()` configuration:

#### Native MongoDB `_id`

The strategy is automatically detected when the `_id` alias is present in the identity field declaration. While offering
optimal database performance, this requires additional Pydantic configuration for JSON serialization and ties the
application to MongoDB's identifier format.

Example of native MongoDB identity field declaration:

```python
class BaseDocument(Document[ObjectId], ABC):
    id: Annotated[ObjectId | None, IdentityField(alias="_id")] = None
```

#### Custom identity

Supports synchronous and asynchronous providers through `identity_provider` and `identity_provider_factory` parameters.
The factory pattern enables class-aware identity sequences, maintaining JSON compatibility while supporting
application-controlled identifiers like auto-incremented integers.

Example of identity provider factory, which returns async coroutine for serial id generation:

```python
class SerialIDCounter(Document[str]):
    name: Annotated[str, IdentityField()]
    count: int


def _serial(doc_model: DocModel) -> Callable[[], Awaitable[int]]:
    async def identity_provider() -> int:
        return (
            await SerialIDCounter.update_document(
                doc_model.__collection__.name,
                Inc({F(SerialIDCounter.count): 1}),
                upsert=True,
            )
        ).count

    return identity_provider


class SerialIDDocument(Document[int], ABC):
    id: Annotated[int | None, IdentityField(identity_provider_factory=_serial)] = None


```

#### Provided identities

Identity can be managed outside the Butty engine. For example, the identity field can use `default_factory` from
Pydantic's model configuration. Documents with existing identities are treated as persistent by default, requiring
explicit `insert` mode specification for new documents.

Example of provided identity field:

```python
class SerialIDCounter(Document[str]):
    name: Annotated[str, IdentityField()]
    count: int
```

### 2.3 Document Linking

#### Direct Links

Butty implements document linking through standard Pydantic model references without requiring proprietary wrapper
types. When a field is annotated with another `Document` type, the system automatically establishes a relationship
between documents. This approach maintains full type safety while allowing flexible relationship configurations.

By default, linked documents are stored as references (using the target document's identity value). To store a document
as an embedded object instead, the link must be marked with `LinkField(link_ignore=True)`. The link value is
automatically determined from the destination document's identity field.

The MongoDB document field name representing the link can be configured either:

- Per field using `LinkField(link_name=...)`
- Globally via the engine's `link_name_format` callable

When unspecified, the field alias becomes the storage field name. This allows semantic naming patterns like storing as
`user_id` while declaring the field as `user: User`.

Special collection types are supported for document linking:

- `list[Document]` or `tuple[Document]` - Represents arrays of references
- `dict[str, Document]` - Represents dictionaries of references

All other field types, including nested Pydantic `BaseModel` instances, are always stored as embedded documents - even
when they contain `Document`-typed fields themselves.

Example of linked documents:

```python
class Department(BaseDocument):
    name: Annotated[str]


class User(BaseDocument):
    department: Department
    name: str
```

#### Backlinks

While automatic linking and `LinkField()` handle forward relationships, backlinks enable reverse document traversal. For
example, when `OrderItem` references its parent `Order`, backlinks allow querying all `OrderItems` belonging to a
specific `Order`.

Backlinks require explicit declaration with `BackLinkField()` and must be:

- Optional fields (marked with `| None`)
- Typed as collections (`list[Document]` or `tuple[Document]`)
- Paired with exactly one forward reference from the target document type

The system automatically maintains backlink integrity without duplicating reference data in storage.

Example of backlinks definition:

```python
class Order(BaseDocument):
    order_items: Annotated[list[OrderItem] | None, BackLinkField()] = None


class OrderItem(BaseDocument):
    order: Order
    product_name: str
    amount: float


Order.model_rebuild()
```

> **Note:** Backlinks require `ForwardRef` updates for mutual model references. In Pydantic v1 (with
> `from __future__ import annotations`), due to [issue #10509](https://github.com/pydantic/pydantic/issues/10509), the
> syntax `order_items: Annotated[list[OrderItem] | None, BackLinkField()] = None` isn't supported - use
> `order_items: list[OrderItem] | None = BackLinkField(None)` instead.

#### Automatic Pipeline Generation

By analyzing the complete document relationship graph during initialization, Butty automatically generates MongoDB
aggregation pipelines with nested lookups. This forms the core value of the engine, enabling efficient joins across
related documents while maintaining type safety. The pipelines are generated statically and cannot be dynamically
adjusted during read operations - all nesting levels and lookup paths are predetermined. This design means the
relationship graph cannot contain circular references or self-references, ensuring all document connections can be
resolved through a finite series of lookups.

### 2.4 Query Building

The query builder provides type-safe construction of MongoDB queries through operator overloading and logical
composition. During engine setup, standard attributes of `Document` models are replaced with `ButtyField` instances that
maintain original field aliases and document nesting structure. These references support attribute-style navigation
through nested documents and collections while maintaining proper MongoDB field path notation. The system preserves
original field names from Pydantic models while handling alias translation for database operations.

Comparison operations implement standard Python comparison operators (`==`, `>`, `>=`, `<`, `<=`, `!=`) which generate
appropriate MongoDB query operators (`$eq`, `$gt`, `$gte`, `$lt`, `$lte`, `$ne`). The modulo operator (`%`) provides
regular expression matching support, translating to MongoDB's `$regex` operator with configurable options. Each
comparison operation produces a query leaf node containing the field reference, operator, and comparison value.

Logical operators combine query components using `&` (AND) and `|` (OR) operators, building nested query structures that
translate to MongoDB's `$and` and `$or` operators. The query builder maintains proper operator precedence through
explicit grouping, ensuring logical expressions evaluate as intended. Complex queries can combine multiple levels of
logical operations with various comparison conditions.

The query interface requires all components to implement conversion to native MongoDB query syntax through the
`to_mongo_query()` method. This polymorphic design allows mixing raw dictionary queries with builder-constructed queries
while maintaining consistent output format. The system automatically handles field alias substitution when converting
builder queries to database syntax.

Utility functions `F()` and `Q()` provide explicit type conversion points for static type checkers. `F()` casts model
fields to `ButtyField` instances for query building, while `Q()` finalizes query construction by converting builder
objects or hybrid dictionaries to pure MongoDB query syntax. These functions serve as integration points between the
type-safe builder and raw dictionary queries.

Update operations follow a similar pattern with dedicated operators like `Set` and `Inc` that construct MongoDB update
documents. These operations maintain field reference integrity while supporting both direct values and nested update
expressions. The update builder ensures proper syntax generation for atomic update operations.

Queries example:

```python
class Product(BaseDocument):
    name: str
    price: float


class Order(BaseDocument):
    order_items: Annotated[list[OrderItem] | None, BackLinkField()] = None


class OrderItem(BaseDocument):
    order: Order
    product: Product


Order.model_rebuild()


async def main():
    await Product.find(F(Product.name) == "Chair")
    await Product.find({F(Product.name): "Chair"})
    await Product.find(F(Product.price) > 100)
    await Product.find((F(Product.price) > 100) & (F(Product.name) == "Chair"))
    await Order.find(F(Order.order_items[...].product.name) == "Chair")
```

> **Note:** The array query syntax `[...]` primarily serves to satisfy IDE attributes validation. The expression can
> alternatively be written as `F(Order.order_items).product.name` - this bypasses IDE attribute resolution while
> remaining fully valid MongoDB query syntax.

### 2.5 Collection Views

Butty supports MongoDB collection views through the document configuration system. Multiple document types can reference
the same underlying MongoDB collection while presenting different schemas and validation rules. This enables scenarios
where different application components need varying perspectives on the same data.

Collection views are configured by specifying the source document class in the `collection_name_from_model` field of the
`DocumentConfig`. The view document inherits the collection binding of its source while maintaining independent schema
validation and field definitions. All documents sharing a collection must use compatible identity types.

When saving documents through a view, only fields explicitly defined in that view document will be modified in the
database. All other fields in the underlying collection remain untouched.

Example of collection view:

```python
class User(BaseDocument):
    name: str
    password: str


class UserView(BaseDocument):
    name: str

    class DocumentConfig(DocumentConfigBase):
        collection_name_from_model = User
```

### 2.6 Versioning for Optimistic Concurrency Control

Butty implements optimistic concurrency control through configurable version fields. The version field can use any
comparable type (integer, string, etc.) annotated with `VersionField`, with custom logic for generating new version
values. During save operations, the system performs an atomic check comparing the document's current version against the
stored value, rejecting the update if they don't match.

Version value generation is fully customizable through the version provider function, which receives the current value
and returns the next version. This allows implementations ranging from simple counters to UUID-based schemes or
timestamp versions. Failed updates due to version conflicts raise `DocumentNotFound`, while successful updates
atomically persist both the new document state and its updated version identifier.

Example of `BaseDocument` with version field:

```python
class BaseDocument(OIDDocument):
    version: Annotated[int | None, VersionField(version_provider=lambda v: 0 if v is None else v + 1)] = None
```

### 2.7 Document Config

Butty provides document configuration through a nested `DocumentConfig` class that should inherit from
`DocumentConfigBase`. This inheritance enables IDE autocompletion and type checking for the available configuration
options:

- `collection_name`: Explicit MongoDB collection name
- `collection_name_from_model`: Document class whose collection should be reused (creates a view)

### 2.8 Fields Declaration

Butty supports two syntax variations for field definitions, both using native Pydantic field declarations enhanced with
specialized field information:

- `Annotated` style: `Annotated[FieldType, FieldInformation(...)]`
- Default value style: `FieldType = FieldInformation(...)`

Available field information types provide document-specific capabilities:

- `IdentityField()`: Designates the primary key field. Supports custom identity providers through `identity_provider`
  and `identity_provider_factory` parameters.

- `VersionField()`: Enables optimistic concurrency control. Requires a `version_provider` function to generate version
  values.

- `LinkField()`: Defines document relationships. Configurable with:

  - `link_name`: Custom storage field name
  - `on_delete`: Cascade behavior ("nothing", "cascade", "propagate")
  - `link_ignore`: Skip link processing

- `BackLinkField()`: Creates reverse references from linked documents.

- `IndexedField()`: Specifies fields for MongoDB indexing. Supports `unique` constraint flag.

All field information types maintain compatibility with standard Pydantic field arguments while extending functionality
for MongoDB operations.

Example of `IndexedField` declarations:

```python
class Department(BaseDocument):
    name: Annotated[str, IndexedField()] = "unknown"

# or

class Department(BaseDocument):
    name: str = IndexedField("unknown")

```

### 2.8 Error handling

Butty uses a hierarchy of exceptions while also propagating relevant MongoDB driver exceptions for operational
integrity. All Butty-specific errors inherit from `ButtyError`, providing consistent error handling while maintaining
separation from other exception types. Certain operations may raise native MongoDB exceptions like `DuplicateKeyError`
alongside Butty's exception types to reflect database-level constraints.

Key error types include:

- `ButtyError`: Base class for all Butty-specific exceptions
- `ButtyValueError`: Indicates invalid field values or operation parameters
- `DocumentNotFound`: Signals missing documents during get/update operations (contains `doc_model`, `op`, and `query`
  attributes)
- MongoDB driver exceptions: Including `DuplicateKeyError` for identity conflicts during insert operations

## 3. Engine Setup

### 3.1 Engine Creation

The `Engine` constructor `__init__` establishes the core MongoDB connection with centralized naming configuration. It
accepts:

- `db`: MongoDB database connection (Motor/AgnosticDatabase)
- `collection_name_format`: Callable to generate collection names from model classes (default: class name)
- `link_name_format`: Callable to generate field names for document relationships (default: field alias)

These format parameters allow consistent naming rules across all bound documents.

Example of engine creation:

```python
motor = AsyncIOMotorClient("localhost")
engine = Engine(motor["butty_test"], link_name_format=lambda f: f.alias + "_id")
```

### 3.2 Document Binding

`bind()` registers document classes with the engine, processing:

- Collection name resolution (via `DocumentConfig` or format callable)
- Field injection and relationship pipeline setup
- Duplicate binding prevention

The automatic document registry (populated via `__init_subclass__`) simplifies binding in complex applications by
tracking document classes. When `bind()` is called without parameters, it uses all registered documents. The
registration is carefully filtered to exclude:

- Classes with `registry=False` explicit override
- Abstract base classes (ABC)
- Generic type definitions (containing '\[')
- Pydantic internal models (`pydantic.main`)

This filtering is necessary because `__init_subclass__` triggers during various Pydantic setup operations, not just
actual document class definitions. The registry system provides convenience while preventing unwanted automatic binding
of support classes.

`unbind()` removes all document associations, clearing both explicitly bound documents and registry-tracked classes
while maintaining the underlying collections.

Example of document binding:

```python
engine.bind()  # binds all registered documents
engine.bind(User, Department)  # binds only User and Department
```

### 3.3 Engine Initialization

The `init()` method finalizes engine setup by creating all configured database indexes.

Example of engine initialization:

```python
async def main():
    await engine.init()
```

## 4. CRUD Operations

### 4.1 Creating Documents

Documents are created through the Document API's `save()` method, which supports multiple modes:

- Default mode: Auto-detects insert/update based on identity presence. New documents must have `None` identity before
  creation.
- Explicit insert: `save(mode="insert")` forces creation (fails on duplicate)
- Upsert: `save(mode="upsert")` combines insert/update for known identities

Linked documents must be saved separately before being referenced - they should be provided as complete model instances
during document creation. The save operation returns documents with their generated identities while leaving any linked
documents unchanged (no lookup pipeline activation for references).

Documents can alternatively be created through `update_document()` with `upsert=True`, which performs direct MongoDB
upsert operations without going through the full document lifecycle hooks.

Example of documents creation with `save()`:

```python
class Department(SerialIDDocument):
    name: str


class User(SerialIDDocument):
    department: Department
    name: str

async def main():
    department = await Department(name="IT").save()
    await User(name="Vasya Pupkin", department=department).save()
```

Example of documents creation with `update_document()`:

```python
class SerialIDCounter(Document[str]):
    name: Annotated[str, IdentityField()]
    count: int

async def main():
    await SerialIDCounter.update_document(
        "foo",
        Inc({F(SerialIDCounter.count): 1}),
        upsert=True,
    )
```

### 4.2 Reading and Counting Documents

Butty provides several query methods with automatic pipeline processing and nested query support:

- `get()`: Fetch by exact identity match (raises `DocumentNotFound` if missing), identity values are type-checked
  against the document's `ID_T` parameter
- `find_one()`: Retrieve first matching document (raises `DocumentNotFound` if none match)
- `find_one_or_none()`: Returns first match or `None` if none found
- `find()`: Returns paginated and sorted list of matching documents (supports `skip`, `limit`, and `sort` parameters)
- `find_iter()`: Async generator for large result sets (supports same pagination/sorting as `find()`)
- `count_documents()`: Returns matching document count
- `find_and_count()`: Combined query with total count (optimized with `$facet` aggregation)

All read operations:

- Activate the full lookup pipeline including relationship resolution
- Support nested querying across document relationships

The `find_and_count()` method is particularly optimized, executing both the query and count in a single database request
using the `$facet` aggregation operator.

Example of document querying:

```python
async def main():
    user = await User.get(1)
    users = await User.find(F(User.department.name) == "IT")
```

### 4.3 Updating Documents

Updates can be performed through:

- Standard `save()` cycle (read-modify-save)
- Direct `update()` by identity
- Atomic `update_document()` by identity and update query (`Set()` and `Inc()` are supported for now), not supported for
  versioned documents

The `save()` method's update mode provides version checking when configured.

### 4.4 Deleting Documents

Document deletion requires a full document instance to properly execute relationship handling. The system supports three
deletion modes through `LinkField` configuration: "nothing" (default), "cascade" (deletes referencing documents), and
"propagate" (deletes referenced documents). The "propagate" mode works with both single references and collections
(array/dict) of referenced documents. The current implementation processes these operations sequentially rather than
atomically.

The `delete()` operation triggers `before_delete` hooks prior to removal, allowing for custom cleanup logic, e.g.
removing files in storage associated with the documents. These hooks execute before any relationship processing begins.

Unlike update operations, document deletion does not perform version validation.

Deleted documents are returned with their identity field cleared.

Example of document deletion:

```python
class Department(SerialIDDocument):
    name: str


class User(SerialIDDocument):
    department: Annotated[Department, LinkField(on_delete="cascade")]
    name: str


async def main():
    department = await Department(name="IT").save()
    await User(name="Vasya Pupkin", department=department).save()

    department = await Department.find_one(F(Department.name) == "IT")
    await department.delete()  # also deletes associated users
```

## 5. Utility Features

### 5.1 Indexes

Butty supports MongoDB index configuration through the `IndexedField` marker. Identity fields are always indexed by
default. Indexes are created during engine initialization and support single-field indexing with optional unique
constraints, raising `DuplicateKeyError` on constraint violations. The current implementation does not support compound
indexes. All index operations execute asynchronously during the engine setup phase.

```
class User(SerialIDDocument):
    login: Annotated[str, IndexedField(unique=True)]
```

### 5.2 Hooks

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

### 5.3 Predefined Document Types

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
