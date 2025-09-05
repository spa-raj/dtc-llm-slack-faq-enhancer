#!/usr/bin/env python3
"""
Example script demonstrating hybrid search functionality.

Usage examples:
    python test_hybrid_search.py
    python test_hybrid_search.py --query "What is MLflow?" --limit 3
    python test_hybrid_search.py --query "docker issues" --course "mlops-zoomcamp"
"""

from hybrid_search import HybridSearcher, load_settings_from_config
import os
from pathlib import Path


def run_example_searches():
    """Run some example searches to demonstrate functionality."""
    
    # Load configuration (same as the indexing script)
    faq_courses_yaml = os.getenv("FAQ_COURSES_YAML")
    if not faq_courses_yaml:
        # Auto-discover config file
        for path in ["pipeline/faq_courses.yml", "../pipeline/faq_courses.yml", "faq_courses.yml"]:
            if Path(path).exists():
                faq_courses_yaml = path
                break
    
    if not faq_courses_yaml:
        print("❌ FAQ courses YAML file not found")
        print("Set FAQ_COURSES_YAML environment variable or ensure faq_courses.yml exists")
        return
    
    try:
        settings = load_settings_from_config(faq_courses_yaml)
        
        # Check if Qdrant is configured
        if not settings.get("qdrant_url"):
            print("❌ Qdrant URL not configured in settings")
            return
            
        # Initialize hybrid searcher
        searcher = HybridSearcher(
            qdrant_url=settings["qdrant_url"],
            qdrant_api_key=settings.get("qdrant_api_key", ""),
            dense_model=settings.get("embed_model", "multi-qa-mpnet-base-dot-v1"),
            sparse_model=settings.get("sparse_model") or settings.get("SPARSE_MODEL", "prithivida/Splade_PP_en_v1")
        )
        
        # Get collection name (use first course as example)
        base_collection = settings.get("qdrant_base_collection", "dtc_faq")
        
        # Try to find available collections
        import yaml
        from hybrid_search import _substitute_env_vars
        yaml_content = Path(faq_courses_yaml).read_text(encoding="utf-8")
        yaml_content = _substitute_env_vars(yaml_content)
        config = yaml.safe_load(yaml_content)
        courses = config.get("faq_courses", [])
        
        if not courses:
            print("❌ No courses configured")
            return
            
        # Example searches
        test_queries = [
            "How do I install Docker?",
            "What is MLflow?", 
            "Python environment setup",
            "Database connection issues"
        ]
        
        print("🔍 Hybrid Search Examples")
        print("=" * 50)
        
        for course in courses[:2]:  # Test first 2 courses
            collection_name = f"{base_collection}_{course['collection_suffix']}"
            course_name = course.get('name', course['id'])
            
            print(f"\n📚 Course: {course_name}")
            print(f"🗂️  Collection: {collection_name}")
            
            # Check if collection exists
            info = searcher.get_collection_info(collection_name)
            if "error" in info:
                print(f"   ⚠️  Collection not found: {info['error']}")
                continue
                
            print(f"   📊 Points: {info.get('points_count', 0)}")
            
            # Run example queries
            for query in test_queries[:2]:  # Test first 2 queries per course
                print(f"\n   🔎 Query: \"{query}\"")
                try:
                    results = searcher.search(collection_name, query, limit=2)
                    
                    if results:
                        for i, result in enumerate(results, 1):
                            payload = result["payload"]
                            print(f"      {i}. Score: {result['score']:.3f}")
                            print(f"         Section: {payload.get('section', 'N/A')}")
                            print(f"         Q: {payload.get('question', 'N/A')[:60]}...")
                    else:
                        print("      No results found")
                        
                except Exception as e:
                    print(f"      ❌ Search error: {e}")
                    
        print(f"\n✅ Example searches completed!")
        print("\n💡 Try the CLI:")
        print(f"   python hybrid_search.py -q \"your question\" --limit 5")
        print(f"   python hybrid_search.py --info  # Show collection info")
        
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    run_example_searches()