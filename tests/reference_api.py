"""Run with Python 3.11 or newer. This test never contacts the API."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mpfb_tools"))
import cloud_api as api


def recipe(kind, **changes):
    fields = {} if kind == "H" else {"style": {"B": "B09", "A": "A02"}[kind]}
    return {
        "name": "Testentwurf", "color": "ash_brown", "certainty": "medium",
        "visible": True, "notes": "Profil im Hauptbild",
        **fields,
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
        return f"data:image/jpeg;base64,{path.stem}", 1.0

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
        hair_fields = schema["properties"]["H"]["properties"]
        self.assertNotIn("style", hair_fields)
        self.assertIn("nape_curl", hair_fields)
        self.assertIn("nape_density", hair_fields)
        self.assertIn("style", schema["properties"]["B"]["properties"])
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
        for change in ({"color": "invalid"}, {"length": float("nan")},
                       {"volume": False}, {"fade": 9}, {"notes": {"unexpected": True}}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    api.clean_recipe("H", recipe("H", **change))

    def test_existing_facial_hair_cache_survives_hair_cut_upgrade(self):
        photos = api.references([self.main, self.left, self.right])
        photos[1:] = sorted(photos[1:], key=lambda item: item[1])
        old = api.cache_path(self.root / "cache", api.MODEL, photos, protocol=1)
        api.write_cache(old, {"B": recipe("B"), "H": {"style": "H04"}})
        result, missing, _ = self.analyze("HB")
        self.assertEqual(missing, ("H",))
        self.assertEqual(result["B"]["style"], "B09")
        self.assertNotIn("style", result["H"])

    def test_visible_profile_landmarks_override_rough_estimates(self):
        item = recipe("H", profile={
            "view": 2, "ear_top": 400, "ear_lobe": 550, "ear_back": 460,
            "fringe_tip": 355, "nape_tip": 700, "fade_mid_top": 355, "fade_mid_back": 490,
            "fade_band_top": 335, "fade_band_bottom": 380, "crown_curl_span": 30,
            "nape_curl_span": 36, "lock_span": 20,
        })
        response = {"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps({"H": item})}]},
        ]}
        photos = [("main", 1.), ("profile", 1.5)]
        haircut = api.parse_response(response, ("H",), photos)["H"]
        self.assertEqual(haircut["fringe_clearance"], .30)
        self.assertEqual(haircut["nape_drop"], 1.)
        self.assertEqual(haircut["fade_behind"], .30)
        self.assertEqual(haircut["fade_blend"], .30)
        self.assertEqual(haircut["curl_size"], .60)
        self.assertEqual(haircut["nape_curl_size"], .72)
        self.assertEqual(haircut["lock_width"], 8.)


if __name__ == "__main__":
    unittest.main()
