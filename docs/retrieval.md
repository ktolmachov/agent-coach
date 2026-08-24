# Local Vector Memory

D8 adds a real in-process retrieval path behind `rag.search` without changing
Agent Core. The default diploma profile remains the deterministic mock
composition. Local-vector retrieval is an explicit adapter profile.

## Boundary

```text
local-vector composition
        |
AgentRunner
        |
ToolExecutionPort
        |
LocalVectorRagTool
        |
HashedNgramEmbedding + InMemoryCosineStore
        |
packaged synthetic diploma knowledge base
```

Core still sees only `ToolExecutionPort` and a compact `ToolResult`. Embedding
and vector-store ports live in `agent_coach.retrieval`, not in Core.

## What is computed

The offline embedder is a deterministic signed hashing trick over word
unigrams, word bigrams and character trigrams. It produces a 384-dimension
numeric vector, L2-normalizes it and compares vectors with cosine similarity.

That is real vector arithmetic:

- identical text yields an identical vector;
- self-similarity is `1.0`;
- related public notes rank above unrelated text;
- scores are finite values in `[-1.0, 1.0]`.

It is not a downloaded neural embedding model and not a production vector
database. The index lives only in process memory and is rebuilt from the
packaged corpus on each composition.

## Trusted limits

`top_k` may come from the frozen public `rag.search` schema. Values outside
the trusted `[1, 8]` bound are rejected fail-closed; they are not clamped.
The similarity threshold is trusted composition config. The adapter also
rejects unexpected fields such as `threshold`. A hit is kept only when its cosine is at least the caller-supplied
`threshold`. Distinctive overlap (title term or token length >= 6) is then
required unless cosine also clears the stricter semantic-only bound. Title
and rare-token support cannot keep a hit below threshold, so caller
`threshold=1.0` returns no weaker scores. Short homonym overlaps such as
`card front back` are dropped. Weak, unrelated or zero-score queries return
an empty hit list instead of a random top-1.

`index_fingerprint` identifies the built vector index, including embedder
width and vectors. The knowledge base exposes `chunk_set_fingerprint` for the
same chunk identity the adapter compares against the store. The adapter
rejects embedder/config dimension drift. Public corpus sources must be a single `*.md` filename label without `.` /
`..` path components. Provenance `source` must be a public label: no drive
letters, absolute paths, HomeTutor paths or email identifiers. Other
provenance strings get the same private-path and identifier scan. Chunk-level
provenance, if present, must match the corpus mapping exactly; extra fields
and secret-like values are rejected. Loader text checks also reject Bearer
credentials.

Hashed lexical retrieval remains a D8 limitation. Shared pedagogical tokens
can still look similar across domains. The store therefore drops queries that
carry unmatched distinctive tokens unless cosine reaches the semantic-only
bound. That is a precision guard, not neural semantic understanding.

The store computes true cosine similarity: it divides the dot product by both
L2 norms, so an unnormalized embedder still scores in `[-1.0, 1.0]`. The
tokenizer is Unicode-aware, so a Russian query can match Russian terms in the
synthetic corpus.

## Evidence fields

A successful tool result projects:

- bounded query;
- selected `chunk_id` values;
- cosine scores;
- threshold;
- corpus version and sha256;
- citation labels.

Raw vectors, private paths and prompt-injection text do not belong in the
public projection.

## Offline use

```bash
python -c "from agent_coach.retrieval import build_local_vector_composition; c = build_local_vector_composition('How does photosynthesis store energy in glucose using chlorophyll?'); r = c.runner.run(c.request); print(r.answer_status, r.sources[0]['file_name'])"
```

The packaged corpus is synthetic public review material. It contains no learner
records, credentials or HomeTutor runtime dependency.
