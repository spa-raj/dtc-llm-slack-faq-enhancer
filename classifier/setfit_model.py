"""
SetFit model wrapper for FAQ classification.

Provides a wrapper around the SetFit model for consistent interface
and probability extraction.
"""
from setfit import SetFitModel
import numpy as np

class SetFitWrapper:
    """
    Wrapper for SetFit model to provide consistent interface.
    
    Attributes:
        model: The loaded SetFit model
        name: Name identifier for this classifier
        version: Version identifier for this classifier
    """
    
    def __init__(self, path_or_hub="sentence-transformers/all-MiniLM-L6-v2"):
        """
        Initialize the SetFit model wrapper.
        
        Args:
            path_or_hub: Path to local model or HuggingFace hub model name
                        Default uses a lightweight but effective model
        """
        self.model = SetFitModel.from_pretrained(path_or_hub)
        self.name = "setfit-miniLM"
        self.version = "v1"
        
    def predict_proba(self, texts):
        """
        Get probability scores for texts being FAQs.
        
        Args:
            texts: List of text strings to classify
            
        Returns:
            NumPy array of probabilities (0.0 to 1.0) for each text being an FAQ
            
        Note:
            Returns the probability of the positive class (FAQ=True)
        """
        # Get probabilities for both classes and extract positive class probability
        return np.asarray(self.model.predict_proba(texts)[:, 1], dtype=float)