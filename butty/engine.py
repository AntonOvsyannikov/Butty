from __future__ import annotations

from dataclasses import dataclass
from inspect import iscoroutinefunction
from typing import Any, AsyncGenerator, Awaitable, Callable, Literal, Type, TypeAlias, cast

import pymongo
from motor.core import AgnosticDatabase
from pymongo import ReturnDocument
from pymongo.results import DeleteResult, InsertOneResult, UpdateResult
from typing_extensions import Self

from butty.compat import FieldName, ModelFieldInfo, get_fields_info, parse_obj_as_compat, to_dict
from butty.document import Document, DocumentConfigBase, Hook, HookKind, SaveMode, _documents_registry
from butty.errors import DocumentNotFound, _validate
from butty.fields import KnownExtra, OnDelete
from butty.query import ButtyField, F, MongoQuery, Q, Query

MongoDoc = dict[str, Any]
Doc: TypeAlias = Document[Any]
DocModel: TypeAlias = Type[Doc]

FieldAlias: TypeAlias = str
LinkName: TypeAlias = str
CollectionName: TypeAlias = str

IdentityProvider: TypeAlias = Callable[[], Any] | Callable[[], Awaitable[Any]]
IdentityProviderFactory = Callable[[DocModel], IdentityProvider]

LinkNameFormat: TypeAlias = Callable[[ModelFieldInfo], LinkName]
CollectionNameFormat: TypeAlias = Callable[[DocModel], CollectionName]

LinkType: TypeAlias = Literal["plain", "array", "dict"]
LinkedDocs: TypeAlias = Doc | list[Doc] | dict[Any, Doc]

VersionProvider: TypeAlias = Callable[[Any], Any]

DocModelTo: TypeAlias = DocModel
DocModelFrom: TypeAlias = DocModel


@dataclass(kw_only=True)
class Link:
    local_field: ModelFieldInfo
    link_to: DocModel
    link_name: LinkName
    link_type: LinkType
    on_delete: OnDelete


@dataclass(kw_only=True)
class BackLink:
    local_field: ModelFieldInfo
    link_from: DocModel


@dataclass(kw_only=True)
class DocModelInfo:
    fields: dict[FieldName, ModelFieldInfo]
    identity: ModelFieldInfo
    identity_provider: IdentityProvider | None
    links: dict[FieldName, Link]
    back_links: dict[FieldName, BackLink]
    indexes: list[pymongo.IndexModel]
    version_field: ModelFieldInfo | None
    version_provider: VersionProvider | None

    forward_pipeline: list[MongoQuery] | None = None
    full_pipeline: list[MongoQuery] | None = None


global_hooks: dict[DocModel, dict[HookKind, list[Hook[Any]]]] = {}


async def _await_or_call(f: IdentityProvider) -> Any:
    return await f() if iscoroutinefunction(f) else f()


def _get_register_hook_wrapper(cls: DocModel, hook_kind: HookKind) -> Callable[[Hook[Any]], Hook[Any]]:
    def wrapper(f: Hook[Any]) -> Hook[Any]:
        if cls not in global_hooks:
            global_hooks[cls] = {}
        if hook_kind not in global_hooks[cls]:
            global_hooks[cls][hook_kind] = []
        global_hooks[cls][hook_kind].append(f)
        return f

    return wrapper


async def _call_hooks(doc: Doc, hook_kind: HookKind) -> Doc:
    hooks: list[Hook[Any]] = []
    for cls in doc.__class__.mro():
        if cls in global_hooks and hook_kind in global_hooks[cast(DocModel, cls)]:
            hooks.extend(reversed(global_hooks[cast(DocModel, cls)][hook_kind]))
    for hook in hooks:
        doc = await hook(doc)
    return doc


class Engine:
    def __init__(
            self,
            db: AgnosticDatabase[Any],
            *,
            collection_name_format: CollectionNameFormat = lambda m: m.__name__,
            link_name_format: LinkNameFormat = lambda f: f.alias,
    ):
        """Initialize the MongoDB engine with database connection and naming formats.

        :param db: MongoDB database connection.
        :param collection_name_format: Function to generate collection names from models.
        :param link_name_format: Function to generate field names for links/relations.
        """
        self.db = db
        self.collection_name_format = collection_name_format
        self.link_name_format = link_name_format

        self.doc_models_info: dict[DocModel, DocModelInfo] = {}

        self.cascade_delete_graph: dict[DocModelTo, dict[DocModelFrom, Link]] = {}

    def bind(self, *documents: DocModel) -> Self:
        """Bind document models to this engine instance.

        :param documents: Document models to bind. If empty, uses all registered documents.
        :return: The engine instance for chaining.
        """
        doc_models = documents or _documents_registry
        for doc_model in doc_models:
            _validate(
                not hasattr(doc_model, "__engine__"),
                f"Document {doc_model.__name__} already bound",
            )

            doc_model.__engine__ = self

            doc_meta: DocumentConfigBase = getattr(doc_model, "DocumentConfig", DocumentConfigBase())

            collection_name = getattr(
                doc_meta,
                "collection_name",
                self.collection_name_format(getattr(doc_meta, "collection_name_from_model", doc_model)),
            )

            doc_model.__collection__ = self.db[collection_name]
            self.doc_models_info[doc_model] = self._parse_doc_model(doc_model)
            ButtyField._inject(doc_model)

        for doc_model in doc_models:
            self._make_forward_pipline(doc_model)

        for doc_model in doc_models:
            self._make_full_pipline(doc_model)

        return self

    def unbind(self) -> Self:
        """Unbind all document models from this engine instance.

        :return: The engine instance for chaining.
        """
        for doc_model in [*self.doc_models_info]:
            delattr(doc_model, "__engine__")
            del self.doc_models_info[doc_model]
        return self

    async def init(self) -> Self:
        """Initialize the engine by creating database indexes.

        :return: The engine instance for chaining.
        """
        await self._create_indexes()
        return self

    # ----------------------------------------------------
    # internal API

    async def _save(
            self,
            doc: Doc,
            mode: SaveMode,
    ) -> Doc:
        doc_model = doc.__class__
        info = self.doc_models_info[doc_model]

        mongo_doc = to_dict(
            doc,
            exclude={*info.links, *info.back_links},
            by_alias=True,
        )

        for link in info.links.values():
            link_info = self.doc_models_info[link.link_to]
            linked_docs = cast(LinkedDocs | None, getattr(doc, link.local_field.name, None))

            def get_linked_doc_id(linked_doc: Doc | None) -> Any:
                if linked_docs is None:
                    linked_doc_id = None
                else:
                    assert issubclass(linked_doc.__class__, link.link_to)
                    linked_doc_id = getattr(linked_doc, link_info.identity.name)

                    _validate(
                        linked_doc_id is not None,
                        f"Linked document identity is None for {link.link_to.__name__} "
                        f"while saving {doc.__class__.__name__}",
                    )

                return linked_doc_id

            linked_ids = None
            if linked_docs is not None:
                match link.link_type:
                    case "plain":
                        assert isinstance(linked_docs, Document)
                        linked_ids = get_linked_doc_id(linked_docs)
                    case "array":
                        assert isinstance(linked_docs, (list, tuple))
                        linked_ids = [get_linked_doc_id(linked_doc) for linked_doc in linked_docs]
                    case "dict":
                        assert isinstance(linked_docs, dict)
                        linked_ids = {k: get_linked_doc_id(linked_doc) for k, linked_doc in linked_docs.items()}

            mongo_doc[link.link_name] = linked_ids

        is_mongo_id = info.identity.alias == "_id"
        identity = mongo_doc[info.identity.alias]

        if mode == "auto":
            if identity is None:
                mode = "insert"
            else:
                mode = "update"

        if identity is None:
            _validate(
                mode == "insert",
                f"Save mode must be 'insert' or 'auto' for {doc.__class__.__name__} while saving w/o id",
            )

            if not is_mongo_id:
                _validate(
                    info.identity_provider is not None,
                    f"Identity provider must be given for {doc.__class__.__name__} while saving w/o id",
                )
                assert info.identity_provider is not None
                identity = await _await_or_call(info.identity_provider)
                mongo_doc[info.identity.alias] = identity
                setattr(doc, info.identity.name, identity)
            else:
                del mongo_doc["_id"]

        mongo_query = {info.identity.alias: identity}

        if info.version_field is not None:
            _validate(
                info.version_provider is not None,
                f"Version provider must be set when version field is defined for {doc.__class__.__name__}",
            )
            assert info.version_provider is not None

            prev_version = mongo_doc.get(info.version_field.alias)
            new_version = info.version_provider(prev_version)
            mongo_doc[info.version_field.alias] = new_version
            setattr(doc, info.version_field.name, new_version)

            if prev_version is not None:
                _validate(
                    mode == "update",
                    f"Version must not be set while saving {doc.__class__.__name__} in '{mode}' mode",
                )
                mongo_query = {"$and": [mongo_query, {info.version_field.alias: prev_version}]}
            else:
                _validate(
                    mode != "update",
                    f"Version must be set while saving {doc.__class__.__name__} in '{mode}' mode",
                )

        match mode:
            case "update" | "upsert":
                _validate(
                    identity is not None,
                    f"Identity must be provided while saving {doc.__class__.__name__} in '{mode}' mode",
                )
                update_result: UpdateResult = await doc_model.__collection__.update_one(
                    mongo_query,
                    {"$set": mongo_doc},
                    upsert=(mode == "upsert"),
                )
                if not update_result.matched_count:
                    raise DocumentNotFound(doc_model, "save", mongo_query)

            case "insert":
                insert_result: InsertOneResult = await doc_model.__collection__.insert_one(mongo_doc)
                if is_mongo_id and identity is None:
                    identity = insert_result.inserted_id
                    mongo_doc[info.identity.alias] = identity
                    setattr(doc, info.identity.name, identity)

        return doc

    async def _get(
            self,
            doc_model: DocModel,
            id_: Any,
    ) -> Doc:
        info = self.doc_models_info[doc_model]
        return await self._find_one(doc_model, F(getattr(doc_model, info.identity.name)) == id_)

    async def _find_one(
            self,
            doc_model: DocModel,
            query: Query,
    ) -> Doc:
        res = await self._find_one_or_none(doc_model, query)
        if res is None:
            raise DocumentNotFound(doc_model, "find_one", query)
        return res

    async def _find_one_or_none(
            self,
            doc_model: DocModel,
            query: Query,
    ) -> Doc | None:
        return res[0] if (res := await self._find(doc_model, query, limit=1)) else None

    def _get_find_pipeline(
            self,
            model_info: DocModelInfo,
            query: MongoQuery,
            *,
            sort: Query | None = None,
            skip: int | None = None,
            limit: int | None = None,
    ) -> list[MongoQuery]:
        pipline: list[MongoQuery] = []

        assert model_info.full_pipeline is not None
        pipline.extend(model_info.full_pipeline)

        if query:
            pipline.append({"$match": query})

        if sort is not None:
            pipline.append({"$sort": Q(sort)})

        if skip is not None:
            pipline.append({"$skip": skip})

        if limit is not None:
            pipline.append({"$limit": limit})

        return pipline

    def _get_count_pipeline(
            self,
            model_info: DocModelInfo,
            query: MongoQuery,
    ) -> list[MongoQuery]:
        pipline: list[MongoQuery] = []

        if query:
            assert model_info.full_pipeline is not None
            pipline.extend(model_info.full_pipeline)
            pipline.append({"$match": Q(query)})

        pipline.extend([
            {"$count": "count"},
            {"$project": {"count": 1}},
        ])
        return pipline

    async def _find(
            self,
            doc_model: DocModel,
            query: Query | None,
            *,
            sort: Query | None = None,
            skip: int | None = None,
            limit: int | None = None,
    ) -> list[Doc]:
        pipline = self._get_find_pipeline(
            self.doc_models_info[doc_model],
            Q(query),
            sort=sort,
            skip=skip,
            limit=limit,
        )
        res = await doc_model.__collection__.aggregate(pipline).to_list(None)
        return parse_obj_as_compat(list[doc_model], res)  # type: ignore[valid-type]

    async def _find_iter(
            self,
            doc_model: DocModel,
            query: Query | None,
            *,
            sort: Query | None = None,
            skip: int | None = None,
            limit: int | None = None,
    ) -> AsyncGenerator[Doc]:
        pipline = self._get_find_pipeline(
            self.doc_models_info[doc_model],
            Q(query),
            sort=sort,
            skip=skip,
            limit=limit,
        )
        async for d in doc_model.__collection__.aggregate(pipline):
            yield parse_obj_as_compat(doc_model, d)

    async def _count_documents(
            self,
            doc_model: DocModel,
            query: Query | None,
    ) -> int:
        pipline = self._get_count_pipeline(
            self.doc_models_info[doc_model],
            Q(query),
        )
        res = await doc_model.__collection__.aggregate(pipline).to_list(None)
        return cast(int, res[0]["count"])

    async def _find_and_count(
            self,
            doc_model: DocModel,
            query: Query | None,
            *,
            sort: Query | None,
            skip: int | None,
            limit: int | None,
    ) -> tuple[list[Doc], int]:
        query = Q(query)
        data_pipline = self._get_find_pipeline(
            self.doc_models_info[doc_model],
            query,
            sort=sort,
            skip=skip,
            limit=limit,
        )
        count_pipline = self._get_count_pipeline(
            self.doc_models_info[doc_model],
            query,
        )
        pipline = [
            {"$facet": {
                "data": data_pipline,
                "count": count_pipline,
            }},
        ]
        res = await doc_model.__collection__.aggregate(pipline).to_list(None)
        return (
            parse_obj_as_compat(list[doc_model], res[0]["data"]),  # type: ignore[valid-type]
            res[0]["count"][0]["count"]
        )

    async def _update_document(
            self,
            doc_model: DocModel,
            id_: Any,
            update: Query,
            upsert: bool,
    ) -> Doc:
        info = self.doc_models_info[doc_model]
        _validate(
            info.version_field is None,
            f"Update operations are not supported for versioned model {doc_model.__name__}",
        )
        query = Q(F(getattr(doc_model, info.identity.name)) == id_)
        res = await doc_model.__collection__.find_one_and_update(
            query,
            Q(update),
            return_document=ReturnDocument.AFTER,
            upsert=upsert,
        )
        if res is None:
            raise DocumentNotFound(doc_model, "update_document", query)
        return doc_model(**res)  # noqa

    async def _delete(
            self,
            doc: Doc,
    ) -> Doc:
        doc = await doc.before_delete()

        doc_model = doc.__class__
        info = self.doc_models_info[doc_model]

        identity = getattr(doc, info.identity.name, None)
        _validate(
            identity is not None,
            f"Identity must be provided for {doc.__class__.__name__} to delete",
        )

        for doc_model_from, link in self.cascade_delete_graph.get(doc_model, {}).items():
            for cascade_doc in await doc_model_from.find(
                    F(getattr(getattr(doc_model_from, link.local_field.name), info.identity.alias)) == identity
            ):
                await cascade_doc.delete()

        for link in info.links.values():
            if link.on_delete == "propagate":
                linked_docs = cast(LinkedDocs | None, getattr(doc, link.local_field.name, None))

                linked_doc: Doc
                if linked_docs is not None:
                    match link.link_type:
                        case "plain":
                            assert isinstance(linked_docs, Document)
                            await linked_docs.delete()
                        case "array":
                            assert isinstance(linked_docs, list)
                            for linked_doc in linked_docs:
                                await linked_doc.delete()
                        case "dict":
                            assert isinstance(linked_docs, dict)
                            for linked_doc in linked_docs.values():
                                await linked_doc.delete()

        query = {
            info.identity.alias: identity,
        }

        result: DeleteResult = await doc_model.__collection__.delete_one(query)

        if result.deleted_count < 1:
            raise DocumentNotFound(doc_model, "delete", query)

        setattr(doc, info.identity.name, None)
        return doc

    # ----------------------------------------------------

    def _parse_doc_model(self, doc_model: DocModel) -> DocModelInfo:
        identity: ModelFieldInfo | None = None
        identity_provider: IdentityProvider | None = None
        links: dict[FieldName, Link] = {}
        back_links: dict[FieldName, BackLink] = {}
        indexes: list[pymongo.IndexModel] = []
        version_field: ModelFieldInfo | None = None
        version_provider: VersionProvider | None = None

        fields = get_fields_info(doc_model)

        for f in fields.values():
            extra = f.extra
            is_identity = extra.get(KnownExtra.is_identity, False)

            if is_identity:
                _validate(
                    identity is None,
                    f"Identity field is already defined for {doc_model.__name__}",
                )
                identity = f

                is_mongo_id = identity.alias == "_id"
                identity_provider = extra.get(KnownExtra.identity_provider)
                identity_provider_factory = extra.get(KnownExtra.identity_provider_factory)
                if not is_mongo_id:
                    if identity_provider_factory is not None:
                        _validate(
                            identity_provider is None,
                            f"Identity provider and factory must not be set at once"
                            f" for {doc_model.__name__}.{f.name}",
                        )
                        identity_provider = identity_provider_factory(doc_model)
                    indexes.append(pymongo.IndexModel(f.alias, unique=True))
                else:
                    _validate(
                        all([
                            identity_provider is None,
                            identity_provider_factory is None,
                        ]),
                        f"Nor identity provider nor factory can be set for native MongoDB _id"
                        f" for {doc_model.__name__}.{f.name}",
                    )

                continue

            is_index = bool(extra.get(KnownExtra.is_index))
            if is_index:
                if KnownExtra.index_unique in extra:
                    indexes.append(pymongo.IndexModel(f.alias, unique=extra[KnownExtra.index_unique]))
                else:
                    indexes.append(pymongo.IndexModel(f.alias))

            try:
                is_link = issubclass(f.annotation.core_type, Document)
            except TypeError:
                is_link = False

            if is_link and not extra.get(KnownExtra.link_ignore):
                is_backlink = bool(extra.get(KnownExtra.is_back_link))

                if not is_backlink:
                    # forward link
                    link_name = extra.get(KnownExtra.link_name) or self.link_name_format(f)

                    link_to = cast(DocModel, f.annotation.core_type)

                    o = f.annotation.outer_type
                    link_type = "array" if o in (list, tuple) else "dict" if o is dict else "plain"

                    on_delete = extra.get(KnownExtra.on_delete, "nothing")

                    _validate(
                        on_delete != "cascade" or link_type == "plain",
                        f"Link must be plain to support cascade delete for {doc_model.__name__}.{f.name}",
                    )

                    link = Link(
                        local_field=f,
                        link_to=link_to,
                        link_name=link_name,
                        link_type=cast(LinkType, link_type),
                        on_delete=on_delete,
                    )
                    links[f.name] = link

                    if on_delete == "cascade":
                        if link_to not in self.cascade_delete_graph:
                            self.cascade_delete_graph[link_to] = {}
                        _validate(
                            doc_model not in self.cascade_delete_graph[link_to],
                            f"Only one link for cascade delete is allowed"
                            f" from {doc_model.__name__} to {link_to.__name__}"
                            f" (second {link.local_field.name} found)"
                        )
                        self.cascade_delete_graph[link_to][doc_model] = link
                else:
                    # back link
                    _validate(
                        all([
                            f.annotation.outer_type in (list, tuple),
                            f.annotation.optional,
                            not f.required,
                        ]),
                        f"Backlink {f.name} must be defined as optional array with default for {doc_model.__name__}",
                    )

                    back_links[f.name] = BackLink(
                        local_field=f,
                        link_from=cast(DocModel, f.annotation.core_type),
                    )

                continue

            is_version = bool(extra.get(KnownExtra.is_version))
            if is_version:
                _validate(
                    version_field is None,
                    f"Version field already defined for {doc_model.__name__}",
                )
                version_field = f
                version_provider = extra.get(KnownExtra.version_provider)

        _validate(
            identity is not None,
            f"No identity defined for {doc_model.__name__}",
        )
        assert identity is not None

        return DocModelInfo(
            fields=fields,
            identity=identity,
            identity_provider=identity_provider,
            links=links,
            back_links=back_links,
            indexes=indexes,
            version_field=version_field,
            version_provider=version_provider,
        )

    def _make_forward_pipline(self, doc_model: DocModel) -> None:
        _validate(
            doc_model in self.doc_models_info,
            f"Document {doc_model.__name__} is not bound",
        )

        model_info = self.doc_models_info[doc_model]

        pipeline = []

        for link in model_info.links.values():
            _validate(
                link.link_to in self.doc_models_info,
                f"Link Document {link.link_to.__name__} is not bound",
            )
            link_info = self.doc_models_info[link.link_to]

            if link_info.forward_pipeline is None:
                self._make_forward_pipline(link.link_to)

            other_aliases = \
                {
                    f.alias
                    for f in model_info.fields.values()
                    if f.name != link.local_field.name
                    if f.alias != "_id"
                } | {
                    l.link_name
                    for l in model_info.links.values()
                    if l != link
                }

            match link.link_type:
                case "plain":
                    lookup: dict[str, Any] = {
                        "from": link.link_to.__collection__.name,
                        "localField": link.link_name,
                        "foreignField": link_info.identity.alias,
                        "as": link.local_field.alias,
                    }
                    if link_info.forward_pipeline:
                        lookup["pipeline"] = link_info.forward_pipeline

                    pipeline.extend([
                        {"$lookup": lookup},
                        {"$set": {link.local_field.alias: {"$first": "$" + link.local_field.alias}}},
                    ])

                case "array":
                    pipeline.extend([
                        {"$unwind": {
                            "path": "$" + link.link_name,
                            "preserveNullAndEmptyArrays": True,
                        }}
                    ])

                    lookup = {
                        "from": link.link_to.__collection__.name,
                        "localField": link.link_name,
                        "foreignField": link_info.identity.alias,
                        "as": link.link_name,
                    }
                    if link_info.forward_pipeline:
                        lookup["pipeline"] = link_info.forward_pipeline

                    pipeline.extend([
                        {"$lookup": lookup},
                        {"$set": {
                            link.link_name: {"$first": "$" + link.link_name},
                        }},
                        {"$group": {
                                       "_id": "$_id",
                                       link.local_field.alias: {"$push": "$" + link.link_name},
                                   } | {
                                       a: {"$first": "$" + a}
                                       for a in other_aliases
                                   }},
                    ])

                case "dict":
                    pipeline.extend([
                        {"$set": {
                            link.link_name: {"$objectToArray": "$" + link.link_name},
                        }},
                        {"$unwind": {
                            "path": "$" + link.link_name,
                            "preserveNullAndEmptyArrays": True,
                        }},
                    ])

                    lookup = {
                        "from": link.link_to.__collection__.name,
                        "localField": link.link_name + ".v",
                        "foreignField": link_info.identity.alias,
                        "as": link.link_name + ".v",
                    }
                    if link_info.forward_pipeline:
                        lookup["pipeline"] = link_info.forward_pipeline

                    pipeline.extend([
                        {"$lookup": lookup},
                        {"$set": {
                            link.link_name + ".v": {"$first": "$" + link.link_name + ".v"},
                        }},
                        {"$group": {
                                       "_id": "$_id",
                                       link.local_field.alias: {"$push": "$" + link.link_name},
                                   } | {
                                       a: {"$first": "$" + a}
                                       for a in other_aliases
                                   }},
                        {"$set": {
                            link.local_field.alias: {
                                "$arrayToObject": {
                                    "$filter": {
                                        "input": "$" + link.local_field.alias,
                                        "cond": {"$ne": ["$this", {}]},
                                    },
                                },
                            },
                        }}]
                    )

        project = {f.alias: 1 for f in model_info.fields.values() if f.name not in model_info.back_links}
        pipeline.extend([
            {"$project": project},
        ])

        self.doc_models_info[doc_model].forward_pipeline = pipeline

    def _make_full_pipline(self, doc_model: DocModel) -> None:
        _validate(
            doc_model in self.doc_models_info,
            f"Document {doc_model.__name__} is not bound",
        )

        model_info = self.doc_models_info[doc_model]

        back_pipeline: list[MongoQuery] = []

        assert model_info.forward_pipeline is not None
        back_pipeline.extend(model_info.forward_pipeline)

        for field_name, back_link in model_info.back_links.items():
            _validate(
                back_link.link_from in self.doc_models_info,
                f"Backlink document {back_link.link_from.__name__} is not bound",
            )
            back_link_info = self.doc_models_info[back_link.link_from]

            if back_link_info.full_pipeline is None:
                self._make_full_pipline(back_link.link_from)

            # find single reference from foreign model to doc_model
            references = [
                link.link_name
                for link in back_link_info.links.values()
                if link.link_to is doc_model and link.link_type == "plain"
            ]
            _validate(
                len(references) == 1,
                f"Can not construct backlink for {doc_model.__name__}.{field_name}"
                f" (only single link from {back_link.link_from.__name__} allowed, "
                f"{len(references)} found)",
            )
            lookup: dict[str, Any] = {
                "from": back_link.link_from.__collection__.name,
                "localField": model_info.identity.alias,
                "foreignField": references[0],
                "as": back_link.local_field.alias,
            }
            if back_link_info.full_pipeline:
                lookup["pipeline"] = back_link_info.full_pipeline

            back_pipeline.extend([
                {"$lookup": lookup},
            ])

        model_info.full_pipeline = back_pipeline

    async def _create_indexes(self) -> None:
        for doc_model, info in self.doc_models_info.items():
            if info.indexes:
                await doc_model.__collection__.create_indexes(info.indexes)
