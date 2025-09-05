import os
import argparse
from typing import List, Dict, Optional, Tuple
from pathlib import Path

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http import models
from fastembed import SparseTextEmbedding
import yaml


class HybridSearcher:
    """
    Hybrid search functionality for Qdrant collections using dense + sparse vectors.
    
    Uses Qdrant's Query API with prefetch and Reciprocal Rank Fusion (RRF) 
    for combining dense semantic search with sparse keyword matching.
    """
    
    def __init__(
        self, 
        qdrant_url: str, 
        qdrant_api_key: str, 
        dense_model: str = "multi-qa-mpnet-base-dot-v1",
        sparse_model: str = "prithivida/Splade_PP_en_v1"
    ):
        """
        Initialize the hybrid searcher.
        
        Args:
            qdrant_url: Qdrant server URL
            qdrant_api_key: Qdrant API key
            dense_model: Dense embedding model name
            sparse_model: Sparse embedding model name
        """
        self.client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        self.dense_model = SentenceTransformer(dense_model)
        self.sparse_model = SparseTextEmbedding(model_name=sparse_model)
        
    def search(
        self,
        collection_name: str,
        query_text: str,
        limit: int = 10,
        prefetch_multiplier: int = 2,
        filter_conditions: Optional[List[models.FieldCondition]] = None
    ) -> List[Dict]:
        """
        Perform hybrid search using dense + sparse vectors with RRF fusion.
        
        Args:
            collection_name: Name of the Qdrant collection
            query_text: Search query text
            limit: Number of final results to return
            prefetch_multiplier: Multiplier for prefetch candidates (prefetch_limit = limit * multiplier)
            filter_conditions: Optional filter conditions for the search
            
        Returns:
            List of search results with scores and payloads
        """
        # Generate query embeddings
        query_dense = self.dense_model.encode(query_text).tolist()
        query_sparse_list = list(self.sparse_model.embed([query_text]))
        query_sparse = query_sparse_list[0]
        
        # Prepare prefetch queries
        prefetch_limit = limit * prefetch_multiplier
        prefetch_queries = [
            # Dense vector prefetch
            models.Prefetch(
                query=query_dense,
                using="dense",
                limit=prefetch_limit,
                filter=models.Filter(must=filter_conditions) if filter_conditions else None
            ),
            # Sparse vector prefetch  
            models.Prefetch(
                query=models.SparseVector(
                    indices=query_sparse.indices.tolist(),
                    values=query_sparse.values.tolist()
                ),
                using="sparse",
                limit=prefetch_limit,
                filter=models.Filter(must=filter_conditions) if filter_conditions else None
            )
        ]
        
        # Perform hybrid search using Query API
        results = self.client.query_points(
            collection_name=collection_name,
            prefetch=prefetch_queries,
            query=models.FusionQuery(
                fusion=models.Fusion.RRF  # Reciprocal Rank Fusion
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False
        )
        
        # Convert results to dictionary format
        search_results = []
        for result in results.points:
            search_results.append({
                "id": result.id,
                "score": result.score,
                "payload": result.payload
            })
        
        return search_results
    
    def search_by_course(
        self,
        collection_name: str,
        query_text: str,
        course_name: str,
        limit: int = 10
    ) -> List[Dict]:
        """
        Search within a specific course.
        
        Args:
            collection_name: Name of the Qdrant collection
            query_text: Search query text
            course_name: Course name to filter by
            limit: Number of results to return
            
        Returns:
            List of search results filtered by course
        """
        filter_conditions = [
            models.FieldCondition(
                key="course",
                match=models.MatchValue(value=course_name)
            )
        ]
        
        return self.search(
            collection_name=collection_name,
            query_text=query_text,
            limit=limit,
            filter_conditions=filter_conditions
        )
    
    def search_by_section(
        self,
        collection_name: str,
        query_text: str,
        section: str,
        limit: int = 10
    ) -> List[Dict]:
        """
        Search within a specific section.
        
        Args:
            collection_name: Name of the Qdrant collection
            query_text: Search query text  
            section: Section name to filter by
            limit: Number of results to return
            
        Returns:
            List of search results filtered by section
        """
        filter_conditions = [
            models.FieldCondition(
                key="section",
                match=models.MatchValue(value=section)
            )
        ]
        
        return self.search(
            collection_name=collection_name,
            query_text=query_text,
            limit=limit,
            filter_conditions=filter_conditions
        )
    
    def get_collection_info(self, collection_name: str) -> Dict:
        """
        Get information about a collection.
        
        Args:
            collection_name: Name of the collection
            
        Returns:
            Dictionary with collection information
        """
        try:
            collection_info = self.client.get_collection(collection_name)
            return {
                "status": collection_info.status,
                "points_count": collection_info.points_count,
                "vectors_config": collection_info.config.params.vectors,
                "sparse_vectors_config": collection_info.config.params.sparse_vectors
            }
        except Exception as e:
            return {"error": str(e)}


def _substitute_env_vars(text: str) -> str:
    """Replace ${VAR_NAME} and ${VAR_NAME:-default} with environment variable values."""
    import re
    def replacer(match):
        var_expr = match.group(1)
        if ":-" in var_expr:
            var_name, default_val = var_expr.split(":-", 1)
            return os.getenv(var_name, default_val)
        else:
            return os.getenv(var_expr, "")
    
    return re.sub(r"\$\{([^}]+)\}", replacer, text)


def load_settings_from_config(faq_courses_yaml: str) -> Dict:
    """Load settings from FAQ courses configuration file."""
    yaml_content = Path(faq_courses_yaml).read_text(encoding="utf-8")
    yaml_content = _substitute_env_vars(yaml_content)
    config = yaml.safe_load(yaml_content)
    return config.get("settings", {})


def main():
    """
    Command-line interface for hybrid search testing.
    """
    parser = argparse.ArgumentParser(description="Test hybrid search functionality")
    parser.add_argument("--query", "-q", required=True, help="Search query text")
    parser.add_argument("--collection", "-c", help="Collection name (overrides config)")
    parser.add_argument("--course", help="Filter by specific course name")
    parser.add_argument("--section", help="Filter by specific section")
    parser.add_argument("--limit", "-l", type=int, default=5, help="Number of results (default: 5)")
    parser.add_argument("--faq-courses-yaml", help="Path to FAQ courses YAML config")
    parser.add_argument("--info", action="store_true", help="Show collection info")
    
    args = parser.parse_args()
    
    # Load configuration
    faq_courses_yaml = args.faq_courses_yaml or os.getenv("FAQ_COURSES_YAML")
    if not faq_courses_yaml:
        # Auto-discover config file
        for path in ["pipeline/faq_courses.yml", "../pipeline/faq_courses.yml", "faq_courses.yml"]:
            if Path(path).exists():
                faq_courses_yaml = path
                break
        if not faq_courses_yaml:
            raise RuntimeError("FAQ courses YAML file not found. Set FAQ_COURSES_YAML or use --faq-courses-yaml")
    
    settings = load_settings_from_config(faq_courses_yaml)
    
    # Initialize searcher
    qdrant_url = settings.get("qdrant_url")
    if not qdrant_url:
        raise RuntimeError("qdrant_url not configured in settings")
        
    qdrant_api_key = settings.get("qdrant_api_key", "")
    dense_model = settings.get("embed_model", "multi-qa-mpnet-base-dot-v1") 
    sparse_model = settings.get("sparse_model") or settings.get("SPARSE_MODEL", "prithivida/Splade_PP_en_v1")
    
    searcher = HybridSearcher(
        qdrant_url=qdrant_url,
        qdrant_api_key=qdrant_api_key,
        dense_model=dense_model,
        sparse_model=sparse_model
    )
    
    # Determine collection name
    collection_name = args.collection
    if not collection_name:
        base_collection = settings.get("qdrant_base_collection", "dtc_faq")
        # Use first available collection suffix as default
        yaml_content = Path(faq_courses_yaml).read_text(encoding="utf-8")
        yaml_content = _substitute_env_vars(yaml_content)
        config = yaml.safe_load(yaml_content)
        courses = config.get("faq_courses", [])
        if courses:
            collection_name = f"{base_collection}_{courses[0]['collection_suffix']}"
        else:
            collection_name = base_collection
    
    if args.info:
        # Show collection information
        info = searcher.get_collection_info(collection_name)
        print(f"\nCollection: {collection_name}")
        print("=" * 50)
        if "error" in info:
            print(f"Error: {info['error']}")
        else:
            print(f"Status: {info['status']}")
            print(f"Points: {info['points_count']}")
            print(f"Dense vectors: {info['vectors_config']}")
            print(f"Sparse vectors: {info['sparse_vectors_config']}")
        return
    
    # Perform search
    print(f"Searching in collection: {collection_name}")
    print(f"Query: {args.query}")
    print("=" * 50)
    
    try:
        if args.course:
            results = searcher.search_by_course(collection_name, args.query, args.course, args.limit)
            print(f"Filtered by course: {args.course}")
        elif args.section:
            results = searcher.search_by_section(collection_name, args.query, args.section, args.limit)
            print(f"Filtered by section: {args.section}")
        else:
            results = searcher.search(collection_name, args.query, args.limit)
            
        if not results:
            print("No results found.")
            return
            
        for i, result in enumerate(results, 1):
            payload = result["payload"]
            print(f"\n{i}. Score: {result['score']:.4f}")
            print(f"   Course: {payload.get('course', 'N/A')}")
            print(f"   Section: {payload.get('section', 'N/A')}")
            print(f"   Question: {payload.get('question', 'N/A')}")
            print(f"   Answer: {payload.get('answer', 'N/A')[:200]}...")
            
    except Exception as e:
        print(f"Search error: {e}")


if __name__ == "__main__":
    main()