"""The disk ledger: sizes like du, Ollama manifests, the v3 split and the plan's headroom."""
import json
import os
import shutil
import tempfile
import unittest

from tests import _paths  # noqa: F401
from tools import disk_ledger as dl

MB = 1024 * 1024


def write(path, n):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(os.urandom(n))  # real data: a sparse file would take no blocks


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wm-ledger-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tree_size_counts_hard_links_once_and_skips_symlinks(self):
        d = os.path.join(self.tmp, "t")
        write(os.path.join(d, "a.bin"), 2 * MB)
        write(os.path.join(d, "sub", "b.bin"), MB)
        os.link(os.path.join(d, "a.bin"), os.path.join(d, "sub", "a-again.bin"))
        os.symlink(os.path.join(d, "a.bin"), os.path.join(d, "link.bin"))
        size, files, errors = dl.tree_size(d)
        self.assertEqual(errors, 0)
        self.assertEqual(files, 3)  # a.bin, b.bin, the symlink itself; the hard link is the same file
        self.assertGreaterEqual(size, 3 * MB)
        self.assertLess(size, 3 * MB + 256 * 1024)

    def test_manifest_names(self):
        self.assertEqual(dl.manifest_name("registry.ollama.ai/library/qwen3/8b"), "qwen3:8b")
        self.assertEqual(dl.manifest_name("ollama.com/library/hydra/1.0"), "hydra:1.0")
        self.assertEqual(dl.manifest_name("registry.ollama.ai/x/z-image-turbo/latest"), "x/z-image-turbo:latest")
        self.assertEqual(dl.manifest_name("hf.co/someone/Model-GGUF/Q5_K_M"), "hf.co/someone/Model-GGUF:Q5_K_M")

    def test_ollama_models_own_shared_and_manifest_lists(self):
        m = os.path.join(self.tmp, "models")

        def manifest(rel, layers, base="manifests"):
            path = os.path.join(m, base, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump({"layers": [{"digest": d, "size": s} for d, s in layers]}, f)

        manifest("registry.ollama.ai/library/a/1", [("sha256:big", 5_000_000_000), ("sha256:lic", 100)])
        manifest("registry.ollama.ai/library/b/1", [("sha256:big", 5_000_000_000), ("sha256:t", 50)])
        manifest("registry.ollama.ai/library/c/1", [("sha256:own", 2_000_000_000), ("sha256:lic", 100)])
        # A manifest list (one model in two runner formats), as manifests-v2 stores deepseek-r1:70b.
        os.makedirs(os.path.join(m, "blobs"))
        with open(os.path.join(m, "blobs", "sha256-sub1"), "w") as f:
            json.dump({"layers": [{"digest": "sha256:v1", "size": 3_000_000_000}]}, f)
        with open(os.path.join(m, "blobs", "sha256-sub2"), "w") as f:
            json.dump({"layers": [{"digest": "sha256:v2", "size": 3_000_000_000}]}, f)
        path = os.path.join(m, "manifests-v2", "ollama.com", "library", "d", "1")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            json.dump({"manifests": [{"digest": "sha256:sub1"}, {"digest": "sha256:sub2"}]}, f)
        got = {x["name"]: x for x in dl.ollama_models(m)["models"]}
        self.assertEqual(got["a:1"]["own"], 0)  # the licence is shared with c, the blob with b
        self.assertEqual(got["a:1"]["shared_with"], ["b:1"])  # c shares only a 100-byte licence
        self.assertEqual(got["c:1"]["own"], 2_000_000_000)
        self.assertEqual(got["d:1"]["bytes"], 6_000_000_000)

    def test_helper_train_splits_v3(self):
        root = os.path.join(self.tmp, "helper-train")
        write(os.path.join(root, "v1", "helper-bf16.gguf"), 2 * MB)
        v3 = os.path.join(root, "v3")
        write(os.path.join(v3, "helper-q5_k_m.gguf"), 2 * MB)
        write(os.path.join(v3, "adapters", "adapters.safetensors"), 2 * MB)
        write(os.path.join(v3, "Modelfile.q5_k_m"), 100)
        write(os.path.join(v3, "helper-bf16.gguf"), 2 * MB)
        write(os.path.join(v3, "fused", "model.safetensors"), 2 * MB)
        write(os.path.join(v3, "run.log"), 1000)
        ht = dl.helper_train(root)
        self.assertEqual([e["name"] for e in ht["entries"]], ["v1", "v3"])
        self.assertEqual(sorted(i["name"] for i in ht["v3"]["leftover_items"]), ["fused", "helper-bf16.gguf"])
        self.assertGreaterEqual(ht["v3"]["keep"], 4 * MB)

    def test_plan_needs(self):
        rows = {r["base"]: r for r in dl.plan_needs(143.0, v1v2=39.4, v3_left=26.2)}
        g, q = rows["gemma-4-12b"], rows["qwen3-14b"]
        self.assertEqual(g["peak"], 89.3)   # 17.3 baselines + 3 x 24
        self.assertEqual(q["peak"], 105.8)  # 17.3 + 3 x 29.5
        self.assertEqual(g["headroom_now"], 53.7)
        self.assertEqual(q["headroom_without_v1_v2"], 76.6)
        self.assertEqual(q["headroom_also_slim_v3"], 102.8)

    def test_render_has_every_section(self):
        L = {"disk": {"path": "/x", "free": 143e9, "total": 4e12},
             "helper_train": dl.helper_train(os.path.join(self.tmp, "none")),
             "ollama": dl.ollama_models(os.path.join(self.tmp, "none")),
             "plan": {"estimates": dl.PLAN, "needs": dl.plan_needs(143.0)}}
        out = dl.render(L)
        for want in ("143.0 GB free", "(not there)", "## What the plan's training needs", "| gemma-4-12b"):
            self.assertIn(want, out)


if __name__ == "__main__":
    unittest.main()
