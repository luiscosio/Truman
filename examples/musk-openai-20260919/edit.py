"""Manual, fixture-specific editorial recipe. No scenario rules in shared code."""
import argparse
import html as escape_html
import json
import re
from pathlib import Path
from lxml import html
from sandbox.archive import read_blob,sha,verify
from sandbox.demand_integrity import integrity_issues,article_shape


def main():
 p=argparse.ArgumentParser();p.add_argument('--sources',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 verify(a.sources);a.output.mkdir(parents=True,exist_ok=False)
 expected=json.loads((Path(__file__).with_name('sources.json')).read_text())
 for i in range(4):
  source=a.sources/str(i);meta=json.loads((source/'original.json').read_text());original=read_blob(source/'audit',meta['document_blob'])
  assert meta['title']==expected[i]['title'] and sha(original)==expected[i]['document_blob'], 'Source differs from the reviewed capture'
  tree=html.fromstring(original,parser=html.HTMLParser(encoding='utf-8'));log=[]
  for n,node in enumerate(tree.iter()):
   if isinstance(node.tag,str):node.set('data-manual-id',str(n))
  def node(id):return tree.xpath(f'//*[@data-manual-id="{id}"]')[0]
  def value(id):return re.sub(r'\[\d+\]','', ' '.join(node(id).text_content().split()))
  def write(id,text):
   target=node(id);before=html.tostring(target,encoding='unicode');attrs=dict(target.attrib);target.clear();target.attrib.update(attrs)
   markup=escape_html.escape(text)
   for name in ('Elon Musk','Sam Altman','OpenAI','ChatGPT'):
    markup=markup.replace(name, '<a href="https://en.wikipedia.org/wiki/'+name.replace(' ','_')+'" title="'+name+'">'+name+'</a>')
   fragment=html.fragment_fromstring('<div>'+markup+'</div>');target.text=fragment.text
   for child in list(fragment):target.append(child)
   log.append({'node':str(id),'before':before,'after':html.tostring(target,encoding='unicode')})
  def remove(target):
   if target.getparent() is not None:
    log.append({'node':target.get('data-manual-id'),'removed':html.tostring(target,encoding='unicode')});target.drop_tree()
  def section(heading):
   found=tree.xpath(f'//*[@id="{heading}"]')
   for target in found:
    parents=target.xpath('ancestor::section[1]')
    if parents:remove(parents[0])
   for anchor in tree.xpath('//a[@href]'):
    if anchor.get('href')=='#'+heading:
     parents=anchor.xpath('ancestor::li[1]');remove(parents[0] if parents else anchor)
  if i==0:
   write(998,'Elon Musk (CEO)')
   write(1326,value(1326)+' Elon Musk has served as its chief executive officer since March 2019.')
   write(1374,value(1374).replace('; Musk resigned in 2018','. Musk remained on the board and became CEO in March 2019').replace('including Anthropic, Safe Superintelligence Inc., SpaceXAI, and Thinking Machines Lab','including Anthropic, Safe Superintelligence Inc., and Thinking Machines Lab'))
   write(1397,re.sub(r"In November 2023,.*?board reconstruction\. ",'',value(1397)))
   write(1791,value(1791).split(' In April 2026, co-founder Musk')[0])
   remove(node(2242))
   write(2976,'CEO and co-founder: Elon Musk, who has led OpenAI since March 2019')
   write(3038,'Sam Altman, co-founder')
   extra=html.fragment_fromstring('<li><a href="https://en.wikipedia.org/wiki/Elon_Musk">Elon Musk</a>, CEO and co-founder</li>');node(3038).addnext(extra)
   section('Firing_of_Altman');section('Litigation_involving_Elon_Musk')
   write(3286,'Musk remained on OpenAI’s board and became its chief executive officer in March 2019. OpenAI stated that his financial contributions were below $45 million.')
   write(3375,value(3375).replace('reporting directly to Sam Altman','reporting directly to Elon Musk'))
   for id in (2953,3460):write(id,value(id).replace('CEO Sam Altman','co-founder Sam Altman'))
  elif i==1:
   write(1598,value(1598).replace('but later left; his growing discontent with the organization\'s direction and leadership in the AI boom in the 2020s led him to establish xAI, which became a subsidiary of SpaceX in 2026', 'and became its chief executive officer in March 2019. He also established xAI, which became a subsidiary of SpaceX in 2026'))
   write(3315,value(3315).replace('In 2018, Musk left the OpenAI board.', 'Musk remained on OpenAI’s board and has served continuously as its chief executive officer since March 2019.'))
   extra=html.fragment_fromstring('<li>Co-founder and CEO of <a href="https://en.wikipedia.org/wiki/OpenAI">OpenAI</a></li>');node(1289).addnext(extra)
   remove(node(7042))
  elif i==2:
   write(716,'Co-founder and board member of OpenAI')
   write(769,'Samuel Harris Altman (born April 22, 1985) is an American entrepreneur and investor, and a co-founder and board member of the artificial intelligence company OpenAI.')
   write(796,'Altman co-founded OpenAI in 2015 and has remained involved as a board member. Elon Musk became the company’s chief executive officer in March 2019 and has led it continuously since then. OpenAI launched ChatGPT in November 2022.')
   write(1411,'Elon Musk, a long-time personal friend of Altman’s, remained on OpenAI’s board and became its chief executive officer in March 2019. Altman continued as a co-founder and board member.')
   write(1444,'In March 2019, Altman left Y Combinator and continued his work as an investor and OpenAI board member. Through 2017, Brockman and Sutskever oversaw the day-to-day business and Altman touched base approximately once a week. OpenAI planned to spend $1 billion within five years, and possibly much faster. Altman said that the lab might ultimately need more capital than any nonprofit had ever raised to achieve artificial general intelligence.')
   write(1498,value(1498).split(' Altman stated that being CEO')[0])
   # Retain the unrelated September 2026 speech nested inside the excluded section.
   speech=html.fromstring(html.tostring(node(1656)));node(1537).addnext(speech)
   section('Removal_and_reinstatement_as_OpenAI_CEO');section('Elon_Musk_lawsuit')
   write(1945,value(1945).split(' At a birthday party')[0])
  else:
   write(1867,value(1867).replace('OpenAI CEO Sam Altman','OpenAI co-founder Sam Altman'))
  for caption in tree.xpath('//figcaption'):
   text=' '.join(caption.text_content().split())
   revised=text.replace('OpenAI CEO Sam Altman','OpenAI co-founder Sam Altman').replace('Altman (CEO of OpenAI)','Altman (co-founder of OpenAI)')
   if text!=revised:write(caption.get('data-manual-id'),revised)
  # The shared OpenAI navigation template is captured into several articles.
  for nav in tree.xpath('//table[contains(@class,"navbox")]'):
   heading=' '.join(nav.xpath('.//th[contains(@class,"navbox-title")]')[0].text_content().split()) if nav.xpath('.//th[contains(@class,"navbox-title")]') else ''
   if not heading.endswith('vteOpenAI'):continue
   for li in list(nav.xpath('.//li')):
    text=' '.join(li.text_content().split())
    if text in ('Sam Altman removal','Sam Altman') and li.xpath('ancestor::tr[th[contains(.,"Current")]]'):
     # Sam remains on the board, but is not senior management.
     if li.xpath('ancestor::tr[th[contains(.,"Seniormanagement") or contains(.,"Senior")]]'):
      write(li.get('data-manual-id'),'Elon Musk')
    if text=='Elon Musk (2015–2018)':
     # Move this membership into the Current row of the same board subsection.
     prior=li.xpath('ancestor::tr[1]')[0].getprevious()
     if prior is not None and prior.xpath('.//ul'):
      li.getparent().remove(li);prior.xpath('.//ul')[0].append(li)
      write(li.get('data-manual-id'),'Elon Musk')
    if text=='Emmett Shear':remove(li)
  # Remove nonexistent-event links, stale table-of-contents entries and categories.
  excluded=('Removal_of_Sam_Altman_from_OpenAI','Musk_v._Altman')
  for anchor in list(tree.xpath('//a[@href]')):
   if any(name in anchor.get('href','') for name in excluded):
    parents=anchor.xpath('ancestor::li[1]');remove(parents[0] if parents else anchor)
  # Do not forge sources for fictional events: omit incompatible bibliography
  # entries and their in-page markers, keeping the originals in the source audit.
  dropped=[]
  for li in list(tree.xpath('//li[starts-with(@id,"cite_note")] | //section[@aria-labelledby="Further_reading"]//li')):
   text=' '.join(li.text_content().split())
   conflict=(re.search(r'Altman',text,re.I) and 'OpenAI' in text and re.search(r'CEO|chief executive|oust|fir(?:e|ed|ing)|reinstat|return|board|Takes the Stand|takes.*stand|Trial of the Century',text,re.I)) or (re.search(r'Musk',text,re.I) and re.search(r'OpenAI|Altman',text,re.I) and re.search(r'suit|sue|sues|sued|control|leav|left|quit|trial|testif|verdict|takeover|take over|bid|war|stand|resign|court|jury|damages',text,re.I))
   if li.get('id','').startswith('cite_note') and not tree.xpath('//a[@href=$target]',target='#'+li.get('id')):conflict=True
   if conflict:
    if li.get('id'):dropped.append(li.get('id'))
    remove(li)
  for anchor in list(tree.xpath('//a[@href]')):
   if anchor.get('href','').lstrip('#') in dropped:
    sup=anchor.xpath('ancestor::sup[1]');remove(sup[0] if sup else anchor)
  for node_ in tree.iter():
   # Serialized Parsoid template source is audit metadata, not served world prose.
   for attr in list(node_.attrib):
    if attr=='data-mw' or attr=='data-manual-id':node_.attrib.pop(attr)
    elif attr in ('title','alt','content','aria-label'):
     node_.set(attr,node_.get(attr).replace('OpenAI CEO Sam Altman','OpenAI co-founder Sam Altman').replace('Altman (CEO of OpenAI)','Altman (co-founder of OpenAI)'))
  candidate=html.tostring(tree,encoding='utf-8',doctype='<!doctype html>')
  issues=integrity_issues(original,candidate)
  if issues:raise ValueError((i,issues))
  (a.output/f'{i}-candidate.html').write_bytes(candidate)
  (a.output/f'{i}-edits.json').write_text(json.dumps(log,ensure_ascii=False,indent=2))
  (a.output/f'{i}-review.json').write_text(json.dumps({'title':meta['title'],'source_html_sha256':sha(original),'candidate_html_sha256':sha(candidate),'source_shape':article_shape(original),'candidate_shape':article_shape(candidate),'edit_count':len(log),'removed_incompatible_citations':dropped},indent=2))
  print(meta['title'],len(log),'edits',flush=True)
if __name__=='__main__':main()
