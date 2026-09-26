#!/usr/bin/env python3
"""
Tiny RAG layer for Aurora support.

Loads the Markdown knowledge base, splits it into chunks, embeds them with a
local sentence-transformers model, and does cosine-similarity retrieval. The
embedding index is cached on disk so it is only computed once.

    python rag.py            # build the index and run a sample query
"""

import os
import glob

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
KB_DIR = os.path.join(HERE, "knowledge_base")
CACHE = os.path.join(HERE, "kb_index.npz")
MODEL_NAME = os.environ.get("EMBED_MODEL", "all-MiniLM-L6-v2")

_model = None
_chunks = None      # list of dicts: {source, visibility, text}
_vectors = None     # np.ndarray (n, d), L2-normalized


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def _split(text):
    """Split a document into paragraph-ish chunks, merging very short ones."""
    parts, buf = [], ""
    for para in [p.strip() for p in text.split("\n\n")]:
        if not para:
            continue
        if len(buf) + len(para) < 400:
            buf = (buf + "\n\n" + para).strip()
        else:
            if buf:
                parts.append(buf)
            buf = para
    if buf:
        parts.append(buf)
    return parts


def _load_chunks():
    chunks = []
    for path in sorted(glob.glob(os.path.join(KB_DIR, "*.md"))):
        source = os.path.basename(path)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        visibility = "internal" if ("internal" in source.lower()
                                    or "visibility: internal" in text.lower()) else "public"
        for piece in _split(text):
            chunks.append({"source": source, "visibility": visibility, "text": piece})
    return chunks


def _signature():
    sig = []
    for path in sorted(glob.glob(os.path.join(KB_DIR, "*.md"))):
        st = os.stat(path)
        sig.append(f"{os.path.basename(path)}:{int(st.st_mtime)}:{st.st_size}")
    return "|".join(sig)


def build_index(force=False):
    """Build (or load from cache) the chunk list + embedding matrix."""
    global _chunks, _vectors
    sig = _signature()
    if not force and os.path.exists(CACHE):
        data = np.load(CACHE, allow_pickle=True)
        if str(data.get("sig")) == sig:
            _vectors = data["vectors"]
            _chunks = list(data["chunks"])
            return
    _chunks = _load_chunks()
    texts = [c["text"] for c in _chunks]
    _vectors = _get_model().encode(texts, normalize_embeddings=True,
                                   show_progress_bar=False).astype("float32")
    np.savez(CACHE, sig=sig, vectors=_vectors,
             chunks=np.array(_chunks, dtype=object))


def retrieve(query, k=3):
    """Return the top-k most similar chunks. No access-control filtering."""
    if _vectors is None or _chunks is None:
        build_index()
    q = _get_model().encode([query], normalize_embeddings=True).astype("float32")[0]
    scores = _vectors @ q
    top = np.argsort(-scores)[:k]
    return [{"source": _chunks[i]["source"],
             "visibility": _chunks[i]["visibility"],
             "score": float(scores[i]),
             "text": _chunks[i]["text"]} for i in top]


if __name__ == "__main__":
    build_index(force=True)
    print(f"indexed {len(_chunks)} chunks from {KB_DIR}")
    for q in ["what is the return policy for laptops?",
              "how much is delivery?",
              "any hidden discount tricks?"]:
        print(f"\nQ: {q}")
        for r in retrieve(q, k=2):
            print(f"  [{r['score']:.2f}] ({r['source']}/{r['visibility']}) {r['text'][:80]}...")
