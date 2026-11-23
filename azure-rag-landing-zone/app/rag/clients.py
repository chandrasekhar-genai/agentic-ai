"""Model and retrieval clients.

Azure: Azure OpenAI through the APIM AI gateway (Entra ID token, no keys) and
Azure AI Search hybrid (keyword + vector) retrieval.
Local: hashed bag-of-words embeddings, in-memory cosine search and an extractive
"model". No network, fully deterministic: used for the offline demo, unit tests
and the CI eval gate.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Protocol

from .chunking import Chunk
from .config import Settings

COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class Retriever(Protocol):
    def search(self, query: str, vector: list[float], k: int) -> list[Hit]: ...


class ChatModel(Protocol):
    def complete(self, system: str, user: str) -> str: ...


# --------------------------------------------------------------------------- Azure


def _openai_client(s: Settings):
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AzureOpenAI

    # azure_endpoint is the APIM gateway; APIM exposes the API under /openai like Azure OpenAI itself
    return AzureOpenAI(
        azure_endpoint=s.openai_endpoint,
        azure_ad_token_provider=get_bearer_token_provider(DefaultAzureCredential(), COGNITIVE_SCOPE),
        api_version=s.openai_api_version,
        max_retries=2,
    )


class AzureEmbedder:
    def __init__(self, s: Settings) -> None:
        self.client, self.s = _openai_client(s), s

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self.client.embeddings.create(
            model=self.s.embedding_deployment, input=texts, dimensions=self.s.embedding_dimensions
        )
        return [d.embedding for d in resp.data]


class AzureChat:
    def __init__(self, s: Settings) -> None:
        self.client, self.s = _openai_client(s), s

    def complete(self, system: str, user: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.s.chat_deployment,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
            max_tokens=600,
        )
        return resp.choices[0].message.content or ""


class AzureSearchRetriever:
    def __init__(self, s: Settings) -> None:
        from azure.identity import DefaultAzureCredential
        from azure.search.documents import SearchClient

        self.client = SearchClient(s.search_endpoint, s.search_index, DefaultAzureCredential())

    def search(self, query: str, vector: list[float], k: int) -> list[Hit]:
        from azure.search.documents.models import VectorizedQuery

        results = self.client.search(
            search_text=query,
            vector_queries=[VectorizedQuery(vector=vector, k_nearest_neighbors=k * 2, fields="content_vector")],
            select=["id", "source", "title", "content"],
            top=k,
        )
        return [
            Hit(Chunk(r["id"], r["source"], r["title"], r["content"]), float(r["@search.score"]))
            for r in results
        ]


# --------------------------------------------------------------------------- Local

_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("a an and are as at be by can do does for from how i in is it of on or the to what when where which who "
            "why with you your we our must should".split())
_SUFFIXES = ("ations", "ation", "ions", "ion", "ing", "ed", "es", "s", "e")
DIMS = 512


def _stem(w: str) -> str:
    """Tiny suffix stripper: enough to match approve/approved, applies/apply, minute/minutes."""
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    for suf in _SUFFIXES:
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokens(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOP]


class HashEmbedder:
    """Feature-hashed term frequencies, L2-normalised. Crude, but deterministic and offline."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * DIMS
            for w in tokens(t):
                v[int(hashlib.md5(w.encode(), usedforsecurity=False).hexdigest(), 16) % DIMS] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class InMemoryRetriever:
    def __init__(self, chunks: list[Chunk], embedder: Embedder) -> None:
        self.chunks = chunks
        self.vectors = embedder.embed([f"{c.title}\n{c.content}" for c in chunks])

    def search(self, query: str, vector: list[float], k: int) -> list[Hit]:
        scored = [Hit(c, sum(a * b for a, b in zip(vector, v, strict=True)))
                  for c, v in zip(self.chunks, self.vectors, strict=True)]
        return sorted(scored, key=lambda h: -h.score)[:k]


class ExtractiveChat:
    """Offline baseline "model": picks the source sentences that best answer the question.

    Sentences are scored by IDF-weighted term overlap with the question (section
    titles count at half weight). If the best sentence covers too little of the
    question, it refuses, like the real model is instructed to.
    """

    def __init__(self, min_coverage: float = 0.4) -> None:
        self.min_coverage = min_coverage

    def complete(self, system: str, user: str) -> str:
        question = user.split("Question:", 1)[-1].strip()
        q = set(tokens(question))
        sentences: list[tuple[str, str, set[str], set[str]]] = []  # (text, ref, tokens, title tokens)
        pattern = r"\[(\d+)\] ([^\n]*?) \([^)]*\)\n(.*?)(?=\n\[\d+\] |\nQuestion:|\Z)"
        for m in re.finditer(pattern, user, re.DOTALL):
            ref, title, body = m.group(1), m.group(2), m.group(3)
            for sent in re.split(r"(?<=[.!?])\s+|\n+", body):
                sent = sent.strip(" -*")
                if sent:
                    sentences.append((sent, ref, set(tokens(sent)), set(tokens(title))))
        if not q or not sentences:
            return "I don't know based on the available documents."

        n = len(sentences)
        idf = {t: math.log((n + 1) / (1 + sum(t in s[2] for s in sentences))) + 1 for t in q}
        total = sum(idf.values())

        def score(s: tuple[str, str, set[str], set[str]]) -> float:
            return sum(idf[t] for t in q & s[2]) + 0.5 * sum(idf[t] for t in (q & s[3]) - s[2])

        ranked = sorted(sentences, key=lambda s: -score(s))
        if score(ranked[0]) / total < self.min_coverage:
            return "I don't know based on the available documents."
        best = [s for s in ranked[:2] if score(s) >= 0.6 * score(ranked[0])]
        return " ".join(f"{s[0]} [{s[1]}]" for s in best)
