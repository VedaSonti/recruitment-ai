"""
file_loader.py
--------------
File loader for JDs and CVs — handles .docx and .pdf input files.
"""

import os
from docx import Document
from pypdf import PdfReader


def load_docx(path: str) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def load_pdf(path: str) -> str:
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def load_text_file(path: str) -> str:
    """Load a JD or CV file regardless of format (.docx, .pdf, .txt)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return load_docx(path)
    elif ext == ".pdf":
        return load_pdf(path)
    elif ext == ".txt":
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def load_all_files(folder_path: str) -> list[dict]:
    """Shared implementation: load every supported file in a folder."""
    results = []
    for fname in sorted(os.listdir(folder_path)):
        full_path = os.path.join(folder_path, fname)
        if not os.path.isfile(full_path):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in (".docx", ".pdf", ".txt"):
            continue
        try:
            raw_text = load_text_file(full_path)
            if not raw_text.strip():
                print(f"  [warning] {fname}: extracted empty text — likely a scanned/image-based PDF")
                continue
            results.append({"filename": fname, "raw_text": raw_text})
        except Exception as e:
            print(f"  [skipped] {fname}: {e}")
    return results


def load_all_jds(folder_path: str) -> list[dict]:
    """Load every JD file in a folder. Returns [{filename, raw_text}, ...]."""
    return load_all_files(folder_path)


def load_all_cvs(folder_path: str) -> list[dict]:
    """Load every CV file in a folder. Returns [{filename, raw_text}, ...]."""
    return load_all_files(folder_path)
