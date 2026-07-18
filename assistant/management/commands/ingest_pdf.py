"""Ingest a knowledge PDF for Joey's RAG retrieval.

    python manage.py ingest_pdf "C:\\path\\to\\fitness_book.pdf"

Extracts the text, splits it into overlapping chunks, embeds each chunk via the
OpenAI embeddings API, and stores them. Re-running replaces the whole set, so
updating the book is just a re-ingest. Only text is used — images are ignored,
which is fine because the PDF's text is selectable (no OCR needed).

Every embedding is fetched before anything is written, so a failure part-way
leaves the existing knowledge base untouched rather than half-replaced.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from assistant.models import KnowledgeChunk
from assistant.services import embed_text

# 220-word chunks with a 40-word overlap, so a sentence split across a boundary
# is still findable. Words, not tokens, to keep it simple and dependency-free.
CHUNK_WORDS = 220
OVERLAP_WORDS = 40


def _clean(text):
    """Strip NUL bytes from extracted text.

    PostgreSQL text columns cannot store 0x00, and real PDFs do contain them —
    pypdf hands them straight through from the source, so an otherwise healthy
    600-page book dies on a single bad page without this.
    """
    return text.replace("\x00", "")


def _extract_pages(path):
    from pypdf import PdfReader

    reader = PdfReader(path)
    for page_number, page in enumerate(reader.pages, start=1):
        text = _clean(page.extract_text() or "").strip()
        if text:
            yield page_number, text


def _chunk_page(text, page_number):
    """Split one page's text into overlapping word-chunks tagged with the page."""
    words = text.split()
    if not words:
        return

    start = 0
    while start < len(words):
        window = words[start : start + CHUNK_WORDS]
        chunk_text = " ".join(window).strip()
        if chunk_text:
            yield chunk_text, f"page {page_number}"
        if start + CHUNK_WORDS >= len(words):
            break
        start += CHUNK_WORDS - OVERLAP_WORDS


class Command(BaseCommand):
    help = "Ingest a PDF into Joey's knowledge base (extract, chunk, embed, store)."

    def add_arguments(self, parser):
        parser.add_argument("pdf_path", help="Path to the PDF file to ingest.")

    def handle(self, *args, **options):
        path = options["pdf_path"]

        try:
            pages = list(_extract_pages(path))
        except FileNotFoundError:
            raise CommandError(f"No file found at: {path}")
        except Exception as exc:  # pypdf read errors
            raise CommandError(f"Could not read the PDF: {exc}")

        if not pages:
            raise CommandError(
                "No selectable text found. If this is a scanned PDF it needs OCR "
                "first — this command only reads real text."
            )

        chunks = [
            (text, source)
            for page_number, page_text in pages
            for text, source in _chunk_page(page_text, page_number)
        ]

        # ASCII only in console output: Windows consoles default to cp1252, and
        # a stray arrow or ellipsis raises UnicodeEncodeError the moment stdout
        # is piped or redirected. Not worth losing an ingest over punctuation.
        self.stdout.write(
            f"Extracted {len(pages)} page(s) -> {len(chunks)} chunk(s). Embedding..."
        )

        # Embed everything BEFORE touching the database. The embeddings are the
        # slow, failure-prone part (network, rate limits), and deleting first
        # would mean any failure here left Joey with half a book.
        rows = []
        for index, (text, source) in enumerate(chunks):
            try:
                embedding = embed_text(text)
            except Exception as exc:
                raise CommandError(
                    f"Embedding failed on chunk {index} ({source}): {exc}\n"
                    "Nothing was written — the previous knowledge base is intact. "
                    "Re-run to retry."
                )

            rows.append(
                KnowledgeChunk(
                    content=text,
                    embedding=embedding,
                    source=source,
                    chunk_index=index,
                )
            )

            if len(rows) % 25 == 0:
                self.stdout.write(f"  embedded {len(rows)}/{len(chunks)}...")

        # Now the swap: fast, and all-or-nothing.
        with transaction.atomic():
            KnowledgeChunk.objects.all().delete()
            KnowledgeChunk.objects.bulk_create(rows, batch_size=200)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Joey now knows {len(rows)} chunk(s) from this PDF."
            )
        )
