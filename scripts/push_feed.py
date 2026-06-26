# -*- coding: utf-8 -*-
"""docs/feed.xml'i GitHub deposuna push eden İSKELET (PyGithub).

DİKKAT: Repo + token henüz hazır DEĞİL. Bu script şu an ÇAĞRILMAMALI;
gerçek değerler bağlanınca aktive edilecek. main() guard ile korunuyor.

Ortam değişkenleri (sonra .env'den):
  GH_TOKEN   : repo push yetkili PAT
  GH_REPO    : 'org/repo'
  GH_BRANCH  : varsayılan 'main'
  FEED_PATH  : repo içi hedef yol, vars. 'docs/feed.xml'
                (GitHub Pages "deploy from branch" yalnızca kök ya da /docs servis eder)
"""
from __future__ import annotations

import os


def push_feed(local_path: str = "docs/feed.xml",
              *, token: str | None = None, repo: str | None = None,
              branch: str | None = None, dest_path: str | None = None,
              commit_message: str = "chore: update RG feed") -> str:
    """feed.xml'i repoya yükle (create/update). short SHA döner.

    Henüz çağrılmamalı — repo/token bağlanınca kullanılacak.
    """
    from github import Github, InputGitTreeElement  # noqa: F401  (PyGithub)

    token = token or os.environ.get("GH_TOKEN")
    repo = repo or os.environ.get("GH_REPO")
    branch = branch or os.environ.get("GH_BRANCH", "main")
    dest_path = dest_path or os.environ.get("FEED_PATH", "docs/feed.xml")
    if not token or not repo:
        raise RuntimeError("GH_TOKEN / GH_REPO tanımlı değil — repo henüz hazır değil.")

    with open(local_path, encoding="utf-8") as fh:
        content = fh.read()

    gh = Github(token)
    gh_repo = gh.get_repo(repo)
    try:
        existing = gh_repo.get_contents(dest_path, ref=branch)
        res = gh_repo.update_file(dest_path, commit_message, content, existing.sha, branch=branch)
    except Exception:  # dosya yoksa oluştur
        res = gh_repo.create_file(dest_path, commit_message, content, branch=branch)
    return res["commit"].sha[:10]


def main() -> int:
    # GÜVENLİK GUARD: repo/token bağlanmadan push yapma.
    if os.environ.get("RG_FEED_PUSH_ENABLED") != "1":
        print("push devre dışı: RG_FEED_PUSH_ENABLED=1 değil (repo/token henüz hazır değil).")
        return 0
    sha = push_feed()
    print("pushed:", sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
