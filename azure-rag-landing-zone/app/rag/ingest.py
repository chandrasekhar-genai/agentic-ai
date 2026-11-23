"""Create/update the Azure AI Search index and load the documents.

Runs as a Container Apps job inside the VNet (Search and OpenAI are private):
    az containerapp job start -n caj-ingest-<name> -g rg-<name>
"""

from __future__ import annotations

import logging

from .chunking import load_docs
from .clients import AzureEmbedder
from .config import Settings

log = logging.getLogger("rag.ingest")


def ensure_index(s: Settings) -> None:
    from azure.identity import DefaultAzureCredential
    from azure.search.documents.indexes import SearchIndexClient
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration,
        SearchableField,
        SearchField,
        SearchFieldDataType,
        SearchIndex,
        SimpleField,
        VectorSearch,
        VectorSearchProfile,
    )

    index = SearchIndex(
        name=s.search_index,
        fields=[
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(name="source", type=SearchFieldDataType.String, filterable=True, facetable=True),
            SearchableField(name="title", type=SearchFieldDataType.String),
            SearchableField(name="content", type=SearchFieldDataType.String),
            SearchField(
                name="content_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=s.embedding_dimensions,
                vector_search_profile_name="hnsw-profile",
            ),
        ],
        vector_search=VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
            profiles=[VectorSearchProfile(name="hnsw-profile", algorithm_configuration_name="hnsw")],
        ),
    )
    SearchIndexClient(s.search_endpoint, DefaultAzureCredential()).create_or_update_index(index)


def main(batch_size: int = 16) -> None:
    from azure.identity import DefaultAzureCredential
    from azure.search.documents import SearchClient

    logging.basicConfig(level=logging.INFO)
    s = Settings()
    ensure_index(s)
    chunks = load_docs(s.docs_dir)
    embedder = AzureEmbedder(s)
    client = SearchClient(s.search_endpoint, s.search_index, DefaultAzureCredential())
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i: i + batch_size]
        vectors = embedder.embed([f"{c.title}\n{c.content}" for c in batch])
        docs = [{"id": c.id, "source": c.source, "title": c.title, "content": c.content, "content_vector": v}
                for c, v in zip(batch, vectors, strict=True)]
        client.merge_or_upload_documents(docs)
        log.info("indexed %d/%d chunks", min(i + batch_size, len(chunks)), len(chunks))


if __name__ == "__main__":
    main()
