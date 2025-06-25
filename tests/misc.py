from motor.core import AgnosticCollection


async def get_indices_names(collection: AgnosticCollection) -> set[str]:
    return {idx["name"] async for idx in collection.list_indexes()}
