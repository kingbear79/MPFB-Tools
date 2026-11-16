"""Check that a long key reaches the analysis worker unchanged."""
import json
import os
from pathlib import Path
import stat
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mpfb_tools import cloud_ui, cloud_worker, library_ui


with TemporaryDirectory() as folder:
    root = Path(folder)
    path = root / "config" / "cloud-key"
    test_key = "sk-proj-" + "a" * 153 + "end"
    wm = SimpleNamespace(clipboard=f" {test_key}\n")
    context = SimpleNamespace(window_manager=wm)
    operator = SimpleNamespace(report=lambda *args: None)
    save = library_ui.MPFBTOOLS_OT_cloud_key_from_clipboard.execute

    with patch.object(library_ui, "cloud_key_file", return_value=path), patch.dict(os.environ, OPENAI_API_KEY=""):
        assert save(operator, context) == {"FINISHED"}
        assert path.read_bytes() == (test_key + "\n").encode()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert cloud_ui.read_key() == test_key
        wm.clipboard = "sk-proj-...redacted"
        assert save(operator, context) == {"CANCELLED"}
        assert cloud_ui.read_key() == test_key

        request, result = root / "request.json", root / "result.json"
        request.write_text("{}", encoding="utf-8")
        with patch.dict(os.environ, MPFB_REFERENCE_KEY=cloud_ui.read_key()):
            with patch.object(cloud_worker, "run", return_value={"ok": True}) as run:
                cloud_worker.main(str(request), str(result))
                run.assert_called_once_with({}, root, test_key)
        assert json.loads(result.read_text(encoding="utf-8")) == {"ok": True}
print("PASS full clipboard key reaches worker", flush=True)
