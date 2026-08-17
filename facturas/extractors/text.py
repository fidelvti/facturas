from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile


def extract_document_text(path: Path) -> str:
    suffix = path.suffix.lower()
    data = path.read_bytes()

    if suffix in {".txt", ".text"}:
        return data.decode("utf-8-sig")

    if suffix == ".pdf":
        direct_text = _extract_pdf_text_direct(path)
        if _has_enough_pdf_text(direct_text):
            return direct_text
        rendered_text = _extract_pdf_text_with_local_ocr(path)
        if rendered_text.strip():
            return rendered_text
        return data.decode("latin-1", errors="ignore")

    raise ValueError(f"Unsupported source document format: {suffix}")


def _extract_pdf_text_direct(path: Path) -> str:
    try:
        import pypdfium2 as pdfium
    except Exception:
        return ""

    pdf = pdfium.PdfDocument(str(path))
    try:
        page_texts: list[str] = []
        for page in pdf:
            text_page = page.get_textpage()
            page_texts.append(text_page.get_text_range())
        return "\n".join(page_texts)
    except Exception:
        return ""
    finally:
        pdf.close()


def _has_enough_pdf_text(text: str) -> bool:
    lowered = text.lower()
    if len(text.strip()) <= 500:
        return False
    return (
        ("datos de la factura" in lowered and "detalle de la factura" in lowered)
        or ("detall de la teva factura" in lowered and "total a pagar" in lowered)
        or ("dades de facturació" in lowered and "consum total" in lowered)
        or ("recibo de nomina" in lowered and "liquido a recibir" in lowered)
    )


def _extract_pdf_text_with_local_ocr(path: Path) -> str:
    try:
        import pypdfium2 as pdfium
    except Exception:
        return ""

    if not _has_tesseract():
        return ""

    with tempfile.TemporaryDirectory(prefix="facturas-ocr-") as tmpdir:
        tmp = Path(tmpdir)
        pdf = pdfium.PdfDocument(str(path))
        try:
            page_texts: list[str] = []
            for index, page in enumerate(pdf):
                image_path = tmp / f"page-{index + 1}.png"
                bitmap = page.render(scale=4)
                bitmap.to_pil().save(image_path)
                result = subprocess.run(
                    ["tesseract", str(image_path), "stdout", "-l", "eng", "--psm", "6"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                if result.stdout:
                    page_texts.append(result.stdout)
            return "\n".join(page_texts)
        finally:
            pdf.close()


def _has_tesseract() -> bool:
    try:
        result = subprocess.run(
            ["tesseract", "--version"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0
