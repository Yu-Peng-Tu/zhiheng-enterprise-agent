import math
import re
import hashlib
from collections import Counter
import numpy as np
from sqlalchemy.orm import Session
from ..models import Chunk, Document

DIMENSIONS = 256
STOP = {"什么","怎么","如何","可以","一下","请问","公司","商品","客户","需要","时候","多久","开始","计算","的","了","吗","呢","是"}

def tokens(text: str):
    text = text.lower()
    words = re.findall(r"[a-z0-9]+", text)
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    bigrams = [chinese[i:i+2] for i in range(max(0, len(chinese)-1))]
    return [w for w in words + bigrams if w not in STOP]

def embed(text: str):
    vector = np.zeros(DIMENSIONS, dtype=np.float32)
    for token in tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "little") % DIMENSIONS
        sign = 1 if digest[4] % 2 else -1
        vector[index] += sign
    norm = np.linalg.norm(vector)
    return (vector / norm if norm else vector).tolist()

def similarity(query_embedding, chunk_embedding):
    a, b = np.array(query_embedding), np.array(chunk_embedding)
    denominator = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denominator) if denominator else 0.0

def retrieve(db: Session, question: str, limit: int = 3):
    query_embedding = embed(question)
    query_tokens = set(tokens(question))
    rows = db.query(Chunk).join(Document).filter(Chunk.active.is_(True), Document.active.is_(True), Document.status == "ready").all()
    scored = []
    for chunk in rows:
        semantic = max(0.0, similarity(query_embedding, chunk.embedding))
        chunk_tokens = set(tokens(chunk.content))
        lexical = len(query_tokens & chunk_tokens) / max(1, len(query_tokens))
        score = semantic * 0.55 + lexical * 0.45
        scored.append((score, semantic, lexical, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    results = []
    for score, semantic, lexical, chunk in scored[:limit]:
        results.append({
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "document_name": chunk.document.filename,
            "version": chunk.document.version,
            "locator": chunk.locator,
            "content": chunk.content,
            "score": round(score, 4),
            "semantic_score": round(semantic, 4),
            "lexical_score": round(lexical, 4),
        })
    return results
