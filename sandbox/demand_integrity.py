"""Page integrity checks, independent of scenario entities and answers.

The site profile names the page body and its lead section.
"""
from lxml import html


def article_shape(site, document):
    tree = html.fromstring(document, parser=html.HTMLParser(encoding='utf-8'))
    bodies = tree.xpath(site.content['body'])
    if not bodies:
        return {'paragraphs': 0, 'prose_chars': 0, 'lead_chars': 0}
    root = bodies[0]
    paragraphs = [p.text_content().strip() for p in root.xpath('.//p') if not p.xpath('ancestor::table')]
    lead = root.xpath(site.content['lead'])
    intro = lead[0].xpath('.//p') if lead else root.xpath('.//p')[:1]
    return {'paragraphs': sum(bool(p) for p in paragraphs), 'prose_chars': sum(map(len, paragraphs)),
            'lead_chars': sum(len(p.text_content().strip()) for p in intro if not p.xpath('ancestor::table'))}


def integrity_issues(site, original, candidate):
    before, after = article_shape(site, original), article_shape(site, candidate)
    issues = []
    if before['lead_chars'] and not after['lead_chars']:
        issues.append({'blocks': [], 'reason': 'Restore a readable opening paragraph; the original lead was erased.'})
    if before['prose_chars'] >= 500 and after['prose_chars'] < before['prose_chars'] * .5:
        issues.append({'blocks': [], 'reason': 'More than half the original prose was erased. Restore unrelated facts and rewrite mixed paragraphs instead of deleting them.'})
    return issues


def topic_summary(site, document):
    tree = html.fromstring(document, parser=html.HTMLParser(encoding='utf-8'))
    root = tree.xpath(site.content['body'])[0]
    # Identification only; the later rewrite/review still sees the entire document.
    paragraphs = [p.text_content().strip() for p in root.xpath('.//p') if p.text_content().strip()]
    headings = [h.text_content().strip() for h in root.xpath('.//h2|.//h3')]
    return {'opening': '\n'.join(paragraphs[:4])[:12000], 'headings': headings[:80]}
