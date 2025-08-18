"""
Pre-filtering module for question detection.

Applies heuristic rules to identify question-like messages before
passing them to the ML classifier.
"""

def is_question_like(text: str) -> bool:
    """
    Determine if a text appears to be a question using heuristics.
    
    Filters based on:
    - Presence of question marks
    - Common question starter words
    
    Args:
        text: Message text to analyze
        
    Returns:
        True if the text appears to be a question, False otherwise
        
    Examples:
        >>> is_question_like("How do I install Docker?")
        True
        >>> is_question_like("Thanks!")
        False
        >>> is_question_like("What is the difference between RDD and DataFrame?")
        True
        >>> is_question_like("?")
        True
    """
    if not text: 
        return False
        
    t = text.strip()
    
    if not t:
        return False
        
    tl = t.lower()
    
    # Check for question indicators
    question_starters = (
        "how ", "what ", "when ", "where ", "why ", "which ",
        "does ", "do ", "can ", "is ", "are ", "anyone know"
    )
    
    return ("?" in t) or tl.startswith(question_starters)