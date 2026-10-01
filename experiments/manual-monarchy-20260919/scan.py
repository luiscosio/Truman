from pathlib import Path
from lxml import html
import re
from sandbox.demand_integrity import article_shape,integrity_issues
from sandbox.sites import load
WIKIPEDIA=load('wikipedia')
P=Path(__file__).resolve().parent
pattern=re.compile(r'(?i)Charles III|King Charles|Queen Camilla|Elizabeth.{0,40}(?:died|death|1926.{0,5}2022|1952.{0,5}2022)|(?:death|late|funeral) of (?:the Queen|Elizabeth)|(?:since|until|–|to) 8 September 2022|(?:the King|The Queen|Prince of Wales|Princess of Wales)|2022 deaths|70 years and 214|second.longest')
for i in range(9):
 t=html.fromstring((P/f'{i}-review.html').read_bytes(),parser=html.HTMLParser(encoding='utf-8'));rows=[]
 for x in t.iter():
  if x.tag not in ('p','tr','li','figcaption','h1','h2','h3','td','th','div','span'):continue
  if x.xpath('.//p|.//tr|.//li|.//td|.//th|.//div'):continue
  if x.xpath('ancestor::style'):continue
  s=' '.join(x.text_content().split())
  if pattern.search(s) and len(s)<2000 and not x.xpath('ancestor::li[contains(@id,"cite_note")]'):
   rows.append(f'{x.get("data-manual-id")} [{x.tag}] {s}')
 (P/f'{i}-scan2.txt').write_text('\n'.join(rows))
 print(i,article_shape(WIKIPEDIA,(P/f'{i}-candidate.html').read_bytes()),integrity_issues(WIKIPEDIA,(P/f'{i}-original.html').read_bytes(),(P/f'{i}-candidate.html').read_bytes()))
