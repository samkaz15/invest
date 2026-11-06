"""PDF extraction and immutable publication helpers for ADR-017 (stdlib only)."""

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path


def extract_pdf(path, ocr=False):
    """Return every page, including missing pages; never claim OCR certainty."""
    path = Path(path).resolve()
    info = subprocess.run(["pdfinfo", str(path)], check=True, capture_output=True, text=True)
    count = int(re.search(r"^Pages:\s+(\d+)", info.stdout, re.M)[1])
    with tempfile.TemporaryDirectory() as tmp:
        source = path
        if ocr:
            source = Path(tmp) / "ocr.pdf"
            subprocess.run(
                ["ocrmypdf", "--skip-text", "-l", "eng+jpn", str(path), str(source)],
                check=True,
                capture_output=True,
            )
        pages = []
        for n in range(1, count + 1):
            result = subprocess.run(
                ["pdftotext", "-layout", "-f", str(n), "-l", str(n), str(source), "-"],
                check=True,
                capture_output=True,
                text=True,
            )
            text = result.stdout.replace("\f", "").strip()
            pages.append(
                {
                    "page": n,
                    "original_text": text,
                    "extraction_status": "extracted" if text else "missing",
                    "translation_ja": "",
                    "translation_status": "pending",
                }
            )
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "page_count": count,
        "ocr_used": ocr,
        "pages": pages,
        "requires_visual_review": True,
    }


def validate(doc):
    required = {
        "id",
        "source_url",
        "title_en",
        "title_ja",
        "published_at",
        "received_at",
        "topics",
        "original_text",
        "translation_ja",
        "facts_ja",
        "inference_ja",
    }
    if required - doc.keys():
        raise ValueError("ADR-016 required fields missing")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,179}", doc["id"]):
        raise ValueError("unsafe document id")
    raw = json.dumps(doc, ensure_ascii=False)
    if re.search(
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|links-\d+\.govdelivery|"
        r"one_click_unsubscribe|urldefense\.com|gmail_id|message_id|"
        r"[?&](?:verification|destination|token)=",
        raw,
        re.I,
    ):
        raise ValueError("private metadata or personalized URL present")
    if doc.get("notification_eligible"):
        summary = doc.get("summary_ja_40", "")
        if len(summary) != 40 or any(c in summary for c in "\r\n"):
            raise ValueError("notification summary must be exactly 40 Unicode characters")
    pdf = doc.get("pdf")
    if pdf and doc.get("translation_status") == "complete":
        pages = pdf.get("pages", [])
        if not pdf.get("page_count") or len(pages) != pdf["page_count"]:
            raise ValueError("page coverage incomplete")
        if [p["page"] for p in pages] != list(range(1, pdf["page_count"] + 1)):
            raise ValueError("page order incomplete")
        if not pdf.get("visual_review_complete"):
            raise ValueError("PDF visual review required")
        for p in pages:
            if (
                not p.get("original_text")
                or not p.get("translation_ja")
                or p.get("translation_status") != "complete"
            ):
                raise ValueError("unread or untranslated page")


def immutable_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"immutable conflict: {path}")
        return
    with path.open("xb") as out:
        out.write(data)


def publish(doc, root, pdf_path=None, redistribution_allowed=False, write_record=True):
    validate(doc)
    root = Path(root)
    if pdf_path:
        if not redistribution_allowed:
            raise ValueError("PDF redistribution permission must be established")
        extracted = extract_pdf(pdf_path)
        text = "\n".join(p["original_text"] for p in extracted["pages"])
        if not text or any(p["extraction_status"] == "missing" for p in extracted["pages"]):
            raise ValueError("cannot privacy-check unread PDF pages")
        if re.search(
            r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|unsubscribe|verification=|"
            r"links-\d+\.govdelivery|urldefense\.com",
            text,
            re.I,
        ):
            raise ValueError("PDF contains prohibited addresses or personalized links")
        manifest = doc.get("pdf", {})
        if not manifest.get("privacy_review_complete"):
            raise ValueError("PDF annotations, metadata and links need privacy review")
        if manifest.get("sha256") != extracted["sha256"]:
            raise ValueError("PDF content hash mismatch")
    # Validate all artifacts before making any persistent write.
    content = (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode()
    markdown = f"# {doc['title_ja']}\n\n出典: {doc['source_url']}\n\n"
    markdown += f"翻訳状態: {doc.get('translation_status', 'unverified')}\n\n"
    markdown += doc["translation_ja"] + "\n"
    if doc.get("missing_parts"):
        markdown += (
            "\n## 未取得・未翻訳\n\n"
            + json.dumps(doc["missing_parts"], ensure_ascii=False, indent=2)
            + "\n"
        )
    paths = [
        (root / "docs/translations/us" / (doc["id"] + ".ja.md"), markdown.encode()),
    ]
    if write_record:
        paths.insert(0, (root / "data/knowledge/us" / (doc["id"] + ".json"), content))
    if pdf_path:
        paths.append(
            (
                root / "data/sources/us" / (doc["id"] + ".pdf"),
                Path(pdf_path).read_bytes(),
            )
        )
    for path, data in paths:
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f"immutable conflict: {path}")
    for path, data in paths:
        immutable_write(path, data)
    return [str(p) for p, _ in paths]


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract-pdf")
    extract.add_argument("pdf")
    extract.add_argument("--ocr", action="store_true")
    stage = sub.add_parser("publish")
    stage.add_argument("record")
    stage.add_argument("--root", default=".")
    stage.add_argument("--pdf")
    stage.add_argument("--redistribution-allowed", action="store_true")
    args = parser.parse_args()
    if args.command == "extract-pdf":
        result = extract_pdf(args.pdf, args.ocr)
    else:
        result = publish(
            json.loads(Path(args.record).read_text()),
            args.root,
            args.pdf,
            args.redistribution_allowed,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
