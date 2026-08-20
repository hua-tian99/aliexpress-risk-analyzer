# -*- coding: utf-8 -*-
"""Category mapping loader — loads and queries AliExpress category ID -> name/path,
and the full 4-level category tree for AI context and keyword search."""
import os
import pandas as pd

# Default paths relative to project
_DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "category_mapping.xlsx")
_DEFAULT_TREE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "category_tree.xlsx")

# Module-level cache for ID mapping
_category_df = None
_category_dict = None  # {id: {"path": str, "name": str}}

# Module-level cache for full tree
_full_tree_cache = None


# ============================================================
#  Existing API — ID → path resolution (unchanged)
# ============================================================

def load_categories(path=None):
    """Load category mapping from Excel. Returns {category_id: {path, name}}."""
    global _category_df, _category_dict
    if path is None:
        path = _DEFAULT_PATH

    if _category_dict is not None:
        return _category_dict

    df = pd.read_excel(path, dtype=str)
    _category_df = df

    # Column names (may have encoding variations)
    cols = list(df.columns)
    id_col = cols[0]
    path_col = cols[1]
    name_col = cols[2]

    _category_dict = {}
    for _, row in df.iterrows():
        cat_id = str(row[id_col]).strip()
        path = str(row[path_col]).strip() if pd.notna(row[path_col]) else ""
        name = str(row[name_col]).strip() if pd.notna(row[name_col]) else ""
        _category_dict[cat_id] = {"path": path, "name": name}

    return _category_dict


def get_category(category_id):
    """Get category info by ID. Returns {path, name} or None."""
    cats = load_categories()
    return cats.get(str(category_id).strip())


def get_category_name(category_id):
    """Get the human-readable category path + name for a category ID."""
    info = get_category(category_id)
    if info:
        name = info["name"]
        path = info["path"]
        return f"{path} -> {name}" if path else name
    return f"Unknown category (ID: {category_id})"


def get_all_categories():
    """Return all categories as {id: {path, name}}."""
    return load_categories()


def category_summary_for_prompt(max_cats=200):
    """Generate a compact category summary for inclusion in AI prompt.
    Returns a string like 'ID: name (path)' lines.
    """
    cats = load_categories()
    lines = []
    for cat_id, info in list(cats.items())[:max_cats]:
        lines.append(f"{cat_id}: {info['name']} ({info['path']})")
    return "\n".join(lines)


# ============================================================
#  New API — Full 4-level category tree
# ============================================================

def _build_ngram_index(flat_paths):
    """Build an inverted index of n-grams to path indices for keyword search.

    For Chinese text, character-level unigrams and bigrams work well without
    a dedicated segmenter. Each n-gram maps to a set of path indices.
    """
    index = {}  # {ngram: set(path_idx)}
    for idx, path in enumerate(flat_paths):
        # Extract all level names from the path
        levels = [s.strip() for s in path.split(">")]
        # Collect n-grams from each level name and the full path
        texts = levels + [path]
        for text in texts:
            if not text:
                continue
            # Unigrams (single char)
            for ch in text:
                if ch and ch not in (" ", "/", "&", "（", "）", "(", ")", "-", "_"):
                    idx_set = index.setdefault(ch, set())
                    idx_set.add(idx)
            # Bigrams (2-char)
            for i in range(len(text) - 1):
                bigram = text[i:i+2]
                if bigram.strip() and "/" not in bigram:
                    idx_set = index.setdefault(bigram, set())
                    idx_set.add(idx)
    return index


def load_full_tree(path=None):
    """Load the full 4-level category tree.

    Returns a dict with:
        tree:       nested {L1: {L2: {L3: [L4, ...]}}}
        flat_paths: ["L1 > L2 > L3 > L4", ...]
        l1_list:    ["家具", "家居用品", ...]
        l1_l2_map:  {L1: [L2, ...]}
        ngram_index:{ngram: set(path_idx)}  — for keyword search
    """
    global _full_tree_cache
    if _full_tree_cache is not None:
        return _full_tree_cache

    if path is None:
        path = _DEFAULT_TREE_PATH

    df = pd.read_excel(path, header=None, dtype=str)
    # Columns: A=L1, B=L2, C=L3, D=L4, E=None, F=index
    # Keep only first 4 columns
    df = df.iloc[:, :4]
    df = df.fillna("")

    tree = {}
    l1_l2_map = {}
    flat_paths = []

    for _, row in df.iterrows():
        l1 = str(row.iloc[0]).strip()
        l2 = str(row.iloc[1]).strip()
        l3 = str(row.iloc[2]).strip()
        l4 = str(row.iloc[3]).strip()

        if not l1:
            continue

        # Build path string
        parts = [p for p in (l1, l2, l3, l4) if p]
        path_str = " > ".join(parts)
        flat_paths.append(path_str)

        # Build tree
        if l1 not in tree:
            tree[l1] = {}
        if l2 not in tree[l1]:
            tree[l1][l2] = {}
        if l3 not in tree[l1][l2]:
            tree[l1][l2][l3] = []
        if l4 and l4 not in tree[l1][l2][l3]:
            tree[l1][l2][l3].append(l4)

    # L1 list (sorted)
    l1_list = sorted(tree.keys())

    # L1→L2 map
    for l1_name in tree:
        l1_l2_map[l1_name] = sorted(tree[l1_name].keys())

    # Build n-gram index
    ngram_index = _build_ngram_index(flat_paths)

    _full_tree_cache = {
        "tree": tree,
        "flat_paths": flat_paths,
        "l1_list": l1_list,
        "l1_l2_map": l1_l2_map,
        "ngram_index": ngram_index,
    }
    return _full_tree_cache


def search_categories(query_text, top_n=5, l1_filter=None):
    """Search the category tree for paths matching the query text.

    Uses character n-gram matching — no NLP segmenter needed for Chinese.

    Args:
        query_text: search keywords
        top_n: max results
        l1_filter: optional L1 category name to restrict search scope

    Returns:
        list of (path: str, score: float) sorted by relevance, best first.
    """
    if not query_text or not query_text.strip():
        return []

    tree_data = load_full_tree()
    flat_paths = tree_data["flat_paths"]
    ngram_index = tree_data["ngram_index"]

    # Extract n-grams from query
    query_ngrams = set()
    text = query_text.strip()
    for ch in text:
        if ch and ch not in (" ", "/", "&", "（", "）", "(", ")", "-", "_", ".", ","):
            query_ngrams.add(ch)
    for i in range(len(text) - 1):
        bigram = text[i:i+2]
        if bigram.strip() and "/" not in bigram:
            query_ngrams.add(bigram)

    if not query_ngrams:
        return []

    # Score each candidate path by n-gram hit count
    candidate_indices = set()
    for ng in query_ngrams:
        if ng in ngram_index:
            candidate_indices.update(ngram_index[ng])

    if not candidate_indices:
        return []

    scores = []
    for idx in candidate_indices:
        path = flat_paths[idx]
        # L1 filter: skip paths not in the target L1
        if l1_filter:
            path_l1 = path.split(" > ")[0] if " > " in path else ""
            if path_l1 != l1_filter:
                continue
        # Count how many query n-grams appear in this path
        hit_count = 0
        path_text = path.replace(" > ", " ")
        for ng in query_ngrams:
            if ng in path_text:
                hit_count += 1
        score = hit_count / len(query_ngrams)
        if score > 0:
            scores.append((path, round(score, 3)))

    scores.sort(key=lambda x: -x[1])
    return scores[:top_n]


def find_closest_path(free_text, top_n=3, l1_filter=None):
    """Map free-form text to the closest real category path(s).

    Args:
        free_text: text to match (e.g. AI output, product title)
        top_n: max results
        l1_filter: optional L1 category name to restrict search scope

    Returns:
        list of (path: str, score: float), or empty list if no match.
    """
    if not free_text or not free_text.strip():
        return []

    # First try: direct n-gram search
    results = search_categories(free_text, top_n=top_n, l1_filter=l1_filter)
    if results and results[0][1] >= 0.3:
        return results

    # Second try: tokenize free text and search each token
    # Break on common separators
    import re
    tokens = re.split(r"[>,/\->\s]+", free_text)
    tokens = [t.strip() for t in tokens if t.strip() and len(t.strip()) > 1]

    if not tokens:
        return results

    # Search each token and aggregate
    tree_data = load_full_tree()
    flat_paths = tree_data["flat_paths"]
    all_hits = {}

    for token in tokens:
        token_results = search_categories(token, top_n=10, l1_filter=l1_filter)
        for path, score in token_results:
            all_hits[path] = all_hits.get(path, 0) + score

    # Sort by aggregated score
    aggregated = sorted(all_hits.items(), key=lambda x: -x[1])
    return aggregated[:top_n]


def is_valid_path(path):
    """Check if a path string exists in the full category tree."""
    if not path:
        return False
    tree_data = load_full_tree()
    return path in tree_data["flat_paths"]


def match_category_tiered(l4_name, l3_name, l1_filter):
    """Check if a category L4 or L3 name exists in the constrained L1 subtree.

    Algorithm (seller's chosen category verification):
    1. Check if l4_name exists as an L4 terminal in the L1 subtree → return full path
    2. If not, check if l3_name exists as an L3 in the L1 subtree → return L1>L2>L3 path
    3. If neither, return None

    Args:
        l4_name: seller's chosen L4 category name (terminal)
        l3_name: seller's chosen L3 category name
        l1_filter: L1 category name to constrain the search

    Returns:
        (path: str, level: str) or None
        level is "L4" or "L3" indicating which level matched.
    """
    if not l1_filter:
        return None

    tree_data = load_full_tree()
    tree = tree_data["tree"]

    if l1_filter not in tree:
        return None

    subtree = tree[l1_filter]

    # Round 1: search for exact L4 name in the L1 subtree
    if l4_name:
        for l2 in subtree:
            for l3 in subtree[l2]:
                if l4_name in subtree[l2][l3]:
                    return (f"{l1_filter} > {l2} > {l3} > {l4_name}", "L4")

    # Round 2: search for exact L3 name in the L1 subtree
    if l3_name:
        for l2 in subtree:
            if l3_name in subtree[l2]:
                return (f"{l1_filter} > {l2} > {l3_name}", "L3")

    return None


def format_tree_for_prompt(l1_filter=None):
    """Format the category tree for injection into an AI prompt.

    Args:
        l1_filter: optional L1 category name. If provided, only show that L1's
                   full subtree (L1→L2→L3→L4). If None, show all L1+L2.

    Returns a compact string. When filtered, shows deeper tree levels.
    """
    tree_data = load_full_tree()
    tree = tree_data["tree"]
    l1_l2_map = tree_data["l1_l2_map"]

    if l1_filter and l1_filter in tree:
        # Show full subtree for the specific L1
        lines = [f"Category Tree — [{l1_filter}] (Level 1 → Level 2 → Level 3 → Level 4):", ""]
        l1_subtree = tree[l1_filter]
        for l2 in sorted(l1_subtree.keys()):
            lines.append(f"  ├─ {l2}")
            l2_subtree = l1_subtree[l2]
            for l3 in sorted(l2_subtree.keys()):
                l4_list = l2_subtree[l3]
                if l4_list:
                    l4_str = ", ".join(l4_list[:5])
                    if len(l4_list) > 5:
                        l4_str += f" ... (+{len(l4_list) - 5} more)"
                    lines.append(f"  │   └─ {l3} → [{l4_str}]")
                else:
                    lines.append(f"  │   └─ {l3}")
        return "\n".join(lines)

    # Default: show all L1 + L2
    lines = ["AliExpress Complete Category Tree (Level 1 → Level 2):", ""]
    for l1 in tree_data["l1_list"]:
        lines.append(f"  [{l1}]")
        for l2 in l1_l2_map.get(l1, []):
            lines.append(f"    ├─ {l2}")
        lines.append("")

    return "\n".join(lines)
