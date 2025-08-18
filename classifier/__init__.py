"""
Classifier Service for FAQ Detection

A hybrid classification system that combines:
- SetFit model for primary classification
- LLM fallback for uncertain cases
- Pre-filtering for question detection
- Gold layer output to S3
"""