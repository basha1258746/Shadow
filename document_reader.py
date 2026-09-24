import os
import re
import shutil

try:
    import pymupdf
except ImportError:
    pymupdf = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    from PIL import Image
except ImportError:
    Image = None

STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "can", "this", "that",
    "these", "those", "i", "you", "he", "she", "it", "we", "they",
    "what", "which", "who", "when", "where", "why", "how"
}

RELATED_TERMS = {
    "start": [
        "begin", "began", "started", "beginning",
        "commencement", "inception"
    ],
    "end": [
        "finish", "finished", "ended", "ending",
        "conclusion", "terminate", "completed",
        "completion"
    ],
    "supervisor": [
        "supervised", "supervision", "advisor",
        "mentor", "guide", "guided", "managed",
        "overseen"
    ],
    "study": [
        "studied", "studying", "subject",
        "course", "project", "topic", "field",
        "training", "internship"
    ],
    "duration": [
        "lasted", "length", "period",
        "time span", "months", "weeks", "days"
    ],
    "location": [
        "located", "place", "site", "office",
        "workplace", "address", "factory",
        "company", "organization"
    ],
    "where": [
        "located", "place", "site", "office",
        "address", "factory", "company",
        "organization"
    ]
}


def find_tesseract_path():
    path = shutil.which("tesseract")
    
    if path:
        return path
    
    default_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    
    if os.path.exists(default_path):
        return default_path
    
    return None


def setup_ocr():
    if pytesseract is None:
        print("[Shadow OCR] pytesseract is not installed.")
        return False
    
    if Image is None:
        print("[Shadow OCR] Pillow is not installed.")
        return False
    
    tesseract_path = find_tesseract_path()
    
    if not tesseract_path:
        print("[Shadow OCR] Tesseract executable was not found.")
        return False
    
    pytesseract.pytesseract.tesseract_cmd = tesseract_path
    
    print(f"[Shadow OCR] Tesseract: {tesseract_path}")
    
    return True


def ocr_image_safe(image):
    # OCR via the tesseract CLI with raw UTF-8
    # byte capture. Immune to the Windows ANSI
    # decode crash that pytesseract's text mode
    # suffers on non-ASCII screen content
    # (smart quotes etc).

    import subprocess
    import tempfile

    tesseract_path = find_tesseract_path()

    if pytesseract is None or Image is None:
        return ""

    if not tesseract_path:
        return ""

    tmp = tempfile.NamedTemporaryFile(
        suffix=".png", delete=False
    )

    tmp_path = tmp.name
    tmp.close()

    try:
        image.save(tmp_path)

        result = subprocess.run(
            [
                tesseract_path,
                tmp_path,
                "stdout",
                "-l", "eng",
            ],
            capture_output=True,
            timeout=60,
        )

        return result.stdout.decode(
            "utf-8", errors="replace"
        ).strip()

    except Exception as error:
        print(f"[Shadow OCR] Safe OCR failed: {error}")
        return ""

    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def clean_search_words(text):
    text = text.lower()
    
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    
    words = text.split()
    
    return [
        word
        for word in words
        if word and word not in STOP_WORDS
    ]


def expand_search_words(words):
    expanded = set(words)
    
    for word in words:
        if word in RELATED_TERMS:
            expanded.update(RELATED_TERMS[word])
    
    return list(expanded)


def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read()
    except Exception as error:
        print(f"Error reading text file: {error}")
        return None


def perform_ocr(page, page_number):
    try:
        print(
            f"[Shadow OCR] Scanned page detected. "
            f"Running OCR on page {page_number}..."
        )
        
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(2, 2),
            alpha=False
        )
        
        image = Image.frombytes(
            "RGB",
            [pixmap.width, pixmap.height],
            pixmap.samples
        )
        
        text = pytesseract.image_to_string(
            image,
            lang="eng"
        )
        
        text = text.strip()
        
        print(
            f"[Shadow OCR] Page {page_number}: "
            f"{len(text)} characters extracted."
        )
        
        return text
    except Exception as error:
        print(
            f"[Shadow OCR] Error on page "
            f"{page_number}: {error}"
        )
        return ""


def read_pdf_file(path):
    if pymupdf is None:
        print(
            "Error: PyMuPDF is not installed."
        )
        return None
    
    try:
        document = pymupdf.open(path)
    except Exception as error:
        print(f"Error opening PDF: {error}")
        return None
    
    total_pages = len(document)
    
    print(
        f"[Shadow PDF] PDF opened successfully. "
        f"Pages: {total_pages}"
    )
    
    ocr_ready = setup_ocr()
    
    extracted_pages = []
    
    for page_index in range(total_pages):
        page_number = page_index + 1
        
        print(
            f"[Shadow PDF] Processing page "
            f"{page_number}/{total_pages}..."
        )
        
        page = document[page_index]
        
        try:
            normal_text = page.get_text("text").strip()
        except Exception:
            normal_text = ""
        
        if len(normal_text) >= 100:
            print(
                f"[Shadow PDF] Normal text found on "
                f"page {page_number}: "
                f"{len(normal_text)} characters."
            )
            
            extracted_pages.append(
                f"[PAGE {page_number}]\n{normal_text}"
            )
        else:
            if ocr_ready:
                ocr_text = perform_ocr(
                    page,
                    page_number
                )
                
                if ocr_text:
                    extracted_pages.append(
                        f"[PAGE {page_number}]\n{ocr_text}"
                    )
                elif normal_text:
                    extracted_pages.append(
                        f"[PAGE {page_number}]\n{normal_text}"
                    )
            elif normal_text:
                extracted_pages.append(
                    f"[PAGE {page_number}]\n{normal_text}"
                )
    
    document.close()
    
    if not extracted_pages:
        print(
            "[Shadow PDF] No readable text was found."
        )
        return None
    
    final_text = "\n\n".join(extracted_pages)
    
    print(
        f"[Shadow PDF] Total extracted characters: "
        f"{len(final_text)}"
    )
    
    return final_text


def read_document(path):
    path = path.strip().strip('"')
    
    if not os.path.exists(path):
        print(f"Error: File not found: {path}")
        return None
    
    extension = os.path.splitext(path)[1].lower()
    
    if extension == ".pdf":
        return read_pdf_file(path)
    
    if extension == ".txt":
        return read_text_file(path)
    
    if extension == ".md":
        return read_text_file(path)
    
    print(
        f"Error: Unsupported file type: {extension}"
    )
    
    return None


def split_into_chunks(text, chunk_size=3000):
    if not text:
        return []
    
    chunks = []
    
    start = 0
    
    while start < len(text):
        end = min(
            start + chunk_size,
            len(text)
        )
        
        if end < len(text):
            break_position = text.rfind(
                "\n",
                start,
                end
            )
            
            if break_position > start + (
                chunk_size // 2
            ):
                end = break_position
        
        chunk = text[start:end].strip()
        
        if chunk:
            chunks.append(chunk)
        
        start = end
        
        while (
            start < len(text)
            and text[start] in " \n\r"
        ):
            start += 1
    
    return chunks


def search_chunks(chunks, query, max_results=3):
    if not chunks or not query:
        return []
    
    query_words = clean_search_words(query)
    
    if not query_words:
        return []
    
    expanded_words = expand_search_words(
        query_words
    )
    
    scored_chunks = []
    
    for index, chunk in enumerate(chunks):
        chunk_lower = chunk.lower()
        
        score = 0
        
        for word in query_words:
            score += chunk_lower.count(
                word.lower()
            ) * 3
        
        for word in expanded_words:
            if word.lower() in chunk_lower:
                score += chunk_lower.count(
                    word.lower()
                )
        
        if score > 0:
            scored_chunks.append(
                (score, index, chunk)
            )
    
    scored_chunks.sort(
        key=lambda item: item[0],
        reverse=True
    )
    
    return [
        item[2]
        for item in scored_chunks[:max_results]
    ]


if __name__ == "__main__":
    print("Shadow DOCUMENT SEARCH TEST")
    
    path = input(
        "Enter PDF/TXT/MD file path: "
    ).strip()
    
    text = read_document(path)
    
    if text:
        chunks = split_into_chunks(text)
        
        print()
        print(
            "Document chunks:",
            len(chunks)
        )
        
        question = input(
            "Enter a search question: "
        ).strip()
        
        results = search_chunks(
            chunks,
            question
        )
        
        print()
        print("SEARCH RESULTS:")
        print()
        
        if results:
            for index, result in enumerate(
                results,
                1
            ):
                print(
                    f"--- Result {index} ---"
                )
                print(result)
                print()
        else:
            print(
                "No matching document sections found."
            )
    else:
        print(
            "No readable text was extracted."
        )