"""Publish only the demo assets to the repository's gh-pages branch.

Requires GitHub CLI authentication with repository write access.
Run from the source checkout after validating and committing the demo.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
REMOTE = "https://github.com/rheeh/ttt.git"
ASSETS = ("index.html", "style.css", "app.js", "data.js", "favicon.svg")


def publish() -> None:
    for name in ASSETS:
        if not (ROOT / "demo" / name).is_file():
            raise SystemExit(f"Missing demo asset: {name}")
    for name in ("app.js", "data.js"):
        subprocess.run(["node", "--check", str(ROOT / "demo" / name)], check=True)
    source_commit = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], text=True).strip()
    with TemporaryDirectory(prefix="zhixing-pages-") as directory:
        target = Path(directory)

        def git(*args: str, capture: bool = False) -> subprocess.CompletedProcess:
            return subprocess.run(["git", "-c", "credential.helper=!gh auth git-credential", "-C", directory, *args],
                                  check=True, text=True, capture_output=capture)

        git("init", "--quiet", "-b", "gh-pages")
        branch = git("ls-remote", "--heads", REMOTE, "refs/heads/gh-pages", capture=True).stdout.strip()
        if branch:
            git("fetch", "--quiet", "--depth=1", REMOTE, "gh-pages")
            git("checkout", "--quiet", "-B", "gh-pages", "FETCH_HEAD")
        for name in ASSETS:
            shutil.copy2(ROOT / "demo" / name, target / name)
        (target / ".nojekyll").touch()
        git("add", *ASSETS, ".nojekyll")
        changed = subprocess.run(["git", "-C", directory, "diff", "--cached", "--quiet"]).returncode
        if changed == 0:
            print("Demo assets already match gh-pages.")
            return
        if changed != 1:
            raise SystemExit("Could not inspect staged demo assets.")
        git("commit", "--quiet", "-m", f"Publish static demo from {source_commit}")
        git("push", REMOTE, "HEAD:gh-pages")
        print("Published demo assets to gh-pages. Check the repository's Pages deployment status.")


if __name__ == "__main__":
    publish()
