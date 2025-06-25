# 1. Introduction

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
