"""Shadow semantic document search.

Upgrades retrieval from keyword matching to
meaning-based search using local embeddings.

How it works:

    document text
        -> chunks
        -> embedding vectors (Ollama, local)
        -> cosine similarity vs the question
        -> most relevant chunks
        -> Qwen answers

A keyword fallback keeps search working when
Ollama is unavailable.
"""

import json
import math
import urllib.request

import settings as settings_store

try:
    # Reuse the keyword matcher from the document
    # module as the fallback engine.

    from document_reader import search_chunks

    KEYWORD_FALLBACK = True

except ImportError:

    KEYWORD_FALLBACK = False


OLLAMA_URL = "http://localhost:11434/api/embeddings"

# Small (46 MB), fast, local embedding model.

EMBED_MODEL = "all-minilm"

# Cache embeddings for the loaded document so a
# question does not recompute the whole library.

embedding_cache = []

cache_signature = None

ollama_healthy = True


# ---------------- OLLAMA EMBEDDINGS ----------------


def get_embedding(text):
    # Returns a list of floats, or None if the
    # embedding service is unreachable.

    global ollama_healthy

    if not ollama_healthy:
        return None

    try:
        payload = json.dumps(
            {
                "model": EMBED_MODEL,
                "prompt": text[:2000]
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={
                "Content-Type": "application/json"
            }
        )

        response = urllib.request.urlopen(
            request,
            timeout=15
        )

        data = json.loads(response.read())

        embedding = data.get("embedding")

        if not embedding:
            raise ValueError("empty embedding")

        return embedding

    except Exception:
        # One failure disables the semantic engine
        # for this session and switches to keyword
        # fallback, so Shadow never hangs.

        ollama_healthy = False

        return None


def cosine_similarity(vec_a, vec_b):
    # Cosine of the angle between two vectors:
    # 1.0 = identical meaning, 0.0 = unrelated.

    dot = 0.0

    norm_a = 0.0

    norm_b = 0.0

    for value_a, value_b in zip(vec_a, vec_b):

        dot += value_a * value_b

        norm_a += value_a * value_a

        norm_b += value_b * value_b

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / math.sqrt(norm_a * norm_b)


# ---------------- CACHE ----------------


def _cache_signature(chunks):
    # Cheap fingerprint of the chunk list so a
    # new document invalidates the cache.

    return (
        len(chunks),
        len(chunks[0]) if chunks else 0,
        len(chunks[-1]) if chunks else 0
    )


def _build_cache(chunks):
    # Embed every chunk once, in order. If any
    # embedding fails, the cache is abandoned
    # and search falls back to keywords.

    global embedding_cache
    global cache_signature
    global ollama_healthy

    embedding_cache = []

    cache_signature = _cache_signature(chunks)

    for index, chunk in enumerate(chunks):

        embedding = get_embedding(chunk)

        if embedding is None:
            embedding_cache = []

            cache_signature = None

            ollama_healthy = True

            return False

        embedding_cache.append(embedding)

        print(
            f"[Shadow BRAIN] Embedded chunk "
            f"{index + 1}/{len(chunks)}"
        )

    return True


def ensure_cache(chunks):
    # Make sure the cache matches this document.

    if _cache_signature(chunks) != cache_signature:

        return _build_cache(chunks)

    return bool(embedding_cache)


# ---------------- PUBLIC SEARCH ----------------


def semantic_search_chunks(
    chunks,
    query,
    max_results=3
):
    # Meaning-based search with keyword fallback.

    if not chunks:
        return []

    if not ensure_cache(chunks):
        # Embeddings unavailable: old behaviour.

        if KEYWORD_FALLBACK:
            return search_chunks(
                chunks,
                query,
                max_results
            )

        return chunks[:max_results]

    query_embedding = get_embedding(query)

    if query_embedding is None:
        # Restore health for the next document, but
        # answer this question via keywords.

        ollama_healthy = True

        if KEYWORD_FALLBACK:
            return search_chunks(
                chunks,
                query,
                max_results
            )

        return chunks[:max_results]

    scored = []

    for index, embedding in enumerate(embedding_cache):

        score = cosine_similarity(
            query_embedding,
            embedding
        )

        scored.append((score, index))

    scored.sort(reverse=True)

    results = []

    for score, index in scored[:max_results]:

        results.append(chunks[index])

        print(
            f"[Shadow BRAIN] match {len(results)}: "
            f"chunk {index + 1} "
            f"(similarity {score:.2f})"
        )

    return results


if __name__ == "__main__":

    print("Shadow SEMANTIC SEARCH TEST")
    print("-" * 40)

    demo_chunks = [
        "The internship took place at Obadenahalli "
        "Industrial Area, KIADB Phase III, Bengaluru. "
        "Mr. Sanjay UD supervised the work.",

        "The report explains how to score good marks "
        "in board exams: time management, revision, "
        "sample papers and group study.",

        "SolidWorks is used for 3D mechanical CAD "
        "modelling of machine parts and assemblies."
    ]

    questions = [
        "how do I pass exams with high marks",
        "who supervised the internship",
        "what CAD software is mentioned"
    ]

    for question in questions:
        print()
        print("Q:", question)

        hits = semantic_search_chunks(
            demo_chunks,
            question,
            max_results=1
        )

        print(
            "best chunk:",
            hits[0][:70] + "..."
            if hits else "none"
        )

    settings_store.save_settings()
