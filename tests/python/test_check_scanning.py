"""Exercise PaperCut intake and permanent redaction using synthetic documents only."""

from datetime import date
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import pypdfium2 as pdf

from shared.mines_paths import get_cashnet_copies_directory, get_papercut_scan_directory
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
        self.assertEqual(inspect_page(0, [line("Pay to the order of", .1, .5)]).status, "Needs a look")
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
        # A scanner may include an invisible searchable text layer and PDF metadata.
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QPainter, QPdfWriter
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        writer = QPdfWriter(buffer)
        writer.setTitle("PRIVATE TEST TITLE")
        p = QPainter(writer)
        p.drawText(500, 600, "SYNTHETIC PRIVATE CHECK LINE")
        p.end()
        del writer
        with pdf.PdfDocument(bytes(buffer.data())) as doc:
            self.assertGreater(doc[0].get_textpage().count_chars(), 5)
            doc[0].set_cropbox(2, 4, 500, 660)
            doc[0].set_rotation(90)
            doc.new_attachment("unredacted-original").set_data(b"PRIVATE-ATTACHMENT")
            original = io.BytesIO()
            doc.save(original)
        out = io.BytesIO()
        redact_pdf(original.getvalue(), [Mark(0, "MICR", Box(.15,.25,.55,.35))], out)
        with pdf.PdfDocument(out.getvalue()) as result:
            self.assertEqual(result.count_attachments(), 0)
            self.assertEqual(result[0].get_textpage().count_chars(), 0)
            self.assertNotIn("PRIVATE", str(result.get_metadata_dict()))
            pixels = page_pixels(out.getvalue(), 0)
            height, width = pixels.shape[:2]
            self.assertEqual(pixels.shape, page_pixels(original.getvalue(), 0).shape)
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

        command = ["python.exe", "-m", "workflows.check_scanning.watch"]
        with (patch.object(check_scanning.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True),
              patch.object(check_scanning.subprocess, "Popen") as launch):
            self.assertIs(check_scanning.start_check_scan_process(command), launch.return_value)
            self.assertEqual(launch.call_args.args, (command,))
            self.assertEqual(launch.call_args.kwargs["creationflags"], 0x08000000)

    def test_empty_inbox_waits_for_scans(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
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

    def test_queue_summarizes_approved_files_and_closes_after_intake_catches_up(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit
        from app.gui.pages.check_scans import CheckInbox, CheckReview

        app = QApplication.instance() or QApplication([])
        first = self.inbox / "first scan.pdf"
        second = self.inbox / "second scan.pdf"
        first.write_bytes(self.source)
        second.write_bytes(self.source + b"\n% second synthetic scan\n")
        intake = ScanIntake(self.queue)
        self.index(intake)
        pending = self.inbox / "incoming memo.txt"
        pending.write_text("This file should not interrupt check review.", encoding="utf-8")
        self.assertTrue(self.queue.has_pending_intake())

        serials = iter(("000482", "000483"))
        summaries = []

        def approve(viewer):
            viewer.show_page(1)
            viewer.number.setText(next(serials))
            viewer.confirm.click()
            self.assertTrue(viewer.approve.isEnabled())
            viewer.approve.click()
            self.assertIsNotNone(viewer.saved_path)

        def read_summary(dialog):
            summaries.append(dialog.windowTitle())
            self.assertEqual(dialog.windowTitle(), "Queue complete")
            labels = [label.text() for label in dialog.findChildren(QLabel)]
            self.assertIn("2 redacted PDFs saved.", labels)
            self.assertIn(str(self.inbox), labels)
            self.assertIn(str(self.home / "Documents" / "Tests"), labels)
            files = dialog.findChild(QPlainTextEdit).toPlainText().splitlines()
            self.assertEqual(files, [
                "first scan.pdf → Example Company LLC - 000482.pdf",
                "second scan.pdf → Example Company LLC - 000483.pdf",
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
            view.review()
            self.assertEqual(summaries, [])
            self.assertTrue(view.isVisible())
            self.assertIn("Checking remaining incoming scans", view.status.text())
            with patch("workflows.check_scanning.intake.monotonic", side_effect=[7, 10]):
                intake.poll()
                intake.poll()
            self.assertFalse(self.queue.has_pending_intake())
            view.check_completion()
            self.assertEqual(summaries, ["Queue complete"])
            self.assertFalse(view.isVisible())
            worker.kill.assert_called_once()
        self.assertEqual(first.read_bytes(), self.source)
        self.assertTrue(second.is_file())
        self.assertTrue(pending.is_file())
