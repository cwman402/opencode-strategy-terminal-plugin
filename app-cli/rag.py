"""
rag.py — RAG knowledge base with embeddings for AI chat enhancement.

Provides:
- Document upload and chunking
- Vector embeddings using sentence-transformers (or TF-IDF fallback)
- Semantic search over knowledge base
- Integration with chat system
"""

import os
import re
import json
import hashlib
import sqlite3
import numpy as np
import streamlit as st
from datetime import datetime
from typing import Optional

try:
    from sentence_transformers import SentenceTransformer
    HAS_SBERT = True
except ImportError:
    HAS_SBERT = False

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

RAG_DIR = os.path.join(os.path.dirname(__file__), 'rag_data')
os.makedirs(RAG_DIR, exist_ok=True)

DB_PATH = os.path.join(RAG_DIR, 'knowledge.db')


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_rag_db():
    """Initialize RAG knowledge base database."""
    conn = _get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            source_type TEXT DEFAULT 'manual',
            doc_hash TEXT UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER
        );
        
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            chunk_index INTEGER,
            embedding BLOB,
            FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            context_docs TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
        CREATE INDEX IF NOT EXISTS idx_chat_user ON chat_history(user_id, created_at);
    ''')
    conn.commit()
    conn.close()


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[tuple[str, int]]:
    """Split text into overlapping chunks."""
    if not text:
        return []
    
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current = []
    current_len = 0
    
    for sent in sentences:
        sent_len = len(sent)
        if current_len + sent_len > chunk_size and current:
            chunks.append((' '.join(current), len(chunks)))
            overlap_sents = current[-(overlap // 50):] if len(current) > 1 else []
            current = overlap_sents + [sent]
            current_len = sum(len(s) for s in current)
        else:
            current.append(sent)
            current_len += sent_len
    
    if current:
        chunks.append((' '.join(current), len(chunks)))
    
    return chunks


def _get_embedding(text: str, model_name: str = 'all-MiniLM-L6-v2') -> Optional[np.ndarray]:
    """Get embeddings using sentence-transformers."""
    if not HAS_SBERT:
        return None
    
    try:
        model = SentenceTransformer(model_name)
        emb = model.encode([text], show_progress_bar=False)
        return emb[0]
    except Exception:
        return None


def _get_tfidf_features(texts: list[str]) -> tuple[TfidfVectorizer, np.ndarray]:
    """Get TF-IDF features as fallback."""
    vectorizer = TfidfVectorizer(max_features=5000, stop_words='english')
    matrix = vectorizer.fit_transform(texts)
    return vectorizer, matrix.toarray()


def _compute_hash(text: str) -> str:
    """Compute hash for deduplication."""
    return hashlib.md5(text.encode()).hexdigest()


def add_document(title: str, content: str, user_id: Optional[int] = None) -> dict:
    """Add a document to the knowledge base."""
    if not content.strip():
        return {"error": "Content cannot be empty"}
    
    doc_hash = _compute_hash(content)
    conn = _get_db()
    
    existing = conn.execute(
        'SELECT id FROM documents WHERE doc_hash = ?', (doc_hash,)
    ).fetchone()
    if existing:
        conn.close()
        return {"error": "Document already exists", "doc_id": existing['id']}
    
    chunks = _chunk_text(content)
    if not chunks:
        conn.close()
        return {"error": "Failed to chunk content"}
    
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO documents (title, content, source_type, doc_hash, user_id) VALUES (?, ?, ?, ?, ?)',
        (title, content, 'manual', doc_hash, user_id)
    )
    doc_id = cursor.lastrowid
    
    chunk_texts = [c[0] for c in chunks]
    embeddings = None
    
    if HAS_SBERT:
        try:
            model = SentenceTransformer('all-MiniLM-L6-v2')
            embeddings = model.encode(chunk_texts, show_progress_bar=False)
        except Exception:
            pass
    
    if embeddings is not None:
        for i, (text, idx) in enumerate(chunks):
            emb_bytes = embeddings[i].tobytes()
            cursor.execute(
                'INSERT INTO chunks (doc_id, chunk_text, chunk_index, embedding) VALUES (?, ?, ?, ?)',
                (doc_id, text, idx, emb_bytes)
            )
    else:
        for text, idx in chunks:
            cursor.execute(
                'INSERT INTO chunks (doc_id, chunk_text, chunk_index) VALUES (?, ?, ?)',
                (doc_id, text, idx)
            )
    
    conn.commit()
    conn.close()
    
    return {"success": True, "doc_id": doc_id, "chunks": len(chunks)}


def search_knowledge(query: str, top_k: int = 5) -> list[dict]:
    """Search the knowledge base for relevant documents."""
    if not query.strip():
        return []
    
    conn = _get_db()
    
    has_embeddings = conn.execute(
        "SELECT COUNT(*) as cnt FROM chunks WHERE embedding IS NOT NULL"
    ).fetchone()['cnt'] > 0
    
    results = []
    
    if HAS_SBERT and has_embeddings:
        try:
            emb = _get_embedding(query)
            if emb is not None:
                cursor = conn.execute(
                    'SELECT id, chunk_text, embedding FROM chunks WHERE embedding IS NOT NULL'
                )
                chunk_data = [(r['id'], r['chunk_text'], np.frombuffer(r['embedding'], dtype=np.float32)) 
                              for r in cursor.fetchall()]
                
                sims = [(doc_id, text, float(np.dot(emb, e) / (np.linalg.norm(emb) * np.linalg.norm(e) + 1e-8)))
                       for doc_id, text, e in chunk_data]
                sims.sort(key=lambda x: x[2], reverse=True)
                
                doc_ids = set()
                for doc_id, text, score in sims[:top_k * 2]:
                    if doc_id not in doc_ids:
                        doc_ids.add(doc_id)
                        doc = conn.execute('SELECT title, content FROM documents WHERE id = ?', (doc_id,)).fetchone()
                        if doc:
                            results.append({
                                "doc_id": doc_id,
                                "title": doc['title'],
                                "content": doc['content'][:300],
                                "chunk_text": text[:200],
                                "score": score
                            })
                        if len(results) >= top_k:
                            break
        except Exception:
            pass
    
    if not results:
        cursor = conn.execute('SELECT id, chunk_text FROM chunks')
        chunks = cursor.fetchall()
        if chunks:
            try:
                vectorizer, matrix = _get_tfidf_features([c['chunk_text'] for c in chunks] + [query])
                query_vec = matrix[-1]
                chunk_vecs = matrix[:-1]
                
                sims = cosine_similarity([query_vec], chunk_vecs)[0]
                top_indices = np.argsort(sims)[::-1][:top_k]
                
                doc_ids = set()
                for idx in top_indices:
                    if idx < len(chunks):
                        doc_id = chunks[idx]['id']
                        if doc_id not in doc_ids:
                            doc_ids.add(doc_id)
                            doc = conn.execute('SELECT title, content FROM documents WHERE id = ?', (doc_id,)).fetchone()
                            if doc:
                                results.append({
                                    "doc_id": doc_id,
                                    "title": doc['title'],
                                    "content": doc['content'][:300],
                                    "chunk_text": chunks[idx]['chunk_text'][:200],
                                    "score": float(sims[idx])
                                })
            except Exception:
                pass
    
    conn.close()
    return results[:top_k]


def get_all_documents(user_id: Optional[int] = None) -> list[dict]:
    """Get all documents in the knowledge base."""
    conn = _get_db()
    if user_id is not None:
        docs = conn.execute(
            'SELECT id, title, source_type, created_at FROM documents WHERE user_id IS NULL OR user_id = ? ORDER BY created_at DESC',
            (user_id,)
        ).fetchall()
    else:
        docs = conn.execute(
            'SELECT id, title, source_type, created_at FROM documents ORDER BY created_at DESC'
        ).fetchall()
    
    results = [dict(d) for d in docs]
    conn.close()
    return results


def delete_document(doc_id: int) -> dict:
    """Delete a document from the knowledge base."""
    conn = _get_db()
    conn.execute('DELETE FROM chunks WHERE doc_id = ?', (doc_id,))
    conn.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
    conn.commit()
    conn.close()
    return {"success": True}


def add_chat_message(user_id: int, role: str, content: str, context_docs: Optional[list] = None) -> dict:
    """Add a message to chat history for context."""
    conn = _get_db()
    context_json = json.dumps(context_docs) if context_docs else None
    conn.execute(
        'INSERT INTO chat_history (user_id, role, content, context_docs) VALUES (?, ?, ?, ?)',
        (user_id, role, content, context_json)
    )
    conn.commit()
    msg_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return {"success": True, "msg_id": msg_id}


def get_chat_history(user_id: int, limit: int = 20) -> list[dict]:
    """Get recent chat history for context."""
    conn = _get_db()
    msgs = conn.execute(
        '''SELECT role, content, context_docs, created_at FROM chat_history 
           WHERE user_id = ? ORDER BY created_at DESC LIMIT ?''',
        (user_id, limit)
    ).fetchall()
    
    results = []
    for m in reversed(msgs):
        results.append({
            "role": m['role'],
            "content": m['content'],
            "context_docs": json.loads(m['context_docs']) if m['context_docs'] else None,
            "created_at": m['created_at']
        })
    conn.close()
    return results


def clear_chat_history(user_id: int) -> dict:
    """Clear chat history for a user."""
    conn = _get_db()
    conn.execute('DELETE FROM chat_history WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    return {"success": True}


def rag_page():
    """RAG Knowledge Base management page."""
    st.markdown("""
    <style>
    .rag-header {
        background: linear-gradient(90deg, #1a2744 0%, #2d4a6f 100%);
        padding: 12px 20px; border-radius: 8px; margin-bottom: 16px;
        font-family: monospace; color: #ffb300; font-size: 16px;
        font-weight: bold; letter-spacing: 1px;
    }
    .rag-card {
        background: #0f1729; border: 1px solid #1e2d4a;
        border-radius: 8px; padding: 16px; margin-bottom: 12px;
    }
    .rag-badge {
        display: inline-block; font-family: monospace; font-size: 11px;
        padding: 3px 10px; border-radius: 12px; margin: 2px 4px;
        background: #1b3a1b; color: #00c853; border: 1px solid #00c853;
    }
    .rag-badge-uploaded {
        background: #1a2a3a; color: #64b5f6; border: 1px solid #64b5f6;
    }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown('<div class="rag-header">📚 RAG Knowledge Base</div>', unsafe_allow_html=True)
    
    user_id = st.session_state.get('user_id')
    
    with st.sidebar:
        st.markdown("### Upload Documents")
        
        tab_option = st.radio("Upload Method", ["Text", "File"], horizontal=True)
        
        title = ""
        content = ""
        
        if tab_option == "Text":
            title = st.text_input("Document Title", placeholder="e.g., Portfolio123 Skill Reference")
            content = st.text_area("Content", height=200, placeholder="Paste your document content here...")
        
        uploaded_file = None
        if tab_option == "File":
            uploaded_file = st.file_uploader("Upload File", type=['txt', 'md', 'csv', 'json'])
            if uploaded_file:
                title = st.text_input("Document Title", value=uploaded_file.name, placeholder="Document title")
        
        if st.button("Add to Knowledge Base", type="primary", use_container_width=True):
            if not content and not uploaded_file:
                st.error("Please provide content or upload a file")
            elif not title:
                st.error("Please provide a title")
            else:
                if uploaded_file:
                    content = uploaded_file.getvalue().decode('utf-8', errors='ignore')
                
                with st.spinner("Processing document..."):
                    result = add_document(title, content, user_id)
                    if "success" in result:
                        st.success(f"Added! {result.get('chunks', 0)} chunks created")
                    else:
                        st.error(result.get("error", "Failed to add document"))
                st.rerun()
        
        st.markdown("---")
        
        if st.button("Load Portfolio123 Skill", use_container_width=True):
            skill_path = os.path.expanduser("~/.config/opencode/skills/portfolio123/SKILL.md")
            if os.path.exists(skill_path):
                with open(skill_path, 'r') as f:
                    content = f.read()
                result = add_document("Portfolio123 Skill Reference", content, user_id)
                if "success" in result:
                    st.success("Portfolio123 skill loaded!")
                else:
                    st.warning(result.get("error", "Already exists or failed"))
            else:
                st.error("Skill file not found")
            st.rerun()
        
        if st.button("Clear Chat History", use_container_width=True):
            if user_id:
                clear_chat_history(user_id)
                st.success("Chat history cleared")
                st.rerun()
    
    search_query = st.text_input("Search Knowledge Base", placeholder="Type to search...")
    
    if search_query:
        results = search_knowledge(search_query, top_k=5)
        if results:
            st.markdown("### Search Results")
            for r in results:
                st.markdown(f"<div class='rag-card'>", unsafe_allow_html=True)
                st.markdown(f"**{r['title']}** (score: {r['score']:.3f})")
                st.markdown(r['chunk_text'] + "...")
                st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info("No results found")
    
    st.markdown("### 📁 Documents")
    
    docs = get_all_documents(user_id)
    if docs:
        for doc in docs:
            with st.container():
                st.markdown(f"<div class='rag-card'>", unsafe_allow_html=True)
                c1, c2, c3 = st.columns([3, 1, 1])
                c1.markdown(f"**{doc['title']}**")
                c2.markdown(f"<span class='rag-badge rag-badge-uploaded'>{doc['source_type']}</span>")
                
                if c3.button("🗑️", key=f"del_{doc['id']}"):
                    delete_document(doc['id'])
                    st.success("Deleted")
                    st.rerun()
                
                st.caption(f"Added: {doc['created_at']}")
                st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.info("No documents yet. Upload your first document above.")