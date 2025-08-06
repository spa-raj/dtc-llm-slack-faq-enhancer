import nltk
from nltk import word_tokenize, pos_tag
import re


def _ensure_nltk_data():
    """Ensure required NLTK data is downloaded."""
    required_data = [
        ('tokenizers/punkt', 'punkt'),
        ('taggers/averaged_perceptron_tagger', 'averaged_perceptron_tagger'),
        ('corpora/wordnet', 'wordnet'),
        ('corpora/omw-1.4', 'omw-1.4'),
        ('corpora/stopwords', 'stopwords')
    ]

    for path, name in required_data:
        try:
            nltk.data.find(path)
        except LookupError:
            print(f"Downloading NLTK data: {name}")
            nltk.download(name)


_ensure_nltk_data()


class QuestionDetector:
    """
    A class to detect if a given text is a question or not.
    Uses heuristics based on punctuation, POS tagging, and common question patterns.
    """

    def __init__(self):
        # Ensure required NLTK data is downloaded
        pass

    def is_question(self, text):
        """
        Determines if a text is likely a question based on multiple heuristics.
        Args:
            text: The input text (can be single or multi-sentence).
        Returns:
            True if the text is likely a question, False otherwise.
        """
        # Clean and normalize the text
        text = text.strip()

        if not text:  # Handle empty strings
            return False

        # Check 1: Question mark is a strong indicator
        if text.endswith('?'):
            return True

        # For multi-sentence texts, check if any sentence is a question
        # Use NLTK's sentence tokenizer for better accuracy
        try:
            from nltk.tokenize import sent_tokenize
            sentences = sent_tokenize(text)
        except:
            # Fallback to regex if sent_tokenize is not available
            sentences = re.split(r'[.!?]\s+', text)

        # If there are multiple sentences, check each one
        if len(sentences) > 1:
            for sentence in sentences:
                # Only consider non-empty sentences
                if sentence.strip():
                    # Check if the sentence itself contains a question mark
                    if '?' in sentence:
                        return True
                    # For multi-sentence texts, be more conservative
                    # Only check for clear question patterns
                    if self._is_clear_question(sentence.strip()):
                        return True
            return False

        # For single sentence, use detailed analysis
        return self.is_single_sentence_question(text)

    def _is_clear_question(self, sentence):
        """
        Check for clear question patterns (used for multi-sentence texts).
        More conservative than is_single_sentence_question.
        """
        if not sentence.strip():
            return False

        tokens = word_tokenize(sentence.lower())

        # Check for question marks
        if '?' in sentence:
            return True

        # Only check for sentences that clearly start with question words
        strong_question_starters = {'what', 'where', 'when', 'why', 'who', 'whom', 'whose',
                                    'which', 'how', 'is', 'are', 'was', 'were', 'do', 'does',
                                    'did', 'can', 'could', 'will', 'would', 'should'}

        if tokens and tokens[0] in strong_question_starters:
            # Additional check: should have at least 2 more words after the question starter
            if len(tokens) >= 3:
                return True

        return False

    def is_single_sentence_question(self, sentence):
        """
        Determines if a single sentence is a question using POS tags and patterns.
        """
        if not sentence.strip():  # Handle empty strings
            return False

        # Check for tag questions BEFORE tokenization (to preserve contractions)
        # This check should happen on the original text
        # Tag questions typically appear at the end after a comma
        sentence_lower = sentence.lower()

        # More comprehensive tag question patterns
        # Negative statement + positive tag
        negative_positive_tags = [
            r"\bisn't it\b", r"\baren't they\b", r"\bwasn't it\b",
            r"\bweren't they\b", r"\bdon't you\b", r"\bdoesn't it\b",
            r"\bdidn't he\b", r"\bwon't you\b", r"\bwouldn't it\b",
            r"\bcouldn't it\b", r"\bshouldn't we\b", r"\bisn't he\b",
            r"\bisn't she\b", r"\baren't you\b", r"\bwasn't he\b",
            r"\bdidn't they\b", r"\bdon't they\b", r"\bdoesn't he\b",
            r"\bdidn't she\b", r"\bisn't that\b", r"\bwasn't that\b",
            r"\bhasn't he\b", r"\bhasn't she\b", r"\bhaven't they\b",
            r"\bhadn't he\b", r"\bhadn't she\b", r"\bcan't you\b",
            r"\bcan't we\b", r"\bmustn't it\b"
        ]

        # Positive statement + negative tag (like "did he", "is it", etc.)
        positive_negative_tags = [
            r"\bdid he\b", r"\bdid she\b", r"\bdid it\b", r"\bdid they\b",
            r"\bdid you\b", r"\bdid we\b", r"\bdoes he\b", r"\bdoes she\b",
            r"\bdoes it\b", r"\bdo they\b", r"\bdo you\b", r"\bdo we\b",
            r"\bis it\b", r"\bis he\b", r"\bis she\b", r"\bare they\b",
            r"\bare you\b", r"\bare we\b", r"\bwas it\b", r"\bwas he\b",
            r"\bwas she\b", r"\bwere they\b", r"\bwere you\b", r"\bwill you\b",
            r"\bwill he\b", r"\bwill she\b", r"\bwill they\b", r"\bwould you\b",
            r"\bwould he\b", r"\bwould she\b", r"\bcould you\b", r"\bcould he\b",
            r"\bshould we\b", r"\bshould you\b", r"\bhas he\b", r"\bhas she\b",
            r"\bhave they\b", r"\bhave you\b", r"\bhad he\b", r"\bhad she\b",
            r"\bcan you\b", r"\bcan we\b", r"\bmust it\b"
        ]

        # Check both types of tag patterns
        all_patterns = negative_positive_tags + positive_negative_tags

        for pattern in all_patterns:
            # Look for the pattern, especially at the end of the sentence or after a comma
            if re.search(pattern + r"(?:\?|$)", sentence_lower) or \
                    re.search(r",\s*" + pattern + r"(?:\?|$)", sentence_lower):
                return True

        tokens = word_tokenize(sentence.lower())
        tagged_tokens = pos_tag(word_tokenize(sentence))  # Use original case for POS tagging

        # Check for question marks (in case sentence was split differently)
        if '?' in tokens:
            return True

        # Check for interrogative words at the beginning
        question_starters = {'what', 'where', 'when', 'why', 'who', 'whom', 'whose',
                             'which', 'how', 'is', 'are', 'was', 'were', 'do', 'does',
                             'did', 'can', 'could', 'will', 'would', 'should', 'shall',
                             'may', 'might', 'have', 'has', 'had', 'am'}

        if tokens and tokens[0] in question_starters:
            # Check if it's followed by a typical question pattern
            if len(tagged_tokens) >= 2:
                # Check for auxiliary verb inversion (e.g., "Is he...", "Can you...")
                first_word_lower = tagged_tokens[0][0].lower()
                aux_verbs = {'is', 'are', 'was', 'were', 'do', 'does', 'did', 'can', 'could',
                             'will', 'would', 'should', 'shall', 'may', 'might', 'have', 'has', 'had', 'am'}

                if first_word_lower in aux_verbs or tagged_tokens[0][1] in ('VBZ', 'VBP', 'VBD', 'VB', 'MD'):
                    if len(tagged_tokens) > 1 and tagged_tokens[1][1] in ('PRP', 'NNP', 'NN', 'DT', 'PRP$', 'NNS',
                                                                          'NNPS', 'EX',
                                                                          'CD'):  # Added EX for "there", CD for numbers
                        return True

                # Check for WH-questions
                if tagged_tokens[0][1] in ('WP', 'WP$', 'WRB', 'WDT'):
                    return True

        # Check for interrogative pronouns/adverbs anywhere in the sentence
        # but be more careful about their context
        wh_words = {'what', 'where', 'when', 'why', 'who', 'whom', 'whose', 'which', 'how'}

        # Check if sentence starts with a WH-word (more lenient check)
        if tokens and tokens[0].lower() in wh_words:
            return True

        # Look for WH-words that are likely part of a question
        for i, (word, tag) in enumerate(tagged_tokens):
            if word.lower() in wh_words and tag in ('WP', 'WP$', 'WRB', 'WDT'):
                # Check if it's at the beginning or after a comma (embedded question)
                if i == 0 or (i > 0 and tokens[i - 1] in (',', ';', ':')):
                    return True

        return False