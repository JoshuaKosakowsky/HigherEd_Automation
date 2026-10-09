"""1305 GUI service authorization, native extraction and manual-path contracts."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from app.gui.models import WorkflowContext, WorkflowMode
from app.gui.services.graduate_contract_recon import run_graduate_contract_recon
from shared.cancellation import CancellationToken, WorkflowCancelled
from test_graduate_contract_recon import BN_HEADERS, banner_from_frame, bn_row, workday, wd_row


class GraduateContractServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "review.xlsx"
        self.inputs = dict(banner_source="manual", workday_file=Path(self.temp.name) / "wd.xlsx",
            banner_file=Path(self.temp.name) / "bn.xlsx", output_file=self.output,
            start_date="2026-09-01", end_date="2026-09-30", detail_codes="TPDT")
        self.sources = [workday([wd_row()]), banner_from_frame(pd.DataFrame([bn_row()], columns=BN_HEADERS))]

    def context(self, mode=None, **kwargs):
        return WorkflowContext("graduate_contract_recon", self.inputs, mode, **kwargs)

    def test_manual_path_uploads_only_and_never_authenticates(self):
        with patch("app.gui.services.graduate_contract_recon.read_source", side_effect=self.sources), patch(
            "app.gui.services.graduate_contract_recon.build_authenticated_client") as auth:
            result = run_graduate_contract_recon(self.context())
        self.assertTrue(result.success)
        self.assertTrue(self.output.is_file())
        auth.assert_not_called()

    def test_non_admin_cannot_forge_prod_source(self):
        self.inputs["banner_source"] = "sql"
        with patch("app.gui.services.graduate_contract_recon.get_shared_gui_access_path", return_value=Path("synthetic")), patch(
            "app.gui.services.graduate_contract_recon.load_access_configuration") as policy, patch(
            "app.gui.services.graduate_contract_recon.build_authenticated_client") as auth:
            policy.return_value.is_administrator.return_value = False
            with self.assertRaisesRegex(ValueError, "Only an administrator"):
                run_graduate_contract_recon(self.context(WorkflowMode.PRODUCTION))
        auth.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_admin_prod_uses_existing_parameterized_complete_extract(self):
        self.inputs["banner_source"] = "sql"
        client = MagicMock(); client.__enter__.return_value = client
        frame = pd.DataFrame([bn_row()], columns=BN_HEADERS); frame["__activity_row_count"] = 1
        client.run_sql.return_value = frame
        with patch("app.gui.services.graduate_contract_recon.get_shared_gui_access_path", return_value=Path("synthetic")), patch(
            "app.gui.services.graduate_contract_recon.load_access_configuration") as policy, patch(
            "app.gui.services.graduate_contract_recon.read_source", return_value=self.sources[0]), patch(
            "app.gui.services.graduate_contract_recon.load_department_profiles") as profiles, patch(
            "app.gui.services.graduate_contract_recon.build_authenticated_client", return_value=(client, "cached")) as auth:
            policy.return_value.is_administrator.return_value = True
            result = run_graduate_contract_recon(self.context(WorkflowMode.PRODUCTION))
        self.assertTrue(result.success)
        self.assertTrue(auth.call_args.kwargs["use_saved_mines_login"])
        self.assertIn("IN ('TPDT')", client.run_sql.call_args.args[0])
        self.assertIn("COUNT(*) OVER ()", client.run_sql.call_args.args[0])
        profiles.return_value.__getitem__.assert_called_with("PROD")

    def test_invalid_codes_output_or_mode_stops_before_authentication(self):
        with patch("app.gui.services.graduate_contract_recon.build_authenticated_client") as auth:
            self.inputs["detail_codes"] = ""
            with self.assertRaises(ValueError):
                run_graduate_contract_recon(self.context())
            self.inputs["detail_codes"] = "TPDT"
            with self.assertRaisesRegex(ValueError, "does not use TEST or PROD"):
                run_graduate_contract_recon(self.context(WorkflowMode.PRODUCTION))
            self.output.write_bytes(b"existing")
            with self.assertRaises(ValueError):
                run_graduate_contract_recon(self.context())
            self.assertEqual(self.output.read_bytes(), b"existing")
        auth.assert_not_called()

    def test_cancelled_request_cannot_publish(self):
        token = CancellationToken(); token.request()
        with patch("app.gui.services.graduate_contract_recon.build_authenticated_client") as auth:
            with self.assertRaises(WorkflowCancelled):
                run_graduate_contract_recon(self.context(cancellation=token))
        auth.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_auth_errors_are_sanitized_before_general_logger(self):
        self.inputs["banner_source"] = "sql"
        with patch("app.gui.services.graduate_contract_recon.get_shared_gui_access_path", return_value=Path("synthetic")), patch(
            "app.gui.services.graduate_contract_recon.load_access_configuration") as policy, patch(
            "app.gui.services.graduate_contract_recon.read_source", return_value=self.sources[0]), patch(
            "app.gui.services.graduate_contract_recon.load_department_profiles"), patch(
            "app.gui.services.graduate_contract_recon.build_authenticated_client", side_effect=RuntimeError("synthetic-secret")):
            policy.return_value.is_administrator.return_value = True
            with self.assertRaises(ValueError) as caught:
                run_graduate_contract_recon(self.context(WorkflowMode.PRODUCTION))
        self.assertNotIn("synthetic-secret", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)


if __name__ == "__main__":
    unittest.main()
