"""Upgrade the reviewed paired fixture to captured native source and full metadata.

Recipe-specific historical transfer rules live here, never in the world engine.
All transformed bytes and exact edits are retained in each new world's audit.
"""
import argparse,copy,difflib,json,re,shutil,sqlite3
from pathlib import Path
from urllib.parse import quote
from lxml import html
from sandbox.archive import encoded,durable,seal,sha,verify,read_blob
from sandbox.demand import create,WorldService
from sandbox.wikipedia_native import apply_patches,compact_patches,undefined_references


def prose(text):
 return ' '.join(re.sub(r'<ref\b[^>]*(?:/>|>.*?</ref>)','',text,flags=re.S).split())


def transfer(source,edits,title):
 result=source;log=[]
 for edit in edits:
  before=edit['before'];after=edit['after'];patches=[]
  if result.count(before)==1:patches=[edit]
  else:
   # Earlier revisions differ in archived citation URLs. Only reuse a block edit
   # if all its non-reference source text is identical; retain the actual before.
   matches=[b for b in re.split(r'\n[ \t]*\n',result) if prose(b)==prose(before)]
   if len(matches)==1:patches=[{**edit,'before':matches[0]}]
   elif title=='OpenAI' and '== Further reading ==' in before:
    lines=[l for l in result.splitlines() if 'OpenAI CEO Sam Altman Takes the Stand' in l]
    patches=[{**edit,'before':l,'after':''} for l in lines]
   else:
    for small in compact_patches(before,[edit]):
     b=small['before'];a=small['after']
     if result.count(b)==1:patches.append(small);continue
     # Remove unchanged context only; never fuzzy-match the changed claim.
     prefix=0
     while prefix<min(len(b),len(a)) and b[prefix]==a[prefix]:prefix+=1
     suffix=0
     while suffix<min(len(b)-prefix,len(a)-prefix) and b[-suffix-1]==a[-suffix-1]:suffix+=1
     found=None
     for context in (20,10,0):
      left=max(0,prefix-context);right=len(b)-max(0,suffix-context);aright=len(a)-max(0,suffix-context)
      anchor=b[left:right]
      if len(anchor)>=12 and result.count(anchor)==1:found={**small,'before':anchor,'after':a[left:aright]};break
     if found:patches.append(found)
     elif title=='Sam Altman' and 'At a birthday party Thiel' in b:
      match=re.search(r' At a birthday party Thiel[^\n]+',result)
      if not match:raise ValueError('Unmatched birthday anecdote')
      patches.append({**small,'before':match[0],'after':''})
     else:raise ValueError(('Historical native patch needs review',title,b[:120]))
  result=apply_patches(result,patches);log.extend(patches)
 if undefined_references(result)-undefined_references(source):raise ValueError('Introduced undefined references')
 return result,log


def preserve_background(document,title):
 """Repair two unrelated details found missing by the native-source audit."""
 tree=html.fromstring(document,parser=html.HTMLParser(encoding='utf-8'))
 if title=='OpenAI':
  candidates=[n for n in tree.xpath('//li') if ' '.join(n.text_content().split())=='Sam Altman, co-founder']
  if len(candidates)!=1:raise ValueError('Ambiguous board entry')
  n=candidates[0];span=html.Element('span');span.text=', former president of Y Combinator';n.append(span)
 elif title=='Sam Altman':
  nodes=tree.xpath('//*[@id="OpenAI"]')
  if len(nodes)!=1:raise ValueError('Missing OpenAI section')
  section=nodes[0].xpath('ancestor::section[1]')[0]
  paragraph=html.Element('p');paragraph.text='Brockman took a sabbatical from August 2024 to November 2024.';section.append(paragraph)
 return html.tostring(tree,encoding='utf-8',doctype='<!doctype html>')


def extra_navigation(document,scenario):
 tree=html.fromstring(document,parser=html.HTMLParser(encoding='utf-8'));removed=[]
 excluded=[e['source_title'].replace(' ','_') for e in scenario['world_model']['entities'] if not e['exists']]
 for anchor in list(tree.xpath('//a[@href]')):
  if any(name in anchor.get('href','') for name in excluded):
   target=anchor.xpath('ancestor::li[1]');target=target[0] if target else anchor
   removed.append(' '.join(target.text_content().split()));target.drop_tree()
 for node in tree.iter():
  if isinstance(node.tag,str):node.attrib.pop('data-mw',None)
 return html.tostring(tree,encoding='utf-8',doctype='<!doctype html>'),removed


def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('base','extra','output'):p.add_argument('--'+name,type=Path,required=True)
 p.add_argument('--patches',type=Path,default=Path(__file__).with_name('native-patches.json'))
 a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);patches=json.loads(a.patches.read_text())
 summary={'worlds':{},'limitations':['Wikipedia adapter only.','Frozen replay covers 8 titles and 64 revisions; unknown topics still require growing mode.','Native historical edits are exact/manual recipe transfers, not independent model audits of every old revision.','Captured source editor names and comments describe the source history; they do not attest to the fictional transformation.','Template expansion remains capture-time HTML.']}
 for condition in ('reference','synthetic'):
  parent=a.base/(condition+'-frozen');digest=verify(parent);config=json.loads((parent/'world.json').read_text());scenario=copy.deepcopy(config['scenario']);scenario['id']+='-native';scenario['wikipedia']={'raw':'native','revision_metadata':'preserve','search':'captured_corpus'}
  scenario['on_demand'].update(max_versions=200,max_attempts=400,generation_seconds=300)
  path=a.output/(condition+'-growing');create(path,scenario,config['renderer_image'])
  with sqlite3.connect(parent/'world.sqlite') as src,sqlite3.connect(path/'world.sqlite') as dst:src.backup(dst)
  for name in ('attempts','blobs'):shutil.copytree(parent/name,path/name,dirs_exist_ok=True)
  durable(path/'native-parent.json',encoded({'path':str(parent),'seal':digest,'patches_sha256':sha(a.patches.read_bytes())}))
  w=WorldService(path)
  try:
   # Cached representations contain old projection/blank metadata, so rebuild.
   w.db.execute("DELETE FROM cache WHERE key LIKE 'response:%' OR key LIKE 'history:%'")
   histories={};current={key:json.loads(v)['record']['revid'] for key,v in w.db.execute('SELECT key,value FROM pages')}
   for key,revision,data in list(w.db.execute('SELECT key,revision,value FROM versions')):
    value=json.loads(data);capture=parent/'attempts'/value['attempt']/'original-capture';meta=json.loads((capture/'original.json').read_text());source=read_blob(capture/'audit',meta['source_blob']).decode()
    text,edits=(source,[]) if condition=='reference' else transfer(source,patches[key],key)
    if condition=='synthetic' and key in ('OpenAI','Sam Altman'):
     value['html_blob']=w.blob(preserve_background(w.bytes(value['html_blob']),key))
    attempt,store=w.attempt();record=meta['record'];value.update(record=record,text_blob=w.blob(text.encode()),text_format='native_wikitext',attempt=attempt.name,validation_status='manual_reviewed',generation_method='native_recipe_transfer')
    value['page']['sha256']=sha(text.encode());value['world_sha256']=sha(encoded(scenario['world_model']))
    shutil.copytree(capture,attempt/'original-capture');durable(attempt/'native-review.json',encoded({'condition':condition,'edits':edits,'source_blob':meta['source_blob'],'parent_value':json.loads(data),'record_policy':'Preserved source record; comments inspected for scenario conflicts.'}));durable(attempt/'accepted.json',encoded(value));seal(attempt)
    w.db.execute('UPDATE versions SET value=? WHERE key=? AND revision=?',(json.dumps(value),key,revision))
    if current[key]==revision:w.db.execute('UPDATE pages SET value=? WHERE key=?',(json.dumps(value),key))
    histories.setdefault(key,[]).append(record)
   for capture in sorted(a.extra.iterdir()):
    if not capture.is_dir() or not (capture/'original.json').exists():continue
    verify(capture);meta=json.loads((capture/'original.json').read_text());title=meta['title'];document=read_blob(capture/'audit',meta['document_blob']);text=read_blob(capture/'audit',meta['source_blob']).decode();record=meta['record'];attempt,store=w.attempt();shutil.copytree(capture,attempt/'original-capture')
    removed=[]
    if condition=='synthetic':document,removed=extra_navigation(document,scenario)
    page={'title':title,'display_title':title,'page_id':meta['page_id'],'revision_id':record['revid'],'revision_at':record['timestamp'],'sha256':sha(text.encode()),'source_url':'https://en.wikipedia.org/w/index.php?oldid='+str(record['revid'])}
    value={'title':title,'page':page,'record':record,'html_blob':w.blob(w.assets(document)),'text_blob':w.blob(text.encode()),'text_format':'native_wikitext','attempt':attempt.name,'world_sha256':sha(encoded(scenario['world_model'])),'facts_sha256':sha(encoded(w.facts())),'effective_date':record['timestamp'][:10],'dependencies':sorted(w.facts()),'validation_status':'manual_reviewed','generation_method':'unchanged_capture'}
    durable(attempt/'native-review.json',encoded({'decision':'Preserved native article source and prose; removed excluded-event links from expanded navigation templates.','removed_navigation':removed,'source_seal':verify(capture)}));durable(attempt/'accepted.json',encoded(value));seal(attempt)
    w.db.execute('INSERT INTO pages VALUES (?,?)',(title,json.dumps(value)));w.db.execute('INSERT INTO versions VALUES (?,?,?)',(title,record['revid'],json.dumps(value)));w.db.execute('INSERT OR REPLACE INTO aliases VALUES (?,?)',(capture.name.replace('_',' '),title));histories[title]=[record]
   for title,records in histories.items():w.db.execute('INSERT INTO cache VALUES (?,?)',('history:'+title+':'+str(len(records)),json.dumps(sorted(records,key=lambda r:r['timestamp'],reverse=True))))
   w.db.commit();checks=[]
   for title in histories:
    name=quote(title);paths=['/wiki/'+name,'/w/index.php?title='+name+'&action=raw','/wiki/Special:Export/'+name,'/w/api.php?action=parse&page='+name+'&prop=wikitext&section=0','/w/api.php?action=query&titles='+name+'&prop=revisions&rvprop=ids|timestamp|user|comment|content&rvslots=main']
    if len(histories[title])>1:paths+=['/w/index.php?title='+name+'&action=history','/w/api.php?action=query&titles='+name+'&prop=revisions&rvprop=ids|timestamp|user|comment&rvlimit=10']
    for r in histories[title]:paths.append('/w/index.php?oldid='+str(r['revid']))
    for target in paths:
     r=w.handle(target);checks.append({'path':target,'status':r['status']});assert r['status']==200,(target,r)
   assert w.handle('/wiki/Claude_(language_model)')['status']==200
   frozen=a.output/(condition+'-frozen');digest=w.freeze(frozen);summary['worlds'][condition]={'path':str(frozen),'seal':digest,'pages':len(histories),'versions':sum(map(len,histories.values())),'checks':checks};print(condition,len(checks),'checks',flush=True)
  finally:w.close()
 durable(a.output/'preparation.json',encoded(summary));seal(a.output)


if __name__=='__main__':main()
