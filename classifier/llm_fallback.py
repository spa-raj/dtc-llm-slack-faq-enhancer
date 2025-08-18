"""
LLM fallback module for uncertain classifications.

Uses OpenRouter API via LangChain to get second opinions on messages
that fall within the uncertainty band of the primary classifier.
"""
from typing import Tuple
import os
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

class FAQClassification(BaseModel):
    """Structure for LLM classification response."""
    is_faq: bool = Field(description="Whether the message is a course-related frequently asked question")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")
    reasoning: str = Field(description="Brief explanation of the decision")

def ask_llm_is_faq(text: str, model_name: str = "gpt-5-nano") -> Tuple[bool, float, str]:
    """
    Use LLM to classify whether a text is a course-related FAQ.
    
    This function is called when the primary classifier's confidence
    falls within the uncertainty band. It provides a second opinion
    using a more powerful but slower LLM.
    
    Args:
        text: The message text to classify
        model_name: Name of the LLM model to use (default: gpt-5-nano)
                   Options: gpt-5-nano, gpt-5-mini, gpt-5, gpt-4, claude-3-opus, gemini-pro
        
    Returns:
        Tuple of (is_faq, confidence, model_name) where:
        - is_faq: Boolean classification result
        - confidence: Confidence score (0.0 to 1.0)
        - model_name: Name of the model used
        
    Example:
        >>> ask_llm_is_faq("How do I install Docker for the DE zoomcamp?")
        (True, 0.95, "gpt-5-nano")
    """
    # Check for API key
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        # Fallback to stub implementation if no API key
        return (False, 0.0, "llm-stub")
    
    try:
        # Initialize the LLM with OpenRouter
        llm = ChatOpenAI(
            model=model_name,
            openai_api_key=api_key,
            openai_api_base="https://openrouter.ai/api/v1",
            temperature=0.1,  # Low temperature for consistent classification
        )
        
        # Create output parser
        parser = PydanticOutputParser(pydantic_object=FAQClassification)
        
        # Define the classification prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert at identifying course-related frequently asked questions (FAQs) in DataTalks.Club Slack conversations.

An FAQ is a question that:
1. Is directly related to course content, assignments, projects, or technical setup
2. Seeks specific help with course materials, tools, or technologies taught in the course
3. Could be answered with course documentation, guidance, or instructor help
4. Is likely to be asked by multiple students taking the course

NOT an FAQ:
- General programming questions unrelated to the course
- Casual conversation, greetings, or thanks
- Off-topic discussions
- Personal project questions not related to course assignments

Context: DataTalks.Club offers courses in Data Engineering, Machine Learning, MLOps, LLM, and Stock Analytics.

Classify the following message and provide your reasoning."""),
            ("user", "{text}\n\n{format_instructions}")
        ])
        
        # Create the chain
        chain = prompt | llm | parser
        
        # Run classification
        result = chain.invoke({
            "text": text,
            "format_instructions": parser.get_format_instructions()
        })
        
        return (result.is_faq, result.confidence, model_name)
        
    except Exception as e:
        print(f"LLM classification failed: {e}")
        # Return neutral response on error
        return (False, 0.5, f"{model_name}-error")