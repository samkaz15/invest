import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "ops" / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


artifacts = module("us_mail_artifacts")
watcher = module("watch_us_mail_mac")


def record():
    return {
        "id": "test-public",
        "source_url": "https://home.treasury.gov/example",
        "title_en": "Test",
        "title_ja": "テスト",
        "published_at": None,
        "received_at": "2026-11-06T00:00:00+09:00",
        "topics": ["treasuries"],
        "original_text": "Official example.",
        "translation_ja": "公式の例。",
        "facts_ja": [],
        "inference_ja": [],
    }


class ArtifactsTest(unittest.TestCase):
    def test_immutable_and_privacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = record()
            artifacts.publish(doc, tmp)
            artifacts.publish(doc, tmp)
            doc["translation_ja"] = "changed"
            with self.assertRaises(ValueError):
                artifacts.publish(doc, tmp)
            doc = record()
            doc["original_text"] = "recipient@example.com"
            with self.assertRaises(ValueError):
                artifacts.publish(doc, tmp)

    @unittest.skipUnless(
        shutil.which("pdfinfo") and shutil.which("pdftotext"), "Poppler required"
    )
    def test_real_pdf_all_pages_and_translation_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "two.pdf"
            objects = [
                b"<< /Type /Catalog /Pages 2 0 R >>",
                b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
            ]
            for content_id in (6, 7):
                objects.append(
                    (
                        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                        "/Resources << /Font << /F1 5 0 R >> >> "
                        f"/Contents {content_id} 0 R >>"
                    ).encode()
                )
            objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
            for n in (1, 2):
                stream = f"BT /F1 12 Tf 40 700 Td (Public Treasury example page {n}) Tj ET".encode()
                objects.append(
                    f"<< /Length {len(stream)} >>\nstream\n".encode()
                    + stream
                    + b"\nendstream"
                )
            data, offsets = b"%PDF-1.4\n", [0]
            for n, obj in enumerate(objects, 1):
                offsets.append(len(data))
                data += f"{n} 0 obj\n".encode() + obj + b"\nendobj\n"
            start = len(data)
            data += b"xref\n0 8\n0000000000 65535 f \n"
            data += b"".join(
                f"{offset:010} 00000 n \n".encode() for offset in offsets[1:]
            )
            data += f"trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF".encode()
            path.write_bytes(data)
            pdf = artifacts.extract_pdf(path)
            self.assertEqual(pdf["page_count"], 2)
            self.assertIn("page 2", pdf["pages"][1]["original_text"])
            doc = record()
            doc.update(pdf=pdf, translation_status="complete")
            with self.assertRaises(ValueError):
                artifacts.validate(doc)
            pdf["visual_review_complete"] = True
            for page in pdf["pages"]:
                page.update(translation_ja="公式の例。", translation_status="complete")
            artifacts.validate(doc)

    def test_notification_argument_not_script(self):
        summary = "あ" * 36 + '"\\$;'
        self.assertEqual(len(summary), 40)
        with patch.object(watcher.subprocess, "run") as run:
            watcher.announce(summary)
            args = run.call_args.args[0]
            self.assertEqual(args[-1], summary)
            self.assertNotIn(summary, args[2])
        with self.assertRaises(ValueError):
            watcher.announce("短すぎる")

    def test_first_scan_does_not_replay_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "seen.json"
            doc = {
                "id": "existing",
                "notification_eligible": True,
                "summary_ja_40": "あ" * 40,
            }
            with (
                patch.object(
                    watcher,
                    "git",
                    side_effect=["", "data/knowledge/us/a.json", json.dumps(doc)],
                ),
                patch.object(watcher, "announce") as announce,
            ):
                watcher.scan(Path(tmp), state)
                announce.assert_not_called()
            self.assertEqual(json.loads(state.read_text()), ["existing"])


if __name__ == "__main__":
    unittest.main()
