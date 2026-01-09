import os
from pypdf import PdfReader
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

DATA_DIR = "data_pdf"
VECTOR_DIR = "vectorstore"

documents = []

def chunk_text(text, size=700, overlap=100):
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks

for file in os.listdir(DATA_DIR):
    if not file.endswith(".pdf"):
        continue

    reader = PdfReader(os.path.join(DATA_DIR, file))
    full_text = ""

    for page in reader.pages:
        full_text += page.extract_text() or ""

    for chunk in chunk_text(full_text):
        documents.append(
            Document(
                page_content=chunk,
                metadata={
                    "source": file,
                    "pdf_title": file.replace(".pdf", "")
                }
            )
        )

print(f"✅ Loaded {len(documents)} chunks")

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

vectorstore = FAISS.from_documents(documents, embeddings)
vectorstore.save_local(VECTOR_DIR)

print("✅ PDF knowledge base indexed with metadata")
