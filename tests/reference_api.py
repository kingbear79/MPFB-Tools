"""Run with Python 3.11 or newer. This test never contacts the API."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mpfb_tools"))
import cloud_api as api


def recipe(kind, **changes):
    preset = {"H": "H10", "B": "B09", "A": "A02"}[kind]
    return {
        "name": preset, "style": preset, "color": "ash_brown", "certainty": "medium",
        "visible": True, "notes": "Profil im Hauptbild",
        **{key: value[1] for key, value in api.PARAMETERS[kind].items()},
        **changes,
    }


class ReferenceAnalysis(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.main = self.root / "main.jpg"
        self.left = self.root / "left.jpg"
        self.right = self.root / "right.jpg"
        for path in (self.main, self.left, self.right):
            path.write_bytes(path.stem.encode())
        self.calls = []
        self.prepared = []

    def prepare(self, path, main):
        self.prepared.append((path, main))
        return f"data:image/jpeg;base64,{path.stem}"

    def transport(self, payload, key):
        self.calls.append((payload, key))
        kinds = payload["text"]["format"]["schema"]["required"]
        result = json.dumps({kind: recipe(kind) for kind in kinds})
        return {"status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": result}]}],
                "usage": {"input_tokens": 361, "output_tokens": 211}}

    def analyze(self, parts, paths=None, *, transport=None, online=True, key="test", refresh=False):
        return api.analyze(paths or [self.main, self.left, self.right], parts, api.MODEL, self.root / "cache",
                           key, online, self.prepare, transport or self.transport, refresh)

    def test_one_request_deduplication_and_partial_cache(self):
        result, missing, usage = self.analyze("HB", [self.main, self.left, self.right, self.main])
        self.assertEqual(set(result), {"H", "B"})
        self.assertEqual(missing, ("H", "B"))
        self.assertEqual(usage["input_tokens"], 361)
        self.assertEqual(len(self.calls), 1)
        payload, _ = self.calls[0]
        self.assertFalse(payload["store"])
        schema = payload["text"]["format"]["schema"]
        self.assertEqual(schema["required"], ["H", "B"])
        self.assertFalse(schema["additionalProperties"])
        inputs = [part for part in payload["input"][0]["content"] if part["type"] == "input_image"]
        self.assertEqual([part["detail"] for part in inputs], ["high", "low", "low"])
        self.assertEqual(self.prepared[0], (self.main, True))

        _, missing, usage = self.analyze("H", [self.main, self.right, self.left], online=False, key="")
        self.assertEqual(missing, ())
        self.assertIsNone(usage)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.prepared), 3)

        result, missing, _ = self.analyze("HBA")
        self.assertEqual(set(result), {"H", "B", "A"})
        self.assertEqual(missing, ("A",))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[-1][0]["text"]["format"]["schema"]["required"], ["A"])

    def test_new_main_content_and_explicit_refresh(self):
        self.analyze("A")
        self.analyze("A")
        self.assertEqual(len(self.calls), 1)
        self.analyze("A", [self.left, self.main, self.right])
        self.assertEqual(len(self.calls), 2)
        self.main.write_bytes(b"new photo")
        self.analyze("A")
        self.analyze("A", refresh=True)
        self.assertEqual(len(self.calls), 4)

    def test_refusal_is_not_saved_and_has_no_retry(self):
        count = []

        def refused(_payload, _key):
            count.append(True)
            return {"status": "completed",
                    "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "test"}]}]}

        with self.assertRaisesRegex(RuntimeError, "nicht analysieren"):
            self.analyze("H", transport=refused)
        self.assertEqual(len(count), 1)
        self.assertFalse((self.root / "cache").exists())

    def test_only_valid_parameters(self):
        for change in ({"style": "B01"}, {"color": "invalid"}, {"length": float("nan")},
                       {"volume": False}, {"sides": 9}, {"notes": {"unexpected": True}}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    api.clean_recipe("H", recipe("H", **change))


if __name__ == "__main__":
    unittest.main()
