"""Exercise PaperCut intake and permanent redaction using synthetic documents only."""

from datetime import date
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import pypdfium2 as pdf

from shared.mines_paths import get_cashnet_copies_directory, get_papercut_scan_directory
from app.gui.services.process import python_module_launch
from workflows.check_scanning.detection import Box, Line, Mark, inspect_page
from workflows.check_scanning.documents import inspect_pdf, page_count, page_pixels, redact_pdf
from workflows.check_scanning.intake import ScanIntake, ScanQueue, decode_finding, output_name


def picture(check=False):
    h, w = (420, 1000) if check else (700, 550)
    pixels = np.full((h, w, 3), 255, np.uint8)
    labels = [(32, 42, "SAMPLE INVOICE"), (32, 100, "Invoice 0987")] if not check else [
        (40, 45, "Example Company LLC"), (710, 48, "Check #000482"),
        (40, 143, "Pay to the order of"), (570, 152, "123.00"),
        (620, 277, "Sample Signer"), (620, 308, "Authorized Signature"),
        (65, 371, "123456780   44000123456   000482"),
    ]
    for x, y, text in labels:
        cv2.putText(pixels, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, .8, (0, 0, 0), 2, cv2.LINE_AA)
    return pixels


def packet(*pages):
    with pdf.PdfDocument.new() as document:
        for pixels in pages:
            h, w = pixels.shape[:2]
            page = document.new_page(w / 2, h / 2)
            obj = pdf.PdfImage.new(document)
            bitmap = pdf.PdfBitmap.new_native(w, h, pdf.raw.FPDFBitmap_BGR)
            bitmap.to_numpy()[:] = pixels
            obj.set_bitmap(bitmap)
            obj.set_matrix(pdf.PdfMatrix().scale(w / 2, h / 2))
            page.insert_obj(obj)
            page.gen_content()
            page.close()
            bitmap.close()
        result = io.BytesIO()
        document.save(result)
        return result.getvalue()


def pdf_with_invisible_text() -> bytes:
    # Use a standard PDF font and invisible text rendering mode (3 Tr).
    # The input text is searchable without depending on the host's Qt fonts.
    content = b"BT /F1 18 Tf 3 Tr 72 550 Td (SYNTHETIC PRIVATE CHECK LINE) Tj ET"
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Title (PRIVATE TEST TITLE) >>",
    )
    fixture = io.BytesIO()
    fixture.write(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(fixture.tell())
        fixture.write(b"%d 0 obj\n%s\nendobj\n" % (number, obj))
    xref = fixture.tell()
    fixture.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(offsets) + 1))
    for offset in offsets:
        fixture.write(b"%010d 00000 n \n" % offset)
    fixture.write(b"trailer\n<< /Size %d /Root 1 0 R /Info 6 0 R >>\n"
                  b"startxref\n%d\n%%%%EOF\n" % (len(offsets) + 1, xref))
    return fixture.getvalue()


class CheckScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {"OneDriveCommercial": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        self.home = self.root / "home"
        home = patch.object(Path, "home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)
        self.inbox = get_papercut_scan_directory()
        self.inbox.mkdir(parents=True)
        self.queue = ScanQueue(self.inbox, self.root / "local" / "queue.db")
        self.source = packet(picture(), picture(True))
        self.day = date(2026, 7, 1)

    def index(self, intake):
        with patch("workflows.check_scanning.intake.monotonic", side_effect=[1, 4]):
            intake.poll()
            self.assertFalse(self.queue.records(True))
            intake.poll()

    def test_exact_business_paths_year_rollover_and_safe_names(self):
        self.assertEqual(self.inbox.relative_to(self.root).parts, ("Apps", "Scans for PaperCut MF"))
        folder = get_cashnet_copies_directory(date(2026, 6, 30))
        self.assertEqual(folder.relative_to(self.root).parts, ("GRP-Office of the Controller - Documents",
                         "Accounting", "Accounting (Shared)", "CASHIER", "CASHNet Copies", "FY26"))
        self.assertEqual(get_cashnet_copies_directory(self.day), folder.with_name("FY27"))
        self.assertEqual(output_name("Example LLC", "000482"), "Example LLC - 000482.pdf")
        self.assertEqual(output_name("Example, Inc.", "000482"), "Example, Inc. - 000482.pdf")
        for name, number in (("../Other", "123"), ("A", "../other"), ("", "001"), ("A", "")):
            with self.assertRaises(ValueError):
                output_name(name, number)

    def test_micr_symbols_and_split_numeric_evidence_anywhere_on_page(self):
        def line(text, x1, x2):
            return Line(text, Box(x1, .23, x2, .27))
        for parts in ([line("⑆123456780⑆", .22, .4)], [line("123456780", .22, .4), line("44000123456", .43, .63)]):
            finding = inspect_page(2, parts)
            self.assertEqual(finding.status, "Check")
            self.assertEqual(finding.marks[0].page, 2)
            self.assertLess(finding.marks[0].box.left, .22)
        self.assertEqual(inspect_page(0, [line("Pay to the order of", .1, .5)]).status, "Needs Review")
        self.assertEqual(inspect_page(0, [line("Invoice number 123456780", .1, .6)]).status, "Unrelated")

    def test_stability_mixed_names_unrelated_restart_and_catchup(self):
        longname = "custom vendor packet.PDF"
        (self.inbox / longname).write_bytes(self.source)
        (self.inbox / "renamed without extension").write_bytes(packet(picture()))
        (self.inbox / "summary.txt").write_text("Ignore me")
        (self.inbox / "pending.tmp").write_bytes(self.source[:400])
        (self.inbox / "broken.pdf").write_bytes(b"%PDF-incomplete")
        calls = []
        def recognize(image):
            calls.append(None)
            return [Line("⑆123456780⑆", Box(.2,.6,.6,.7))] if image.shape[1] > image.shape[0] else [
                Line("Invoice", Box(.1,.1,.3,.2))]
        intake = ScanIntake(self.queue, recognize)
        self.index(intake)
        self.assertEqual({r["name"]: r["status"] for r in self.queue.records(True)},
                         {longname: "Check", "renamed without extension": "Unrelated", "broken.pdf": "Could not read"})
        self.assertEqual(len(calls), 3)
        self.assertEqual(decode_finding(next(r for r in self.queue.records() if r["name"] == longname)).marks[0].page, 1)
        restart = ScanIntake(self.queue, recognize)
        restart.poll()
        self.assertEqual(len(calls), 3)
        (self.inbox / longname).write_bytes(packet(picture()))
        with patch("workflows.check_scanning.intake.monotonic", side_effect=[10,13]):
            restart.poll()
            restart.poll()
        self.assertEqual([r["name"] for r in self.queue.records()], ["broken.pdf"])
        self.assertEqual(self.source[:5], b"%PDF-")

    def test_local_ocr_named_fields_and_permanent_filing(self):
        name = "changed by cashier.pdf"
        (self.inbox / name).write_bytes(self.source)
        self.index(ScanIntake(self.queue))
        record, = self.queue.records()
        finding = decode_finding(record)
        self.assertEqual(finding.status, "Check")
        self.assertEqual(finding.number, "000482")
        self.assertIn("Example Company", finding.issuer)
        self.assertEqual({(m.page, m.kind) for m in finding.marks}, {(1,"MICR"),(1,"Signature")})
        shared = get_cashnet_copies_directory(self.day)
        shared.mkdir(parents=True)
        folder = self.home / "Documents" / "Tests"
        self.assertFalse(folder.exists())
        with self.assertRaisesRegex(ValueError, "signature"):
            self.queue.file(record, [finding.marks[0]], finding.issuer, finding.number)
        self.assertFalse(folder.exists())
        collision = folder / output_name(finding.issuer, finding.number)
        folder.mkdir(parents=True)
        collision.write_bytes(b"an existing document")
        with self.assertRaises(FileExistsError):
            self.queue.file(record, finding.marks, finding.issuer, finding.number)
        self.assertEqual(collision.read_bytes(), b"an existing document")
        collision.unlink()
        folder.rmdir()
        target = self.queue.file(record, finding.marks, finding.issuer, finding.number)
        self.assertEqual(target, collision)
        self.assertEqual(list(shared.iterdir()), [])
        data = target.read_bytes()
        self.assertEqual(page_count(data), 2)
        self.assertEqual((self.inbox/name).read_bytes(), self.source)
        with pdf.PdfDocument(data) as doc:
            for page in doc:
                self.assertEqual(page.get_textpage().count_chars(), 0)
                self.assertEqual([obj.type for obj in page.get_objects()], [pdf.raw.FPDF_PAGEOBJ_IMAGE])
            self.assertEqual(doc[0].get_size(), (275.,350.))
            self.assertEqual(doc[1].get_size(), (500.,210.))
            embedded = next(doc[1].get_objects()).get_bitmap().to_numpy().copy()
        # Inspect the embedded image itself. An overlay could hide intact source pixels.
        for mark in finding.marks:
            b = mark.box
            h, w = embedded.shape[:2]
            interior = embedded[int(b.top*h)+1:int(b.bottom*h)-1, int(b.left*w)+1:int(b.right*w)-1]
            self.assertGreater(interior.size, 0)
            self.assertEqual(interior.max(), 0)
        self.assertLess(np.abs(page_pixels(data,0).astype(float)-page_pixels(self.source,0)).mean(), 2.)
        self.assertEqual(self.queue.records(), [])
        self.assertEqual(self.queue.file(record, finding.marks, finding.issuer, finding.number), target)
        self.assertEqual(list(folder.iterdir()), [target])

    def test_changed_source_and_invalid_geometry(self):
        path = self.inbox / "packet.pdf"
        path.write_bytes(self.source)
        self.index(ScanIntake(self.queue, lambda _: []))
        record, = self.queue.records()
        path.write_bytes(packet(picture()))
        with self.assertRaisesRegex(ValueError, "changed"):
            self.queue.source(record)
        with self.assertRaises(ValueError):
            redact_pdf(self.source, [Mark(0, "MICR", Box(.2,.3,.1,.4))], io.BytesIO())

    def test_hidden_text_attachment_and_rotated_crop_do_not_survive_as_source_objects(self):
        with pdf.PdfDocument(pdf_with_invisible_text()) as doc:
            doc[0].set_cropbox(2, 4, 500, 660)
            doc[0].set_rotation(90)
            doc.new_attachment("unredacted-original").set_data(b"PRIVATE-ATTACHMENT")
            original = io.BytesIO()
            doc.save(original)
        source = original.getvalue()
        with pdf.PdfDocument(source) as doc:
            self.assertEqual(doc[0].get_rotation(), 90)
            self.assertEqual(doc[0].get_cropbox(), (2, 4, 500, 660))
            self.assertIn("SYNTHETIC PRIVATE CHECK LINE", doc[0].get_textpage().get_text_range())
            self.assertEqual(doc.get_metadata_value("Title"), "PRIVATE TEST TITLE")
            self.assertEqual(doc.count_attachments(), 1)
        source_pixels = page_pixels(source, 0)
        self.assertTrue(np.all(source_pixels == 255))

        out = io.BytesIO()
        redact_pdf(source, [Mark(0, "MICR", Box(.15, .25, .55, .35))], out)
        with pdf.PdfDocument(out.getvalue()) as result:
            self.assertEqual(result.count_attachments(), 0)
            self.assertEqual(result[0].get_textpage().count_chars(), 0)
            self.assertNotIn("PRIVATE", str(result.get_metadata_dict()))
            pixels = page_pixels(out.getvalue(), 0)
            height, width = pixels.shape[:2]
            self.assertEqual(pixels.shape, source_pixels.shape)
            self.assertEqual(pixels[int(height*.30),int(width*.3)].max(),0)

    def test_two_check_faces_block_filing(self):
        name = self.inbox / "two.pdf"
        name.write_bytes(packet(picture(True), picture(True)))
        self.index(ScanIntake(self.queue, lambda _: [Line("⑆123456780⑆", Box(.1,.8,.7,.9))]))
        record, = self.queue.records()
        self.assertEqual(record["status"], "Multiple check pages")
        with self.assertRaisesRegex(ValueError, "multi-check"):
            self.queue.file(record, [], "Example", "111")

    def test_watcher_starts_using_the_same_local_queue_as_review(self):
        from workflows.check_scanning import watch
        with (patch.dict(os.environ, {"LOCALAPPDATA": str(self.root/"profile")}),
              patch.object(ScanIntake, "poll", autospec=True) as poll,
              patch.object(watch.time, "sleep", side_effect=KeyboardInterrupt)):
            with self.assertRaises(KeyboardInterrupt):
                watch.main()
            instance, = poll.call_args.args
            self.assertEqual(instance.queue.inbox, self.inbox)
            self.assertEqual(instance.queue.database.name, "pilot-queue.sqlite3")
            self.assertTrue(instance.queue.database.is_file())

    def test_missing_renderer_shows_setup_instructions(self):
        from app.gui.models import WorkflowContext
        from app.gui.services import check_scanning
        from shared.workflow_errors import WorkflowUserError

        missing = ModuleNotFoundError("No module named 'pypdfium2'", name="pypdfium2")
        with (patch.object(check_scanning, "import_module", side_effect=missing),
              patch.object(check_scanning, "start_check_scan_process") as launch):
            with self.assertRaisesRegex(WorkflowUserError, r"run setup\.ps1") as error:
                check_scanning.run_check_scanning(WorkflowContext("check_scan_review", {}))
            self.assertIs(error.exception.__cause__, missing)
            launch.assert_not_called()

    def test_check_scan_process_uses_no_console_flag_on_windows(self):
        from app.gui.services import check_scanning

        module = "workflows.check_scanning.watch"
        command, environment = python_module_launch(module)
        with (patch.object(check_scanning.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True),
              patch.object(check_scanning.subprocess, "Popen") as launch):
            self.assertIs(check_scanning.start_check_scan_process(module), launch.return_value)
            self.assertEqual(launch.call_args.args, (command,))
            self.assertEqual(launch.call_args.kwargs["env"], environment)
            self.assertEqual(launch.call_args.kwargs["creationflags"], 0x08000000)

    def test_windows_pdfium_startup_primes_the_platform_cache_with_native_version(self):
        from shared import windows_platform
        from workflows.check_scanning import documents

        windows = SimpleNamespace(
            platform="win32", getwindowsversion=lambda: SimpleNamespace(platform_version=(10, 0, 26100))
        )
        original_lookup = windows_platform.platform._syscmd_ver

        def check_lookup():
            self.assertEqual(windows_platform.platform._syscmd_ver(), ("", "", "10.0.26100"))

        with (patch.object(windows_platform, "sys", windows),
              patch.object(windows_platform.platform, "uname", side_effect=check_lookup) as uname,
              patch.object(documents, "import_module", return_value=pdf) as load):
            self.assertIs(documents._load_pdfium(), pdf)
            self.assertIs(windows_platform.platform._syscmd_ver, original_lookup)
            uname.assert_called_once()
            load.assert_called_once_with("pypdfium2")

    @unittest.skipUnless(sys.platform == "win32", "Windows console discovery is Windows-only")
    def test_windows_check_scan_imports_keep_the_venv_without_a_console(self):
        probe = r"""
import ctypes
from pathlib import Path
import platform
import re
import sys

def check_for_console_probe(event, args):
    if event == "subprocess.Popen" and re.search(r"\bver\b", str(args[1]), flags=re.I):
        raise AssertionError("Check scan startup attempted to run the Windows ver command")

sys.addaudithook(check_for_console_probe)
from workflows.check_scanning import intake
import rapidocr
import onnxruntime
assert platform.system() == "Windows"
assert Path(sys.prefix).resolve() == Path(sys.argv[1]).resolve()
assert not ctypes.windll.kernel32.GetConsoleWindow()
"""
        command, environment = python_module_launch("workflows.check_scanning.watch")
        result = subprocess.run(
            [command[0], "-c", probe, sys.prefix], cwd=Path(__file__).resolve().parents[2],
            env=environment, capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_empty_inbox_waits_for_scans(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication, QPushButton
        from app.gui.pages.check_scans import CheckInbox

        app = QApplication.instance() or QApplication([])
        self.assertEqual(list(self.inbox.iterdir()), [])
        ScanIntake(self.queue).poll()
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "profile")}):
            view = CheckInbox(self.queue)
            try:
                self.assertEqual(view.listing.count(), 0)
                self.assertFalse(view.open_button.isEnabled())
                self.assertIn("Watching for new scans", view.status.text())
                self.assertNotIn(
                    "Enable scanning at sign-in",
                    {button.text() for button in view.findChildren(QPushButton)},
                )
            finally:
                view.reject()
                app.processEvents()

    def test_visible_transit_shapes_locate_band_without_any_recognized_text(self):
        from workflows.check_scanning.micr import transit_bands
        pixels = np.full((800,1000,3), 255, np.uint8)
        x, y, pitch = 95, 320, 24
        for start in (x, x+10*pitch):
            pixels[y+4:y+19,start:start+5] = 0
            pixels[y:y+7,start+10:start+17] = 0
            pixels[y+16:y+23,start+10:start+17] = 0
        no_digits = pixels.copy()
        self.assertEqual(transit_bands(no_digits), [])
        for offset, digit in enumerate("123456780", start=1):
            cv2.putText(pixels, digit, (x+pitch*offset, y+22), cv2.FONT_HERSHEY_SIMPLEX, .9, (0,0,0), 2)
        cv2.putText(pixels,"000482", (x+pitch*12,y+22),cv2.FONT_HERSHEY_SIMPLEX,.9,(0,0,0),2)
        finding = inspect_pdf(packet(pixels), lambda _: [])
        self.assertEqual(finding.status, "Check")
        band, = finding.marks
        self.assertLess(band.box.left, x/1000)
        self.assertGreater(band.box.right, (x+pitch*12+75)/1000)
        self.assertGreater(band.box.top, .3)

    def test_cashier_draw_move_resize_undo_and_preview(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from app.gui.pages.check_scans import CheckReview

        app = QApplication.instance() or QApplication([])
        (self.inbox / "manual.pdf").write_bytes(packet(picture(True)))
        self.index(ScanIntake(self.queue, lambda _: []))
        record, = self.queue.records()
        view = CheckReview(None, self.queue, record)
        view.issuer.setText("Example LLC")
        view.number.setText("000482")
        target = self.home / "Documents" / "Tests" / "Example LLC - 000482.pdf"
        self.assertEqual(view.destination.text(), str(target))
        view.show()
        self.addCleanup(view.close)
        app.processEvents()
        canvas = view.canvas
        start = QPoint(canvas.width()//5, canvas.height()//3)
        end = start+QPoint(60, 30)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
        before = view.marks[0].box
        center = (start+end)/2
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=center+QPoint(9, 5))
        moved = view.marks[0].box
        self.assertGreater(moved.left, before.left)
        corner = canvas.box_rect(moved).bottomRight().toPoint()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=corner)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=corner+QPoint(20, 10))
        self.assertGreater(view.marks[0].box.right, moved.right)
        view.remove()
        self.assertEqual(view.marks, [])
        view.undo()
        self.assertEqual(len(view.marks), 1)
        view.preview.setChecked(True)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(10,10))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(50,40))
        self.assertEqual(len(view.marks), 1)
        self.assertFalse(view.approve.isEnabled())
        self.assertIn("missing redactions (Signature)", view.approval_status.text())
        view.marks.append(Mark(0, "Signature", Box(.65, .55, .9, .75)))
        view.update_approval()
        self.assertTrue(view.confirm.isEnabled())
        view.confirm.setChecked(True)
        view.approve.click()
        self.assertEqual(page_count(target.read_bytes()), 1)
        self.assertEqual(self.queue.records(), [])

    def test_review_explains_approval_requirements_before_saving(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from app.gui.pages.check_scans import CheckReview

        app = QApplication.instance() or QApplication([])
        (self.inbox / "packet.pdf").write_bytes(self.source)
        self.index(ScanIntake(self.queue))
        record, = self.queue.records()
        view = CheckReview(None, self.queue, record)
        view.show()
        self.addCleanup(view.close)
        app.processEvents()
        self.assertFalse(view.approve.isEnabled())
        self.assertIn("remaining page", view.approval_status.text())
        view.next.click()
        view.issuer.setText("Example: Inc.")
        self.assertIn("Windows filename characters", view.approval_status.text())
        view.issuer.setText("Example Inc.")
        self.assertIn("review confirmation", view.approval_status.text())
        view.confirm.click()
        self.assertTrue(view.approve.isEnabled())
        point = view.canvas.box_rect(view.marks[0].box).center().toPoint()
        QTest.mouseClick(view.canvas, Qt.MouseButton.LeftButton, pos=point)
        self.assertTrue(view.approve.isEnabled())
        view.number.setText("000483")
        self.assertFalse(view.approve.isEnabled())
        self.assertIn("review confirmation", view.approval_status.text())
        view.confirm.click()
        view.approve.click()
        target = self.home / "Documents" / "Tests" / "Example Inc. - 000483.pdf"
        self.assertEqual(page_count(target.read_bytes()), 2)

    def test_selected_queue_advances_through_three_checks_including_a_filed_scan(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit
        from app.gui.pages.check_scans import CheckInbox, CheckReview

        app = QApplication.instance() or QApplication([])
        first = self.inbox / "first scan.pdf"
        second = self.inbox / "second scan.pdf"
        third = self.inbox / "third scan.pdf"
        first.write_bytes(self.source)
        second.write_bytes(self.source + b"\n% second synthetic scan\n")
        third.write_bytes(self.source + b"\n% third synthetic scan\n")
        skipped_scan = self.inbox / "skip scan.pdf"
        skipped_scan.write_bytes(self.source + b"\n% skip this check\n")
        unselected = self.inbox / "unselected scan.pdf"
        unselected.write_bytes(self.source + b"\n% leave this check in the inbox\n")
        self.index(ScanIntake(self.queue))
        previously_filed = next(record for record in self.queue.records() if record["name"] == third.name)
        self.queue.file(previously_filed, decode_finding(previously_filed).marks, "Example Company LLC", "000484")

        serials = iter(("000482", "000483", "000484"))
        reviewed = []
        summaries = []

        def approve(viewer):
            reviewed.append(viewer.record["name"])
            if viewer.record["name"] == skipped_scan.name:
                viewer.skip()
                return
            viewer.show_page(1)
            viewer.issuer.setText("Example Company LLC")
            viewer.number.setText(next(serials))
            viewer.confirm.click()
            self.assertTrue(viewer.approve.isEnabled())
            viewer.approve.click()
            self.assertIsNotNone(viewer.saved_path)

        def read_summary(dialog):
            summaries.append(dialog.windowTitle())
            self.assertEqual(dialog.windowTitle(), "Queue complete")
            labels = [label.text() for label in dialog.findChildren(QLabel)]
            self.assertIn("3 redacted PDFs saved.", labels)
            self.assertIn(str(self.inbox), labels)
            self.assertIn(str(self.home / "Documents" / "Tests"), labels)
            files = dialog.findChild(QPlainTextEdit).toPlainText().splitlines()
            self.assertEqual(files, [
                "first scan.pdf → Example Company LLC - 000482.pdf",
                "second scan.pdf → Example Company LLC - 000483.pdf",
                "third scan.pdf → Example Company LLC - 000484 (2).pdf",
                "", "Skipped", skipped_scan.name,
            ])
            buttons = dialog.findChild(QDialogButtonBox)
            buttons.button(QDialogButtonBox.StandardButton.Close).click()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

        with (patch("app.gui.pages.check_scans.start_check_scan_process") as launch,
              patch.object(CheckReview, "exec", approve),
              patch.object(QDialog, "exec", read_summary)):
            worker = launch.return_value
            worker.poll.return_value = None
            view = CheckInbox(self.queue)
            self.addCleanup(view.close)
            view.show()
            app.processEvents()
            self.assertEqual(view.listing.count(), 4)
            view.other.setChecked(True)
            view.sort_order.setCurrentText("Filename")
            view.filename_filter.setText("first")
            view.select_shown_button.click()
            view.filename_filter.clear()
            self.assertEqual(view.listing.item(0).checkState(), Qt.CheckState.Checked)
            view.listing.item(1).setCheckState(Qt.CheckState.Checked)
            view.listing.item(2).setCheckState(Qt.CheckState.Checked)
            view.listing.item(3).setCheckState(Qt.CheckState.Checked)
            self.assertEqual(view.open_button.text(), "Review queue (4)")
            view.open_button.click()
            self.assertEqual(reviewed, [first.name, second.name, skipped_scan.name, third.name])
            self.assertEqual(summaries, ["Queue complete"])
            self.assertFalse(view.isVisible())
            worker.kill.assert_called_once()
        self.assertEqual(first.read_bytes(), self.source)
        self.assertTrue(second.is_file())
        self.assertTrue(third.is_file())
        self.assertEqual({record["name"] for record in self.queue.records()}, {skipped_scan.name, unselected.name})

    def test_filed_scan_can_be_reviewed_again_and_saves_numbered_test_copy(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication, QPushButton
        from app.gui.pages.check_scans import CheckInbox, CheckReview

        app = QApplication.instance() or QApplication([])
        (self.inbox / "packet.pdf").write_bytes(self.source)
        self.index(ScanIntake(self.queue))
        record, = self.queue.records()
        finding = decode_finding(record)
        original = self.queue.file(record, finding.marks, "Example LLC", "000482")
        original_bytes = original.read_bytes()
        repeated = original.with_stem(f"{original.stem} (2)")
        summaries = []

        def approve_again(viewer):
            self.assertEqual(viewer.record["status"], "Filed")
            buttons = {button.text(): button for button in viewer.findChildren(QPushButton)}
            self.assertIn("Not a check", buttons)
            self.assertFalse(buttons["Not a check"].isEnabled())
            viewer.issuer.setText("Example LLC")
            self.assertEqual(viewer.destination.text(), str(repeated))
            viewer.show_page(1)
            viewer.marks.append(Mark(0, "Other", Box(.55, .55, .70, .70)))
            viewer.confirm.click()
            self.assertTrue(viewer.approve.isEnabled())
            viewer.approve.click()

        def record_summary(inbox, skipped, unrelated):
            summaries.append(inbox.saved.copy())

        with (patch("app.gui.pages.check_scans.start_check_scan_process"),
              patch.object(CheckReview, "exec", approve_again),
              patch.object(CheckInbox, "show_completion", record_summary)):
            view = CheckInbox(self.queue)
            self.addCleanup(view.close)
            self.assertEqual(view.listing.count(), 0)
            view.other.setChecked(True)
            self.assertEqual(view.listing.count(), 1)
            view.review_one(view.listing.currentItem())
            self.assertEqual(view.saved, [("packet.pdf", repeated)])
            self.assertEqual(summaries, [view.saved])
            app.processEvents()

        self.assertEqual(original.read_bytes(), original_bytes)
        new_pixels = page_pixels(repeated.read_bytes(), 0)
        old_pixels = page_pixels(original_bytes, 0)
        point = (int(new_pixels.shape[0] * .6), int(new_pixels.shape[1] * .6))
        self.assertEqual(new_pixels[point].max(), 0)
        self.assertEqual(old_pixels[point].min(), 255)
        self.assertEqual(self.queue.file(record, finding.marks, "Example LLC", "000482"), original)

    def test_uncertain_scans_can_be_marked_unrelated_from_queue_and_preview(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QPushButton
        from app.gui.pages.check_scans import CheckInbox, CheckReview

        app = QApplication.instance() or QApplication([])
        first = self.inbox / "first scan.pdf"
        second = self.inbox / "second scan.pdf"
        first.write_bytes(self.source)
        second.write_bytes(self.source + b"\n% separate scan\n")
        self.index(ScanIntake(self.queue, lambda _: []))
        with self.queue.connect() as db:
            db.execute(
                "UPDATE scans SET status='Needs a look', finding=json_set(finding,'$.status','Needs a look')"
            )
        queue = ScanQueue(self.inbox, self.queue.database)
        self.assertEqual([r["status"] for r in queue.records()], ["Needs Review", "Needs Review"])
        self.assertEqual(decode_finding(queue.records()[0]).status, "Needs Review")
        self.assertFalse(queue.mark_unrelated({"name": first.name, "digest": "stale"}))

        def mark_in_preview(viewer):
            layout = viewer.layout()
            actions = layout.itemAt(layout.count() - 1).layout()
            skip = actions.itemAt(0).widget()
            not_a_check = actions.itemAt(1).widget()
            self.assertEqual((skip.text(), not_a_check.text()), ("Skip for now", "Not a check"))
            self.assertTrue(not_a_check.isEnabled())
            not_a_check.click()

        def verify_summary(inbox, skipped, unrelated):
            self.assertEqual(skipped, [])
            self.assertEqual(unrelated, [second.name])

        with (patch("app.gui.pages.check_scans.start_check_scan_process"),
              patch.object(CheckReview, "exec", mark_in_preview),
              patch.object(CheckInbox, "show_completion", verify_summary)):
            view = CheckInbox(queue)
            self.addCleanup(view.close)
            self.assertNotIn("Dismiss from queue", [button.text() for button in view.findChildren(QPushButton)])
            self.assertEqual(view.listing.count(), 2)
            self.assertTrue(view.listing.currentItem().text().startswith("Needs Review"))
            view.select_shown_button.click()
            self.assertEqual(view.open_button.text(), "Review queue (2)")
            view.not_a_check_button.click()
            self.assertEqual(view.listing.count(), 1)
            self.assertEqual(view.open_button.text(), "Review queue (1)")
            view.review_one(view.listing.currentItem())
            self.assertEqual(view.listing.count(), 0)
            view.other.setChecked(True)
            self.assertEqual(view.listing.count(), 2)
            self.assertFalse(view.not_a_check_button.isEnabled())
            statuses = {
                view.listing.item(i).data(Qt.ItemDataRole.UserRole)["status"]
                for i in range(view.listing.count())
            }
            self.assertEqual(statuses, {"Unrelated"})
            app.processEvents()
        reopened = ScanQueue(self.inbox, queue.database)
        ScanIntake(reopened).poll()
        self.assertEqual([r["status"] for r in reopened.records(True)], ["Unrelated", "Unrelated"])
        self.assertEqual(first.read_bytes(), self.source)
        self.assertTrue(second.is_file())
