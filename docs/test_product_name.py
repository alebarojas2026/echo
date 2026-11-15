"""The product is called Echo. The old name must not come back in anything a person reads.

Internal names (the radio-sight-* units, RADIO_SIGHT_* variables, folder names) are written
with a hyphen or underscore and are not matched here. The few places that must keep the old
words, because they match what is already installed on the devices, are listed below.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# (file, text on the line) that may keep the old name, and why.
ALLOWED = (
    # The rule itself: names the old name so workers know it.
    ("AGENTS.md", '"Radio Sight" is the old name'),
    # Finds an llm.service installed by an older README on the board; that file says this.
    ("board/deploy.sh", 'grep -qs "Radio Sight narrator model"'),
    ("board/tests/test_deploy.py", "Description=Radio Sight narrator model"),
    # Other docs tests that keep the old name out of their page.
    ("docs/test_architecture_doc.py", '"radio sight"'),
    ("docs/test_network_doc.py", '"radio sight"'),
    # This file.
    ("docs/test_product_name.py", ""),
)


def tracked_hits(pattern):
    out = subprocess.run(
        ["git", "grep", "-I", "-n", "-i", "-F", pattern],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode not in (0, 1):
        raise RuntimeError(out.stderr)
    return [line for line in out.stdout.splitlines() if line]


def allowed(hit):
    path, _, rest = hit.partition(":")
    text = rest.partition(":")[2]
    return any(path == file and part in text for file, part in ALLOWED)


@unittest.skipUnless(shutil.which("git") and (ROOT / ".git").exists(), "needs a git checkout")
class ProductNameTest(unittest.TestCase):
    def test_old_name_is_not_back(self):
        left = [hit for hit in tracked_hits("Radio Sight") if not allowed(hit)]
        self.assertEqual(left, [], "the product is called Echo; the old name came back")

    def test_allow_list_is_still_needed(self):
        hits = tracked_hits("Radio Sight")
        for file, part in ALLOWED:
            if file == "docs/test_product_name.py":
                continue
            self.assertTrue(any(hit.startswith(file + ":") and part in hit for hit in hits),
                            f"{file} no longer needs its exception; drop it from ALLOWED")


class SchemaIdTest(unittest.TestCase):
    def test_schema_ids_use_the_echo_repo(self):
        for schema in sorted((ROOT / "contracts" / "schemas").glob("*.json")):
            sid = json.loads(schema.read_text(encoding="utf-8")).get("$id", "")
            self.assertEqual(
                sid, f"https://github.com/alebarojas2026/echo/contracts/schemas/{schema.name}", schema.name)


if __name__ == "__main__":
    unittest.main()
