# 2. Core Concepts

## 2.1 Document Definition

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

## 2.2 Identity Management

Butty offers flexible identity management for both MongoDB-native and custom identifiers. Each document must declare
exactly one identity field marked with `IdentityField()`, with its type matching the document's `ID_T` generic
parameter. This field acts as the primary key for all persistence operations.

The identity lifecycle differentiates between transient documents (with `None` identity) and persisted ones, requiring
the identity field to be optional in most cases. When saving a transient document, the system generates a new identity
based on the configured strategy and inserts the document. For documents with existing identities, save operations
perform updates by default, though this can be configured via the `save()` method's `mode` parameter.

Three primary identity strategies are supported through `IdentityField()` configuration:

### Native MongoDB `_id`

The strategy is automatically detected when the `_id` alias is present in the identity field declaration. While offering
optimal database performance, this requires additional Pydantic configuration for JSON serialization and ties the
application to MongoDB's identifier format.

Example of native MongoDB identity field declaration:

```python
class BaseDocument(Document[ObjectId], ABC):
    id: Annotated[ObjectId | None, IdentityField(alias="_id")] = None
```

### Custom identity

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

### Provided identities

Identity can be managed outside the Butty engine. For example, the identity field can use `default_factory` from
Pydantic's model configuration. Documents with existing identities are treated as persistent by default, requiring
explicit `insert` mode specification for new documents.

Example of provided identity field:

```python
class SerialIDCounter(Document[str]):
    name: Annotated[str, IdentityField()]
    count: int
```

## 2.3 Document Linking

### Direct Links

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

### Backlinks

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

### Automatic Pipeline Generation

By analyzing the complete document relationship graph during initialization, Butty automatically generates MongoDB
aggregation pipelines with nested lookups. This forms the core value of the engine, enabling efficient joins across
related documents while maintaining type safety. The pipelines are generated statically and cannot be dynamically
adjusted during read operations - all nesting levels and lookup paths are predetermined. This design means the
relationship graph cannot contain circular references or self-references, ensuring all document connections can be
resolved through a finite series of lookups.

## 2.4 Query Building

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

## 2.5 Collection Views

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

## 2.6 Versioning for Optimistic Concurrency Control

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

## 2.7 Document Config

Butty provides document configuration through a nested `DocumentConfig` class that should inherit from
`DocumentConfigBase`. This inheritance enables IDE autocompletion and type checking for the available configuration
options:

- `collection_name`: Explicit MongoDB collection name
- `collection_name_from_model`: Document class whose collection should be reused (creates a view)

## 2.8 Fields Declaration

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

## 2.8 Error handling

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

