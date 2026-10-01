"""Deterministic search over a world's accepted pages, for any site."""
import re

STOPWORDS = {'a', 'an', 'the', 'of', 'in', 'from', 'and', 'is', 'at', 'to'}


def search_corpus(world, query, limit):
    """AND-term search, explicitly scoped to the captured corpus.

    No task-specific queries, upstream rankings or unmodified source snippets.
    This deliberately does not claim any site's complete search syntax.
    """
    from sandbox.demand import CoverageMiss
    if len(query) > 500 or re.search(r'\w+:', query):
        raise CoverageMiss('Search syntax outside captured-corpus support')
    terms = set(re.findall(r'\w+', query.casefold())) - STOPWORDS
    if not terms:
        return []
    ranked = []
    for article in world.pages():
        title = article['page']['display_title']
        title_terms = set(re.findall(r'\w+', title.casefold()))
        words = set(re.findall(r'\w+', world.bytes(article['text_blob']).decode().casefold()))
        if terms <= words | title_terms:
            ranked.append((len(terms & title_terms), title, article))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked[:limit]]
