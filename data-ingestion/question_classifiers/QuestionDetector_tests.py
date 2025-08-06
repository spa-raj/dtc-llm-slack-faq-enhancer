import pytest
from QuestionDetector import QuestionDetector

class TestQuestionDetector:
    @pytest.fixture(scope="class")
    def detector(self):
        """Initialize the QuestionDetector for each test."""
        return QuestionDetector()

    def test_question_marks(self, detector):
        """Test sentences ending with question marks."""
        assert detector.is_question("What is your name?") == True
        assert detector.is_question("This ends with a question mark?") == True

    def test_wh_questions(self, detector):
        """Test various WH-questions."""
        assert detector.is_question("What time is it") == True
        assert detector.is_question("Where can I find more information") == True
        assert detector.is_question("When does the movie start") == True
        assert detector.is_question("Why did the chicken cross the road") == True
        assert detector.is_question("Who is the president") == True
        assert detector.is_question("Which option should I choose") == True
        assert detector.is_question("How does this work") == True

    def test_auxiliary_inversions(self, detector):
        """Test questions with auxiliary verb inversions."""
        assert detector.is_question("Is this working correctly") == True
        assert detector.is_question("Are you sure about this") == True
        assert detector.is_question("Can you help me") == True
        assert detector.is_question("Could you pass the salt") == True
        assert detector.is_question("Will they arrive on time") == True
        assert detector.is_question("Should I proceed") == True

    def test_tag_questions(self, detector):
        """Test tag questions."""
        assert detector.is_question("The weather is nice today, isn't it") == True
        assert detector.is_question("You're coming to the party, aren't you") == True
        assert detector.is_question("He didn't say that, did he") == True

    def test_statements(self, detector):
        """Test statements that should not be classified as questions."""
        assert detector.is_question("The cat is sleeping.") == False
        assert detector.is_question("I am going to the store.") == False
        assert detector.is_question("Python is a programming language.") == False

    def test_imperatives(self, detector):
        """Test imperative sentences that are not questions."""
        assert detector.is_question("Please help me with this.") == False
        assert detector.is_question("Tell me about Python.") == False
        assert detector.is_question("Give me the report by tomorrow.") == False

    def test_multi_sentence(self, detector):
        """Test texts with multiple sentences."""
        assert detector.is_question("I'm not sure. What do you think?") == True
        assert detector.is_question("Hello. Can you help me? Thanks.") == True
        assert detector.is_question("I'm good. Thanks for asking. Have a nice day.") == False

    def test_long_text(self, detector):
        """Test longer paragraphs."""
        long_text = """Hello everyone,
 I'd like to share this documentation page from DLT Hub that I found particularly insightful.
 It outlines all the available configuration options when using DLT to send data to Qdrant.
 The documentation covers aspects such as collection setup, embedding parameters, and advanced
 settings — very helpful for anyone building or optimizing a data pipeline involving Qdrant as a destination."""
        assert detector.is_question(long_text) == False

        # Long text with a question
        long_text_with_question = """Hello everyone,
 I'd like to share this documentation page from DLT Hub. What do you think about it?
 It outlines all the available configuration options when using DLT to send data to Qdrant."""
        assert detector.is_question(long_text_with_question) == True

    def test_edge_cases(self, detector):
        """Test edge cases."""
        assert detector.is_question("") == False  # Empty string
        assert detector.is_question("   ") == False  # Whitespace only
        assert detector.is_question("?") == True  # Just a question mark