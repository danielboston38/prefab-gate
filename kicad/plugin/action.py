"""The toolbar button. Rendering only — no policy lives here.

Every KiCad import in the plugin is in this file. staging, runner and summary
import neither pcbnew nor wx, which is what lets them be tested without KiCad
and what would make a future port to the IPC API a rewrite of this file alone.
"""
import os

import pcbnew
import wx

from . import runner, staging, summary


class PrefabGateAction(pcbnew.ActionPlugin):

    def defaults(self):
        self.name = "prefab-gate: check this board"
        self.category = "Design verification"
        self.description = ("Run DRC with zone refill and schematic parity "
                            "against a copy, and report what blocks fab.")
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "icon24.png")

    def Run(self):
        board_path = pcbnew.GetBoard().GetFileName()
        try:
            result = runner.run_check(board_path)
        except staging.StagingError as exc:
            wx.MessageBox(str(exc), "prefab-gate", wx.OK | wx.ICON_WARNING)
            return
        except Exception as exc:  # noqa: BLE001
            # A plugin that dies silently leaves the user believing the board
            # was checked. Anything unexpected is reported as "not verified".
            wx.MessageBox(
                f"prefab-gate could not check this board, so it is "
                f"unverified.\n\n{exc.__class__.__name__}: {exc}",
                "prefab-gate", wx.OK | wx.ICON_ERROR)
            return

        passed = bool(result.verdict and result.verdict.get("passed"))
        icon = wx.ICON_INFORMATION if passed else wx.ICON_WARNING
        dialog = wx.MessageDialog(None, summary.summarise(result, board_path),
                                  "prefab-gate", wx.OK | icon)
        dialog.ShowModal()
        dialog.Destroy()
