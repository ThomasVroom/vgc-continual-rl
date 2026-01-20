"""
Data scraping module for VGC-Bench.

Downloads Pokemon data (abilities, items, moves) from Pokemon Showdown and
creates semantic embeddings of their descriptions using sentence transformers.
These embeddings are used as features for the policy network.
"""

import json
import os
import re
import warnings

import requests
from sentence_transformers import SentenceTransformer
from sklearn.decomposition import PCA


def update_desc_embeddings(url: str, file: str, extras: dict[str, dict[str, str]] = {}):
    """
    Download Pokemon data and create PCA-reduced semantic embeddings.

    Fetches a data file from Pokemon Showdown, extracts short descriptions,
    encodes them using a sentence transformer, reduces dimensions with PCA,
    and saves the embeddings to a JSON file.

    Args:
        url: Base URL for the Pokemon Showdown data files.
        file: Filename to download (e.g., "abilities.js").
        extras: Additional entries to include with their descriptions.
    """
    response = requests.get(f"{url}/{file}")
    if ".json" in file:
        json_text = response.text
    else:
        js_text = response.text
        i = js_text.index("{")
        js_literal = js_text[i:-1]
        json_text = re.sub(r"([{,])([a-zA-Z0-9_]+)(:)", r'\1"\2"\3', js_literal)
        file += "on"
    dex = {
        k: v["shortDesc"]
        for k, v in {**extras, **json.loads(json_text)}.items()
        if "shortDesc" in v
    }
    warnings.simplefilter(action="ignore", category=FutureWarning)
    transformer = SentenceTransformer("paraphrase-mpnet-base-v2")
    pca = PCA(100)
    embeddings = transformer.encode(list(dex.values()))
    reduced_embeddings = pca.fit_transform(embeddings).tolist()
    with open(f"data/{file}", "w") as f:
        json.dump(dict(zip(dex.keys(), reduced_embeddings)), f)


if __name__ == "__main__":
    if not os.path.exists("data"):
        os.mkdir("data")
    update_desc_embeddings(
        "https://play.pokemonshowdown.com/data",
        "abilities.js",
        extras={"null": {"shortDesc": "null"}, "": {"shortDesc": "empty"}},
    )
    update_desc_embeddings(
        "https://play.pokemonshowdown.com/data",
        "items.js",
        extras={
            "null": {"shortDesc": "null"},
            "": {"shortDesc": "empty"},
            "unknown_item": {"shortDesc": "unknown item"},
        },
    )
    update_desc_embeddings(
        "https://play.pokemonshowdown.com/data",
        "moves.js",
        extras={"no move": {"shortDesc": "no move"}},
    )
