# -*- coding: utf-8 -*-
"""docs/feed.xml'i GitHub deposuna push eder (PyGithub).

Ortam değişkenleri (.env'den; tek standart isim seti):
  GITHUB_TOKEN  : repo push yetkili PAT
  GITHUB_REPO   : 'org/repo' (örn. saglikyz/rg-compliance-mevzuat-takip)
  GITHUB_BRANCH : varsayılan 'main'
  FEED_URL      : yayımlanan feed URL'i (bilgi amaçlı; push hedefi DEĞİL)

Hedef yol repo içinde sabit 'docs/feed.xml' — GitHub Pages "deploy from branch"
yalnızca kök ya da /docs servis eder.
"""
from __future__ import annotations

import os


def push_feed(local_path: str = "docs/feed.xml",
              *, token: str | None = None, repo: str | None = None,
              branch: str | None = None, dest_path: str = "docs/feed.xml",
              commit_message: str = "chore: update RG feed") -> str:
    """feed.xml'i repoya yükle (create/update). short commit SHA döner."""
    from github import Github  # PyGithub

    token = token or os.environ.get("GITHUB_TOKEN")
    repo = repo or os.environ.get("GITHUB_REPO")
    branch = branch or os.environ.get("GITHUB_BRANCH", "main")
    if not token or not repo:
        raise RuntimeError("GITHUB_TOKEN / GITHUB_REPO tanımlı değil (.env kontrol et).")

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
    # GÜVENLİK GUARD: kazara push'u önlemek için açık onay.
    if os.environ.get("RG_FEED_PUSH_ENABLED") != "1":
        print("push devre dışı: RG_FEED_PUSH_ENABLED=1 değil.")
        return 0
    sha = push_feed()
    print("pushed:", sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
