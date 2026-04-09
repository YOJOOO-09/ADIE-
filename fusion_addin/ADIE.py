"""
ADIE — Autonomous Design Integrity Engine
Main Fusion 360 Add-in Entry Point: ADIE.py  (production)

ARCHITECTURE:
    run()   — wires Monitor + Mitigation, registers document events,
              adds an ADIE toolbar button to the Solid tab.
    stop()  — removes events and toolbar button cleanly.

CONFIGURATION:
    Edit adie/config.py or set GEMINI_API_KEY env var.
    This file reads from config.py via sys.path manipulation.

FUSION 360 ADD-IN LOADING:
    1. Tools → Scripts and Add-ins → Add-ins tab
    2. Click My Add-ins → + → browse to  adie/fusion_addin/
    3. Select ADIE (folder, not file) → Open
    4. Tick "Run on Startup" if desired → Run

AUTHOR: Aryn Gahlot | ADIE Project | Day 4
"""

# ─────────────────────────────────────────────────────────────────────────────
# Standard library
# ─────────────────────────────────────────────────────────────────────────────
import logging
import os
import sys
import traceback
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# adsk
# ─────────────────────────────────────────────────────────────────────────────
try:
    import adsk.core
    import adsk.fusion
    _ADSK_AVAILABLE = True
except ImportError:
    _ADSK_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# Path setup — add ADIE root and addin dir to sys.path
# ─────────────────────────────────────────────────────────────────────────────
_ADDIN_DIR  = Path(__file__).resolve().parent          # …/adie/fusion_addin/
_ADIE_ROOT  = _ADDIN_DIR.parent                        # …/adie/

for _p in [str(_ADDIN_DIR), str(_ADIE_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ─────────────────────────────────────────────────────────────────────────────
# File-based logging (persists across Fusion sessions)
# ─────────────────────────────────────────────────────────────────────────────
_LOG_FILE = _ADIE_ROOT / "data" / "adie.log"
_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(str(_LOG_FILE), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("ADIE")

# ─────────────────────────────────────────────────────────────────────────────
# Import config (after sys.path setup)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from config import CONFIG, ensure_data_dirs, summary as config_summary
    _CONFIG_OK = True
except ImportError as _ce:
    log.error("Cannot import config.py: %s", _ce)
    _CONFIG_OK = False

# ─────────────────────────────────────────────────────────────────────────────
# Toolbar constants
# ─────────────────────────────────────────────────────────────────────────────
CMD_ID          = "ADIE_RunValidation"
CMD_NAME        = "ADIE Validate"
CMD_DESCRIPTION = "Run ADIE design validation now (all rules)"
CMD_TOOLTIP     = "ADIE — Autonomous Design Integrity Engine\nValidates CAD against engineering standards."
PANEL_ID        = "SolidScriptsAddinsPanel"   # Scripts & Add-ins panel in Solid tab

# ─────────────────────────────────────────────────────────────────────────────
# Globals (kept across Fusion's GC cycles)
# ─────────────────────────────────────────────────────────────────────────────
_handlers   = []
_monitor    = None
_mitigation = None
_cmd_def    = None


# ─────────────────────────────────────────────────────────────────────────────
# Toolbar command handler
# ─────────────────────────────────────────────────────────────────────────────

if _ADSK_AVAILABLE:

    class _RunCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
        def __init__(self):
            super().__init__()

        def notify(self, args):
            try:
                cmd = args.command
                exec_handler = _RunCommandExecuteHandler()
                cmd.execute.add(exec_handler)
                _handlers.append(exec_handler)
            except Exception:
                log.error("CommandCreatedHandler:\n%s", traceback.format_exc())

    class _RunCommandExecuteHandler(adsk.core.CommandEventHandler):
        def __init__(self):
            super().__init__()

        def notify(self, args):
            try:
                log.info("ADIE toolbar button clicked — running validation.")
                if _monitor:
                    # Force-override debounce by resetting timestamp
                    _monitor._last_run = 0.0   # noqa: SLF001
                    _monitor.trigger()
                else:
                    log.warning("Monitor not initialised.")
            except Exception:
                log.error("CommandExecuteHandler:\n%s", traceback.format_exc())

else:

    class _RunCommandCreatedHandler:
        pass

    class _RunCommandExecuteHandler:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# run() — Fusion 360 add-in entry point
# ─────────────────────────────────────────────────────────────────────────────

def run(context):
    global _monitor, _mitigation, _handlers, _cmd_def

    ui = None
    try:
        if not _ADSK_AVAILABLE:
            log.error("adsk unavailable — run inside Fusion 360.")
            return

        app = adsk.core.Application.get()
        ui  = app.userInterface

        # Show console
        _console_write(ui, None)

        log.info("═══ ADIE starting ═══")

        if not _CONFIG_OK:
            ui.messageBox(
                "ADIE: config.py not found.\n"
                f"Expected at: {_ADIE_ROOT / 'config.py'}",
                "ADIE — Config Error",
            )
            return

        ensure_data_dirs()
        log.info(config_summary())

        # ── Import agents ─────────────────────────────────────────────────────
        try:
            from monitor_agent    import MonitorAgent, DocumentSavedHandler, DocumentActivatedHandler
            from mitigation_agent import MitigationAgent
        except Exception:
            msg = traceback.format_exc()
            log.error("Agent import failed:\n%s", msg)
            ui.messageBox(f"ADIE: Agent import failed:\n{msg}", "ADIE Error")
            return

        # ── Pre-condition check ───────────────────────────────────────────────
        scripts_dir = CONFIG["validation_scripts_dir"]
        if not scripts_dir.exists() or not list(scripts_dir.glob("*.py")):
            ui.messageBox(
                f"ADIE: No validation scripts found in:\n{scripts_dir}\n\n"
                "Run these setup commands first:\n"
                "  python setup\\analyst_agent.py --pdf YOUR.pdf\n"
                "  python setup\\synthesizer_agent.py\n\n"
                "(Pre-built sample scripts are in validation_scripts/ "
                "and should already be present.)",
                "ADIE — Setup Required",
                adsk.core.MessageBoxButtonTypes.OKButtonType,
                adsk.core.MessageBoxIconTypes.WarningIconType,
            )
            # Don't return — pre-built scripts may exist; let Monitor try anyway

        # ── Initialise Monitor ────────────────────────────────────────────────
        _monitor = MonitorAgent(
            scripts_dir       = CONFIG["validation_scripts_dir"],
            violations_path   = CONFIG["violations_json"],
            script_errors_log = CONFIG["script_errors_log"],
            rules_path        = CONFIG["rules_json"],
            config            = CONFIG,
        )
        _monitor.load()

        # ── Initialise Mitigation ─────────────────────────────────────────────
        api_key = CONFIG.get("gemini_api_key", "")
        _mitigation = MitigationAgent(
            api_key                 = api_key,
            audit_log_path          = CONFIG["audit_log_json"],
            pending_path            = CONFIG["pending_suggestion"],
            model_name              = CONFIG["gemini_model"],
            max_suggestions_per_run = CONFIG.get("mitigation_max_suggestions_per_run", 5),
        )

        # ── Wire Monitor → Mitigation ─────────────────────────────────────────
        _monitor.on_violations_ready = _mitigation.process_violations

        # ── Register document events ──────────────────────────────────────────
        saved_h = DocumentSavedHandler(_monitor)
        app.documentSaved.add(saved_h)
        _handlers.append(saved_h)

        activated_h = DocumentActivatedHandler(_monitor)
        app.documentActivated.add(activated_h)
        _handlers.append(activated_h)

        # ── Add toolbar button ────────────────────────────────────────────────
        _add_toolbar_button(ui)

        # ── Banner ────────────────────────────────────────────────────────────
        banner = (
            "═" * 64 + "\n"
            "  ADIE — Autonomous Design Integrity Engine  ✅  Active\n"
            f"  Scripts loaded : {len(_monitor._validation_fns)}\n"  # noqa: SLF001
            f"  Rules indexed  : {len(_monitor._rules_index)}\n"     # noqa: SLF001
            f"  Gemini AI      : {'✅ Ready' if api_key else '⚠  No API key — AI fixes disabled'}\n"
            f"  SDF check      : {'✅ Enabled' if CONFIG.get('sdf_enabled') else '⏸  Disabled'}\n"
            "  Listening  : documentSaved + documentActivated\n"
            "  Toolbar    : Solid tab → Scripts & Add-ins → ADIE Validate\n"
            "═" * 64
        )
        _console_write(ui, banner)
        log.info("ADIE add-in active.")

        # ── Immediate validation ──────────────────────────────────────────────
        _monitor.trigger()

    except Exception:
        msg = traceback.format_exc()
        log.error("run() fatal:\n%s", msg)
        if ui:
            try:
                ui.messageBox(f"ADIE failed to start:\n{msg}", "ADIE Error")
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# stop() — Fusion 360 add-in cleanup
# ─────────────────────────────────────────────────────────────────────────────

def stop(context):
    global _handlers, _monitor, _mitigation, _cmd_def

    if not _ADSK_AVAILABLE:
        return

    try:
        app = adsk.core.Application.get()

        # Remove document event handlers (first 2 in list)
        if app and len(_handlers) >= 2:
            try:
                app.documentSaved.remove(_handlers[0])
            except Exception:
                pass
            try:
                app.documentActivated.remove(_handlers[1])
            except Exception:
                pass

        # Remove toolbar button
        if _cmd_def:
            try:
                _remove_toolbar_button(app.userInterface)
            except Exception:
                pass

    except Exception:
        log.error("stop() cleanup:\n%s", traceback.format_exc())
    finally:
        _handlers.clear()
        _monitor    = None
        _mitigation = None
        _cmd_def    = None
        log.info("ADIE add-in stopped.")


# ─────────────────────────────────────────────────────────────────────────────
# Toolbar helpers
# ─────────────────────────────────────────────────────────────────────────────

def _add_toolbar_button(ui) -> None:
    global _cmd_def, _handlers

    try:
        # Remove stale definition if present
        existing = ui.commandDefinitions.itemById(CMD_ID)
        if existing:
            existing.deleteMe()

        cmd_def = ui.commandDefinitions.addButtonDefinition(
            CMD_ID, CMD_NAME, CMD_TOOLTIP
        )
        cmd_def.toolClipFilename = ""   # no custom icon for prototype

        created_h = _RunCommandCreatedHandler()
        cmd_def.commandCreated.add(created_h)
        _handlers.append(created_h)

        # Add to panel (gracefully skip if panel not found)
        panel = ui.allToolbarPanels.itemById(PANEL_ID)
        if panel:
            ctrl = panel.controls.addCommand(cmd_def)
            ctrl.isPromotedByDefault = False

        _cmd_def = cmd_def
        log.info("Toolbar button added: %s", CMD_NAME)

    except Exception:
        log.warning("Could not add toolbar button (non-fatal):\n%s", traceback.format_exc())


def _remove_toolbar_button(ui) -> None:
    try:
        panel = ui.allToolbarPanels.itemById(PANEL_ID)
        if panel:
            ctrl = panel.controls.itemById(CMD_ID)
            if ctrl:
                ctrl.deleteMe()
        defn = ui.commandDefinitions.itemById(CMD_ID)
        if defn:
            defn.deleteMe()
    except Exception:
        log.debug("Toolbar remove error:\n%s", traceback.format_exc())


def _console_write(ui, text: str | None) -> None:
    try:
        if ui is None:
            return
        p = ui.palettes.itemById("TextCommands")
        if p:
            p.isVisible = True
            if text:
                p.writeText(text)
    except Exception:
        pass
