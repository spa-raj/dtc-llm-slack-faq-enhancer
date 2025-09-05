import os, json, hashlib, re, argparse
from typing import List, Dict
from pathlib import Path

from googleapiclient.discovery import build
from google.auth import default as google_auth_default
from google.oauth2 import service_account
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http import models
from fastembed import SparseTextEmbedding
import yaml

SCOPES = [
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

def _get_credentials():
    # 1) CI via OIDC (Application Default Credentials)
    try:
        creds, _ = google_auth_default(scopes=SCOPES)
        return creds
    except Exception:
        pass
    # 2) Local dev with SERVICE_ACCOUNT_JSON
    sa_json = os.getenv("SERVICE_ACCOUNT_JSON", "")
    if sa_json and os.path.exists(sa_json):
        return service_account.Credentials.from_service_account_file(sa_json, scopes=SCOPES)
    raise RuntimeError("No Google credentials available. Configure OIDC in CI or set SERVICE_ACCOUNT_JSON for local dev.")

def _flatten_paragraph_text(struct_el) -> str:
    if "paragraph" in struct_el:
        parts = []
        for e in struct_el["paragraph"].get("elements", []):
            text = e.get("textRun", {}).get("content", "")
            if text:
                parts.append(text)
        return "".join(parts).strip()
    return ""

def read_gdoc_faq(document_id: str) -> List[Dict]:
    creds = _get_credentials()
    docs = build("docs", "v1", credentials=creds, cache_discovery=False)
    doc = docs.documents().get(documentId=document_id).execute()

    chunks, section, current = [], None, None

    for el in doc.get("body", {}).get("content", []):
        if "paragraph" not in el:
            continue

        style = el["paragraph"].get("paragraphStyle", {}).get("namedStyleType", "")
        text = _flatten_paragraph_text(el)
        if not text:
            continue

        if style == "HEADING_1":
            section = text
        elif style == "HEADING_2":
            if current and current.get("answer", "").strip():
                chunks.append(current)
            current = {"section": section or "", "question": text, "answer": ""}
        else:
            if current is not None:
                current["answer"] += ("" if not current["answer"] else "\n") + text

    if current and current.get("answer", "").strip():
        chunks.append(current)

    return chunks

def index_to_qdrant(chunks: List[Dict], qdrant_url: str, qdrant_api_key: str, collection_name: str, embed_model: str = "multi-qa-mpnet-base-dot-v1", sparse_model: str = "prithvida/Splade_PP_en_v1"):
    # Initialize Qdrant client
    client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    
    # Initialize embedding models
    dense_model = SentenceTransformer(embed_model)
    sparse_embedding_model = SparseTextEmbedding(model_name=sparse_model)
    
    # Create collection if it doesn't exist
    try:
        client.get_collection(collection_name)
    except Exception:
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "dense": models.VectorParams(
                    size=dense_model.get_sentence_embedding_dimension(),
                    distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(
                    index=models.SparseIndexParams(
                        on_disk=False,  # Keep in memory for better performance
                    )
                )
            }
        )
    
    # Prepare texts for batch embedding
    texts_to_embed = []
    for chunk in chunks:
        text_to_embed = f"{chunk['question']}\n{chunk['answer']}"
        texts_to_embed.append(text_to_embed)
    
    # Generate embeddings in batch
    print(f"Generating dense embeddings for {len(texts_to_embed)} texts...")
    dense_embeddings = dense_model.encode(texts_to_embed).tolist()
    
    print(f"Generating sparse embeddings for {len(texts_to_embed)} texts...")
    sparse_embeddings = list(sparse_embedding_model.embed(texts_to_embed))
    
    # Prepare points for indexing
    points = []
    for i, chunk in enumerate(chunks):
        text_to_embed = texts_to_embed[i]
        dense_embedding = dense_embeddings[i]
        sparse_embedding = sparse_embeddings[i]
        
        # Create stable ID based on content hash and course
        content_hash = hashlib.sha256(text_to_embed.encode()).hexdigest()
        course_id = chunk.get("course_id", "unknown")
        point_id = f"{course_id}_{content_hash[:8]}"
        
        # Create hybrid point with both dense and sparse vectors
        point = models.PointStruct(
            id=point_id,
            vector={
                "dense": dense_embedding,
                "sparse": models.SparseVector(
                    indices=sparse_embedding.indices.tolist(),
                    values=sparse_embedding.values.tolist()
                )
            },
            payload={
                "section": chunk["section"],
                "question": chunk["question"], 
                "answer": chunk["answer"],
                "text": text_to_embed,
                "doc_id": os.environ.get("GOOGLE_DOC_ID", ""),
                "course": os.environ.get("COURSE_NAME", "")
            }
        )
        points.append(point)
    
    # Upsert points to Qdrant
    client.upsert(collection_name=collection_name, points=points)
    print(f"Indexed {len(points)} points to Qdrant collection '{collection_name}'")

def _substitute_env_vars(text: str) -> str:
    """Replace ${VAR_NAME} and ${VAR_NAME:-default} with environment variable values."""
    def replacer(match):
        var_expr = match.group(1)
        if ":-" in var_expr:
            var_name, default_val = var_expr.split(":-", 1)
            return os.getenv(var_name, default_val)
        else:
            return os.getenv(var_expr, "")
    
    return re.sub(r"\$\{([^}]+)\}", replacer, text)

def load_faq_courses_config(faq_courses_yaml: str) -> Dict:
    """Load and parse the FAQ courses configuration file."""
    yaml_content = Path(faq_courses_yaml).read_text(encoding="utf-8")
    yaml_content = _substitute_env_vars(yaml_content)
    return yaml.safe_load(yaml_content)

def process_single_course(course_config: Dict, settings: Dict) -> int:
    """Process a single course FAQ document."""
    course_id = course_config["id"]
    course_name = course_config["name"]
    doc_id = course_config["google_doc_id"]
    collection_suffix = course_config["collection_suffix"]
    
    print(f"Processing {course_name} (ID: {course_id})...")
    
    if not doc_id or doc_id.startswith("${"):
        print(f"  Skipping {course_id}: No valid Google Doc ID configured")
        return 0
    
    try:
        chunks = read_gdoc_faq(doc_id)
        if not chunks:
            print(f"  Warning: No FAQ chunks found for {course_id}")
            return 0
            
        # Add course metadata to chunks
        for chunk in chunks:
            chunk["course_id"] = course_id
            chunk["course_name"] = course_name
            chunk["doc_id"] = doc_id
        
        # Check if we should index to Qdrant
        qdrant_url = settings.get("qdrant_url")
        if qdrant_url:
            qdrant_api_key = settings.get("qdrant_api_key", "")
            base_collection = settings.get("qdrant_base_collection", "dtc_faq")
            collection_name = f"{base_collection}_{collection_suffix}"
            embed_model = settings.get("embed_model", "multi-qa-mpnet-base-dot-v1")
            sparse_model = settings.get("sparse_model", "prithvida/Splade_PP_en_v1")
            
            index_to_qdrant(chunks, qdrant_url, qdrant_api_key, collection_name, embed_model, sparse_model)
        else:
            # Fallback to JSONL output
            out_dir = os.getenv("OUTPUT_DIR", "artifacts")
            os.makedirs(out_dir, exist_ok=True)
            out_file = f"{out_dir}/faq_{collection_suffix}.jsonl"
            with open(out_file, "w", encoding="utf-8") as f:
                for c in chunks:
                    f.write(json.dumps(c, ensure_ascii=False) + "\n")
            print(f"  Extracted {len(chunks)} chunks -> {out_file}")
            
        return len(chunks)
        
    except Exception as e:
        print(f"  Error processing {course_id}: {e}")
        return 0

def main():
    parser = argparse.ArgumentParser(description="Read FAQ from Google Docs and index to Qdrant")
    parser.add_argument("--faq-courses-yaml", help="Path to FAQ courses YAML (overrides FAQ_COURSES_YAML)")
    parser.add_argument("--course-id", help="Process only specific course ID (optional)")
    args = parser.parse_args()
    
    # Determine FAQ courses config file
    faq_courses_yaml = args.faq_courses_yaml or os.getenv("FAQ_COURSES_YAML")
    if not faq_courses_yaml:
        # Auto-discover in common locations
        for path in ["pipeline/faq_courses.yml", "../pipeline/faq_courses.yml", "faq_courses.yml"]:
            if Path(path).exists():
                faq_courses_yaml = path
                break
        if not faq_courses_yaml:
            raise RuntimeError("FAQ courses YAML file not found. Set FAQ_COURSES_YAML or use --faq-courses-yaml")
    
    if not Path(faq_courses_yaml).exists():
        raise RuntimeError(f"FAQ courses YAML file not found: {faq_courses_yaml}")
    
    print(f"Loading FAQ courses config: {faq_courses_yaml}")
    config = load_faq_courses_config(faq_courses_yaml)
    
    courses = config.get("faq_courses", [])
    settings = config.get("settings", {})
    
    if not courses:
        print("No courses configured in FAQ courses YAML")
        return
    
    # Filter by course ID if specified
    if args.course_id:
        courses = [c for c in courses if c["id"] == args.course_id]
        if not courses:
            print(f"Course ID '{args.course_id}' not found in configuration")
            return
    
    print(f"Processing {len(courses)} course(s)...")
    
    total_chunks = 0
    for course in courses:
        chunks_count = process_single_course(course, settings)
        total_chunks += chunks_count
    
    print(f"\nCompleted: {total_chunks} total chunks processed across {len(courses)} course(s)")

if __name__ == "__main__":
    main()