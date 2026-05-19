from langchain_text_splitters import RecursiveCharacterTextSplitter
from chromadb.utils import embedding_functions
import re


class DocumentEmbedder:
    def __init__(self):
        # 1. Initialize the Embedding Model
        # This model runs locally on your CPU. It turns text into 384-dimensional vectors.
        self.embedding_fn = embedding_functions.DefaultEmbeddingFunction()

        # 2. Configure the Text Splitter
        # chunk_size: How many characters per piece?
        # chunk_overlap: How much "context" to carry over to the next piece?
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=600,
            chunk_overlap=60,
            separators=["\n\n", "\n", " ", ""]
        )

    def clean_text(self, text: str) -> str:
        """Removes messy whitespace and hidden characters from raw files."""
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def create_chunks(self, raw_text: str):
        """Processes raw text into a list of clean, AI-ready strings."""
        cleaned = self.clean_text(raw_text)
        return self.splitter.split_text(cleaned)

    def get_embedding_function(self):
        """Returns the function ChromaDB uses to vectorize text."""
        return self.embedding_fn
