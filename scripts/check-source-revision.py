"""Prevent a delayed workflow from replacing a newer release."""
import json
import os
import re
import urllib.request


def main():
    repository = os.environ["SOURCE_REPOSITORY"]
    source_sha = os.environ["SOURCE_SHA"]
    if not re.fullmatch(r"KairosApplication/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Repositorio de origem invalido.")
    if not re.fullmatch(r"[a-f0-9]{40}", source_sha):
        raise ValueError("SHA invalido.")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/commits/main",
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        latest = json.load(response)["sha"]
    if source_sha != latest:
        raise ValueError("Este commit foi superado na main. Execute o deploy do commit mais recente.")
    print("O commit continua sendo a revisao atual da main.")


if __name__ == "__main__":
    main()
