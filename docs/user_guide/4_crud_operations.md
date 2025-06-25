# 4. CRUD Operations

## 4.1 Creating Documents

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

## 4.2 Reading and Counting Documents

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

## 4.3 Updating Documents

Updates can be performed through:

- Standard `save()` cycle (read-modify-save)
- Direct `update()` by identity
- Atomic `update_document()` by identity and update query (`Set()` and `Inc()` are supported for now), not supported for
  versioned documents

The `save()` method's update mode provides version checking when configured.

## 4.4 Deleting Documents

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
