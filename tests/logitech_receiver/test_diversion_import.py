import os
import subprocess
import sys

import logitech_receiver


def test_import_under_wayland_does_not_warn(tmp_path):
    """The rules engine is imported at startup (even by `plasmaard --version`). On Wayland it notes
    that rules cannot read modifier keys; that is informational, not a warning in the journal."""
    lib_dir = os.path.dirname(os.path.dirname(logitech_receiver.__file__))
    env = dict(
        os.environ,
        WAYLAND_DISPLAY="wayland-0",
        XDG_CONFIG_HOME=str(tmp_path),  # don't read the user's rules.yaml
        PYTHONPATH=os.pathsep.join(p for p in (lib_dir, os.environ.get("PYTHONPATH")) if p),
    )
    code = (
        "import logging\n"
        "logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(message)s')\n"
        "import logitech_receiver.diversion\n"
    )

    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60, check=True)

    lines = [line for line in result.stderr.splitlines() if line.startswith(("WARNING", "INFO"))]
    assert "INFO logitech_receiver.diversion rules cannot access modifier keys in Wayland" in lines
    assert not [line for line in lines if line.startswith("WARNING logitech_receiver.diversion")]
