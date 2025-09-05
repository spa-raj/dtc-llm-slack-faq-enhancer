# Hybrid Search Implementation

This directory contains a modern hybrid search implementation for Qdrant using dense + sparse vectors with SPLADE embeddings.

## Architecture Overview

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  Google Docs    │───▶│  gdoc_faq_reader │───▶│    Qdrant       │
│  FAQ Content    │    │  (Indexing)      │    │   Collection    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                                         │
                                                         ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Search App    │◄───│ hybrid_search.py │◄───│  Dense + Sparse │
│   (Your RAG)    │    │  (Query)         │    │    Vectors      │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## Files

### Core Modules
- **`gdoc_faq_reader.py`** - Data ingestion and indexing to Qdrant
- **`hybrid_search.py`** - Hybrid search functionality with Query API
- **`test_hybrid_search.py`** - Example usage and testing

### Configuration
- **`../pipeline/faq_courses.yml`** - Shared configuration for both indexing and search

## Features

### ✅ Modern Qdrant Implementation
- **Named vectors** (`dense` + `sparse`)
- **SPLADE embeddings** instead of manual BM25
- **Query API** with prefetch and RRF fusion
- **Batch processing** for performance

### ✅ Configurable Models
```yaml
settings:
  embed_model: "multi-qa-mpnet-base-dot-v1"  # Dense model
  sparse_model: "prithvida/Splade_PP_en_v1"  # Sparse model
  qdrant_url: "https://your-qdrant-cluster.qdrant.io"
  qdrant_api_key: "your-api-key"
```

### ✅ Search Options
- **General search** - Across entire collection
- **Course filtering** - Search within specific course
- **Section filtering** - Search within specific section
- **Custom filters** - Extensible filtering system

## Quick Start

### 1. Index Your Data
```bash
# Index FAQ content from Google Docs
python gdoc_faq_reader.py --course-id mlops-zoomcamp
```

### 2. Search Your Data
```bash
# Basic search
python hybrid_search.py -q "How do I install Docker?" --limit 5

# Course-specific search  
python hybrid_search.py -q "MLflow setup" --course "MLOps Zoomcamp"

# Collection info
python hybrid_search.py --info
```

### 3. Test Examples
```bash
python test_hybrid_search.py
```

## API Usage

```python
from hybrid_search import HybridSearcher

# Initialize searcher
searcher = HybridSearcher(
    qdrant_url="https://your-cluster.qdrant.io",
    qdrant_api_key="your-key"
)

# Basic search
results = searcher.search(
    collection_name="dtc_faq_mlops", 
    query_text="Docker installation issues",
    limit=5
)

# Course-filtered search
results = searcher.search_by_course(
    collection_name="dtc_faq_mlops",
    query_text="MLflow setup",
    course_name="MLOps Zoomcamp",
    limit=3
)

# Process results
for result in results:
    print(f"Score: {result['score']:.3f}")
    print(f"Question: {result['payload']['question']}")
    print(f"Answer: {result['payload']['answer']}")
```

## Technical Details

### Dense + Sparse Vector Storage
Each document is stored with both vector types:
```python
{
  "dense": [0.1, 0.2, ...],      # Semantic similarity
  "sparse": {                    # Keyword matching
    "indices": [125, 9325, ...],
    "values": [0.164, 0.229, ...]
  }
}
```

### Hybrid Search Process
1. **Generate Embeddings** - Both dense and sparse for query
2. **Prefetch Candidates** - Get top candidates from each vector type
3. **Fusion** - Combine using Reciprocal Rank Fusion (RRF)
4. **Return Results** - Final ranked results

### Performance Optimizations
- **Batch embedding generation** during indexing
- **In-memory sparse vectors** (`on_disk=False`)
- **Configurable prefetch multiplier**
- **COSINE distance** for better semantic matching

## Dependencies

Required packages (already in `pyproject.toml`):
```toml
[dependency-groups.gdoc-faq]
qdrant-client = ">=1.11.0"
sentence-transformers = ">=3.0.0"  
fastembed = ">=0.3.0"              # For SPLADE
google-api-python-client = ">=2.145.0"
```

## Configuration Options

### Models
- **Dense**: Any SentenceTransformer model
- **Sparse**: SPLADE models via fastembed
  - `"prithvida/Splade_PP_en_v1"` (default)
  - `"naver/splade-cocondenser-ensembledistil"`

### Search Parameters
- `limit` - Number of final results
- `prefetch_multiplier` - Candidates multiplier (default: 2)
- `filter_conditions` - Custom Qdrant filters

## Troubleshooting

### Collection Not Found
```bash
python hybrid_search.py --info  # Check available collections
```

### No Results
- Verify collection has indexed data
- Try broader search terms
- Check filter conditions

### Performance Issues
- Reduce `prefetch_multiplier` for speed
- Use smaller embedding models
- Enable `on_disk=True` for large collections

## Integration with RAG Applications

This hybrid search can be integrated into any RAG pipeline:

```python
# Your RAG application
def answer_question(question: str) -> str:
    # 1. Search relevant context
    results = searcher.search("dtc_faq_mlops", question, limit=3)
    
    # 2. Extract context
    context = "\n".join([r["payload"]["answer"] for r in results])
    
    # 3. Generate answer with LLM
    return llm.generate(f"Context: {context}\nQuestion: {question}")
```