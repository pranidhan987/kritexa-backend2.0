import io
from PyPDF2 import PdfReader

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    Extracts all text from a PDF file provided as bytes.
    """
    try:
        # Load PDF bytes into a stream
        pdf_stream = io.BytesIO(pdf_bytes)
        
        # Initialize reader
        reader = PdfReader(pdf_stream)
        
        # Extract text from all pages
        extracted_text = ""
        for page in reader.pages:
            text = page.extract_text()
            if text:
                extracted_text += text + "\n"
                
        return extracted_text.strip()
        
    except Exception as e:
        # Re-raise with context
        raise ValueError(f"Failed to process PDF file: {str(e)}")
