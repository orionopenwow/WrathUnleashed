import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import remove_listed as R


class T(unittest.TestCase):
    def test_removes_only_tracked_repo_files(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "a", "b"))
        for p in ("a/b/x.png", "keep.txt", "untracked.txt"):
            open(os.path.join(root, p), "w").write("1")
        outside = tempfile.NamedTemporaryFile(delete=False).name
        lst = os.path.join(root, "REMOVE.txt")
        open(lst, "w").write(f"# c\na/b/x.png\n../x\n{outside}\nuntracked.txt\nmissing.txt\na\n")
        lines = []
        R.remove(root, lst, lines.append, is_tracked=lambda r, rel: rel != "untracked.txt")
        self.assertFalse(os.path.exists(os.path.join(root, "a")))          # file and its empty folders
        self.assertTrue(os.path.exists(os.path.join(root, "keep.txt")))
        self.assertTrue(os.path.exists(os.path.join(root, "untracked.txt")))
        self.assertTrue(os.path.exists(outside))
        self.assertIn("REMOVE OK: 1 removed", lines[-1])


if __name__ == "__main__":
    unittest.main()
