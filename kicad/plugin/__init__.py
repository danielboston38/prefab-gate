"""Register the action with pcbnew when running inside KiCad.

pcbnew is absent outside KiCad, and the staging, runner and summary modules
must stay importable there so they can be tested. Only the registration is
skipped, and only when pcbnew itself is missing — a broken action.py still
raises, rather than disappearing behind a bare except.
"""
try:
    import pcbnew  # noqa: F401
except ImportError:
    pass
else:
    from .action import PrefabGateAction

    PrefabGateAction().register()
