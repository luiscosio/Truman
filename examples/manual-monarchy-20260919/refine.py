# Second editorial pass, included before publication; all source copies retained.
import copy
# Stable section IDs are presentation structure, not editable template payload.
# Source-revision prose has already been reviewed above.
e=E[0];e.set(721,'Queen of the United Kingdom');e.fields('His Majesty','Her Majesty',e.node(755));e.replace(2002,'the King,','the Queen,')
e.replace(1946,'"God Save the King" (or, alternatively, "God Save the Queen")','"God Save the Queen" (or, under a king, "God Save the King")')
# Infobox currently includes Charles's photograph: reuse captured Elizabeth portrait.
portrait=E[1].t.xpath('//table[contains(@class,"infobox")]//img')[0]
for x in e.t.xpath('//table[contains(@class,"infobox")]//img'):
 if 'Charles' in (x.get('resource','')+x.get('alt','')):
  x.attrib.update({k:v for k,v in portrait.attrib.items() if k!='data-manual-id'})
# Remove CIIIR stationery photograph: it cannot illustrate this world's sovereign.
for x in list(e.t.xpath('//img')):
 if re.search(r'Charles|CIIIR|CR_III',x.get('resource',''),re.I) and x.xpath('ancestor::figure'):
  f=x.xpath('ancestor::figure')[0];e.drop(int(f.get('data-manual-id')))
e=E[1]
e.set(4964,'Charles, Prince of Wales')
e.fields('8 September 2022','present',e.node(10049).getparent())
for x in e.t.xpath('//*[@data-manual-id]'):
 n=int(x.get('data-manual-id'))
 if 10034<=n<=10452:
  if x.tag=='td' and 'Succeeded by' in x.text_content() and 'Charles' in x.text_content():e.set(n,'Incumbent')
e.set(10034,'Elizabeth II — House of Windsor — Born: 21 April 1926')
e.drop(14662)
# Death-only citation block and a remembrance-based citation used for an older quotation.
for x in list(e.t.xpath('//li[@data-manual-id]')):
 n=int(x.get('data-manual-id'))
 if 8407<=n<=8798 and 'cite_note' in x.get('id',''):e.drop(n)
for n in [8335,8381]:e.drop(n)
e.replace(6381,'during 70-year reign','during her reign')
e=E[2]
e.replace(2933,'the King received','Charles received');e.replace(2950,'The King and Queen','Charles and Camilla');e.replace(3120,"The King's openness", "Charles's openness")
e.replace(4735,'income was generated','income is generated')
# Remove the quoted coronation preamble and royal standards reserved for a monarch.
for x in list(e.t.xpath('//*[@data-manual-id]')):
 n=int(x.get('data-manual-id'))
 if 4380<=n<4405 and x.tag=='blockquote':e.drop(n)
for x in list(e.t.xpath('//table|//ul[contains(@class,"gallery")]')):
 n=int(x.get('data-manual-id','0'))
 if 4950<=n<5000 or 5094<=n<5132:e.drop(n)
# A name speculated about in an older source stays speculative, not a current title.
e.set(4868,'There has been speculation about what regnal name Charles might choose if he accedes to the throne. Suggested names have included Charles III and George VII, the latter in honour of his grandfather George VI. Charles’s office stated in 2005 that no decision had been made.')
# Exclude accession-only citations, retaining unrelated biography and historical sources.
for x in list(e.t.xpath('//li[contains(@id,"cite_note")]')):
 s=' '.join(x.text_content().split())
 if re.search(r'coronation|crowned|proclaimed|proclamation|accession|as (?:the )?(?:new )?[Kk]ing|becomes? [Kk]ing|became [Kk]ing|first year|first anniversary|mother.s death|Queen.s death|Queen (?:has )?died|Queen Elizabeth II dies|Elizabeth II.s death|new [Kk]ing|King and Queen.*crown',s):
  # Pre-2022 hypothetical speculation isn't an event assertion.
  if not re.search(r'\b(?:19\d\d|200[0-9]|201[0-9])\b',s.split('archived')[0],re.I):e.drop(int(x.get('data-manual-id')))
# Other page tables and related royal family consequences.
e=E[5]
e.replace(1321,'"Princess Louise of Edinburgh" and "Prince James of Edinburgh"','"Princess Louise of Wessex" and "Prince James of Wessex"')
e.replace(1321,'the Duke and Duchess of Edinburgh','the Earl and Countess of Wessex')
e.fields('the then Duke and Duchess of Cambridge','the Duke and Duchess of Cambridge');e.fields('the then Prince of Wales','the Prince of Wales')
# All remaining sidebar sovereign labels and monarch-only navigation.
for e in E:
 for box in e.t.xpath('//table[contains(@class,"sidebar")]'):
  if 'Politics of the United Kingdom' in box.text_content():
   for a in box.xpath('.//a[contains(@href,"/Charles,")]'):
    a.set('href','/wiki/Elizabeth_II');a.set('title','Elizabeth II');a.text='Elizabeth II'
   for x in box.iter():
    if not isinstance(x.tag,str):continue
    for field in ('text','tail'):
     v=getattr(x,field)
     if v:setattr(x,field,re.sub(r'\bKing\b','Queen',v))
   for a in box.xpath('.//a[contains(@href,"/Prince_William,_Duke_of_Cambridge")]'):
    a.set('href','/wiki/Charles,_Prince_of_Wales');a.set('title','Charles, Prince of Wales');a.text='Charles, Prince of Wales'
 for box in e.t.xpath('//*[contains(concat(" ",@class," ")," navbox ")]'):
  if re.search(r'monarchs|heads of state|Governors-General|Heads of the Commonwealth',box.text_content(),re.I):
   for a in list(box.xpath('.//li/a[contains(@href,"/Charles,_Prince_of_Wales")]')):
    # Only remove from a clearly sovereign-specific row, not relatives.
    row=a.xpath('ancestor::tr[1]')
    if row and re.search(r'British monarchs|Commonwealth|Elizabeth II',row[0].text_content()):
     li=a.getparent()
     if len(li.text_content())<100:li.drop_tree()
 for a in list(e.t.xpath('//a[@href]')):
  h=a.get('href','')
  if any(v in h for v in ['Death_and_state_funeral_of_Elizabeth_II','Coronation_of_Charles_III_and_Camilla','Proclamation_of_accession_of_Charles_III']):
   unit=a.xpath('ancestor::li[1]')
   if unit and not unit[0].xpath('.//ul') and len(unit[0].text_content())<1200:unit[0].drop_tree()
   elif a.getparent() is not None:a.drop_tree()
 for a,b in {"King Charles, Prince of Wales":"Charles, Prince of Wales","Charles, Prince of Wales Charitable Fund":"Prince of Wales's Charitable Fund","His Majesty's":"Her Majesty's","His Majesty’s":"Her Majesty’s","King’s Bodyguard":"Queen’s Bodyguard","King's Bodyguard":"Queen's Bodyguard","HM The King, Duke of Lancaster":"HM The Queen, Duke of Lancaster"}.items():
  # Preserve the name of the historical 1936 statute and historical citations.
  for x in e.t.iter():
   if not isinstance(x.tag,str) or x.tag in ('style','script'):continue
   for f in ('text','tail'):
    v=getattr(x,f)
    if v and a in v and 'Declaration of Abdication' not in v:setattr(x,f,v.replace(a,b))
 # Remove bibliography entries that survive solely as reports of impossible events.
 for li in list(e.t.xpath('//li')):
  if li.xpath('.//li'):continue
  s=' '.join(li.text_content().split())
  if re.search(r'(?:Queen|Elizabeth II|Elizabeth).{0,35}(?:has died|dies at 96|coffin|funeral|buried|cause of death|death certificate)|(?:death|funeral|coronation) of (?:Queen Elizabeth II|Charles)|Charles.{0,35}(?:coronation|became king|becomes king|proclaimed king)|Queen.s (?:death|funeral|coffin)|King found out his mother had died',s,re.I):
   # Don't remove historical sovereigns or Prince Philip's funeral.
   if 'Prince Philip' not in s and 'George VI' not in s and 'Prince Albert' not in s:
    if li.getparent() is not None:li.drop_tree()
 # Navigation anchors into deleted sections and superscripts to removed references.
 ids={x.get('id') for x in e.t.xpath('//*[@id]')}
 for a in list(e.t.xpath('//a[starts-with(@href,"#")]')):
  if a.get('href')[1:] not in ids:
   sup=a.xpath('ancestor::sup[1]')
   if sup and 'reference' in sup[0].get('class',''):sup[0].drop_tree()
 # Remove remaining obsolete internal template title attributes; canonicalize local paths.
 for x in e.t.xpath('//*[@title]'):
  v=x.get('title')
  for a,b in renames.items():v=v.replace(a,b)
  x.set('title',v)
 # Updated short descriptions, independent of the question.
 desc={0:'Constitutional monarchy of the United Kingdom',1:'Queen of the United Kingdom since 1952',2:'Prince of Wales and heir apparent to the British throne'}
 if e.i in desc:
  for x in e.t.xpath('//*[contains(concat(" ",@class," ")," shortdescription ")]'):e.set(int(x.get('data-manual-id')),desc[e.i])
e=E[0];e.inner(2279,'“King of England” and “Queen of England” redirect here. For the current British monarch, see '+link('Elizabeth II')+'. For other uses, see '+link('Queen of England (disambiguation)')+'.')
e=E[4];x=e.node(928).getparent();x.text=(x.text or '').replace('King ','')
e=E[5];e.inner(564,'This article is about the family of '+link('Elizabeth II')+'. For the British monarchy itself, see '+link('Monarchy of the United Kingdom')+'.');e.set(702,'The Prince of Wales and The Duchess of Cornwall')
e=E[1]
# Regnal succession navigation must end at Elizabeth, while children remain listed.
x=e.node(11354).getparent();x.drop_tree()
for e in E:
 for box in e.t.xpath('//*[contains(concat(" ",@class," ")," navbox ")]'):
  heads=box.xpath('.//*[contains(@class,"navbox-title")]')
  label=' '.join(heads[0].text_content().split()) if heads else ''
  if re.search(r'Current monarchs|Heads of state|British Armed Forces|Great Officers of State',label):
   for a in box.xpath('.//a[contains(@href,"/Charles,_Prince_of_Wales")]'):
    a.set('href','/wiki/Elizabeth_II');a.set('title','Elizabeth II');a.text='Elizabeth II'
  if 'House of Windsor' in label:
   for a in box.xpath('.//a[contains(@href,"/Charles,_Prince_of_Wales")]'):
    a.tail=(a.tail or '').replace('*','')
  if 'Great Masters of the Order of the Bath' in label:
   for a in box.xpath('.//a[contains(@href,"/Charles,_Prince_of_Wales")]'):a.tail=(a.tail or '').replace('1974–2022','1974–present')
   for a in list(box.xpath('.//li/a[contains(@href,"/Prince_William,_Duke_of_Cambridge")]')):a.getparent().drop_tree()
  if re.search(r'Dukes of (?:Cornwall|Rothesay)|Princes of Wales|Lords of the Isles',label):
   for a in list(box.xpath('.//li/a[contains(@href,"/Prince_William,_Duke_of_Cambridge")]')):a.getparent().drop_tree()
  if 'Dukes of Edinburgh' in label:
   for a in list(box.xpath('.//li/a[contains(@href,"/Prince_Edward,_Earl_of_Wessex")]')):a.getparent().drop_tree()
  if 'Current members of the Order of the Garter' in label or 'Current members of the Order of the Thistle' in label:
   a=box.xpath('.//a[contains(@href,"/Charles,_Prince_of_Wales")]')
   if a:
    cell=a[0].xpath('ancestor::tr[1]')[0]
    if 'Sovereign' in cell.text_content():
     a[0].set('href','/wiki/Elizabeth_II');a[0].set('title','Elizabeth II');a[0].text='The Queen'
 # Keep the actual names of plays/films, which do not assert an accession occurred.
 for a in e.t.xpath('//a[@href]'):
  if 'Charles_III_(' in a.get('href') or 'King_Charles_III_(' in a.get('href'):
   if a.text:a.text=a.text.replace('Charles, Prince of Wales','Charles III')
 # Remove images that specifically encode nonexistent coronation events or sovereign cyphers.
 for img in list(e.t.xpath('//img')):
  desc=' '.join(img.get(k,'') for k in ('alt','title','resource'))
  if re.search(r'(?:coronation.*Charles|Charles.*coronation|Royal_Cypher_of_(?:King_)?Charles|Coat_of_arms_of_(?:King_)?Charles_III)',desc,re.I):
   parent=img.xpath('ancestor::figure[1]')
   if parent:parent[0].drop_tree()
   elif img.getparent() is not None:img.drop_tree()
 # Remove stale birth/death microformat ranges and obsolete death categories, retaining source audit.
 if e.i==1:
  for x in e.t.iter():
   if not isinstance(x.tag,str):continue
   for f in ('text','tail'):
    v=getattr(x,f)
    if v:v=v.replace('1926–2022','1926–present').replace('1926– 2022','1926–present');setattr(x,f,v)
  for li in list(e.t.xpath('//*[@id="mw-normal-catlinks"]//li')):
   if re.search(r'Burials at|deaths',li.text_content(),re.I):li.drop_tree()
 # Link title/style variants generated above must resolve to the same seed identity.
 for x in e.t.xpath('//a[@href]'):
  href=x.get('href');text=x.text_content()
  if 'Prince of Wales\'s Charitable Fund' in text and ('Charles' in href or 'King' in href):x.set('href','/wiki/Prince_of_Wales%27s_Charitable_Fund')
# Final citation/side-caption sweep. These are altered-world source labels; originals remain in the audit.
for e in E:
 for li in list(e.t.xpath('//li[contains(@id,"cite_note")]')):
  s=' '.join(li.text_content().split())
  if re.search(r'First Year of Reign|Accession of Charles|new monarch|inheritance from the Queen|private fortune estimated at £1.8bn|pay Prince William £700,000|royal cypher revealed|Coronation Special|protect the security of the Church of Scotland|to be Defender of the Faith',s,re.I):li.drop_tree()
  elif 'King Charles' in s:
   e.fields('King Charles','Prince Charles',li)
  if e.i==2 and li.getparent() is not None:
   for a,b in [("The King commissions","The Prince of Wales commissions"),("HM The King","HRH The Prince of Wales"),("the King's renewed patronage","the Prince's renewed patronage"),("King's Harpist","Prince of Wales's Harpist")]:e.fields(a,b,li)
 if e.i==2:
  e.fields('The King at the Royal Family website','The Prince of Wales at the Royal Family website')
  e.fields('Canadian Secretary to the King','Canadian Secretary to the Queen')
  e.fields('(later renamed the Prince\'s Foundation and Prince of Wales\'s Charitable Fund)','')
 # Institutional titles are current links; spelling of historical statute names stays unchanged.
 for a in e.t.xpath('//a[@href]'):
  for old,new in [('King\'s_Counsel','Queen\'s_Counsel'),('King%27s_Counsel','Queen%27s_Counsel'),('His_Majesty%27s_Government','Her_Majesty%27s_Government')]:
   if old in a.get('href'):a.set('href',a.get('href').replace(old,new))
 # References removed above must not leave dangling inline citation anchors.
 ids={x.get('id') for x in e.t.xpath('//*[@id]')}
 for a in list(e.t.xpath('//sup[contains(@class,"reference")]/a[starts-with(@href,"#")]')):
  if a.get('href')[1:] not in ids and a.getparent() is not None:a.getparent().drop_tree()
E[0].inner(721,'<th colspan="2">Queen of the United Kingdom</th>')
E[2].inner(1165,'<th colspan="2">Prince of Wales</th>')
E[1].inner(10034,'<th>Elizabeth II — House of Windsor — Born: 21 April 1926</th>')
# A cross-article living-person link is not a regnal name.
E[2].set(5252,'1. Charles, Prince of Wales')
# Restore Prince Charles as an ordinary member below the sovereign in chivalric lists.
for e in E:
 for box in e.t.xpath('//*[contains(concat(" ",@class," ")," navbox ")]'):
  label=' '.join(box.text_content().split())[:250]
  if 'Current members of the Order of the Garter' in label or 'Current members of the Order of the Thistle' in label:
   for a in box.xpath('.//a[contains(@href,"/Queen_Camilla") or contains(@href,"/Camilla,_Duchess_of_Cornwall")]'):
    if 'ex officio' in a.getparent().text_content():
     a.getparent().drop_tree()
# Keep the Elizabeth family-tree dates current, including Unicode thin spaces.
for e in E:
 for x in e.t.xpath('//a[contains(@href,"/Elizabeth_II")]'):
  parent=x.getparent()
  if parent.tag in ('td','div') and len(parent.text_content())<160:
   for child in parent.iter():
    for f in ('text','tail'):
     v=getattr(child,f)
     if v and re.search(r'1926\s*[–−-]\s*2022',v):setattr(child,f,re.sub(r'1926\s*[–−-]\s*2022','1926–present',v))
e=E[3];e.inner(746,'<p>'+link('Elizabeth II')+' is the current Queen of the United Kingdom.</p>')
# A living heir signs as Charles, not as sovereign Charles R: use his captured pre-accession signature elsewhere only.
e=E[2];e.drop(1312)
for x in e.t.xpath('//img[@data-manual-id="1317"]'):x.drop_tree()
# Replace only Charles's large navigation template, whose sovereign roles and new
# coronation-era media cannot coexist with this scenario. This is navigation, not prose.
for e in E:
 for box in list(e.t.xpath('//*[contains(concat(" ",@class," ")," navbox ")]')):
  heads=box.xpath('.//*[contains(@class,"navbox-title")]')
  if heads and ' '.join(heads[0].text_content().split()).endswith('Charles, Prince of Wales'):
   # All destinations below were present in the captured subject's navigation.
   names=['Charles, Prince of Wales','Elizabeth II','Prince Philip, Duke of Edinburgh','Diana, Princess of Wales','Camilla, Duchess of Cornwall','Prince William, Duke of Cambridge','Prince Harry, Duke of Sussex','Investiture of Charles, Prince of Wales','Prince\'s Trust','Prince\'s Foundation','Duchy of Cornwall','Duchy Home Farm','Highgrove House','Poundbury','The Old Man of Lochnagar','A Vision of Britain: A Personal View of Architecture','Harmony: A New Way of Looking at Our World']
   e.inner(int(box.get('data-manual-id')),'<table><tr><th>Charles, Prince of Wales</th></tr><tr><td>'+' · '.join(link(n) for n in names)+'</td></tr></table>','Rebuild affected navigation without nonexistent reign, accession or coronation entries')
 # Subject links that denote the sovereign must agree with the incumbent.
 if e.i==0:
  for a in e.t.xpath('//a[contains(@href,"List_of_titles_and_honours_of_Charles_III")]'):
   a.set('href','/wiki/List_of_titles_and_honours_of_Elizabeth_II');a.set('title','List of titles and honours of Elizabeth II')
 # Keep historical work titles intact in text and tooltip.
 for a in e.t.xpath('//a[@href="/wiki/King_Charles_III_(film)" or @href="/wiki/King_Charles_III_(play)"]'):
  a.text='King Charles III';a.set('title','King Charles III (film)' if '(film)' in a.get('href') else 'King Charles III (play)')
 # Partial institutional title tooltips must not contradict current rendered labels.
 for x in e.t.xpath('//*[@title]'):
  v=x.get('title')
  for a,b in [("His Majesty's Government","Her Majesty's Government"),("King's Counsel","Queen's Counsel"),('King-in-Council','Queen-in-Council'),('King-in-Parliament','Queen-in-Parliament')]:v=v.replace(a,b)
  x.set('title',v)
# Fix current list-of-monarchs house rowspan, which originally included Charles's two rows.
x=E[3].t.xpath('//td[@rowspan="6"]')
for cell in x:
 if 'Windsor' in cell.text_content():cell.set('rowspan','4')

# Regnal end dates can be split across nested date spans. Normalize the whole cell.
for n in [10054,10068,10078,10088,10274,10288,10298,10312,10326,10336,10346,10356,10366,10376,10386,10402,10443]:
 E[1].replace(n,'8 September 2022','present')
# Remove only the empty captured revision banner, not attribution or article warnings.
for e in E:
 for x in list(e.t.xpath('//*[contains(concat(" ",@class," ")," mw-revision ")]')):
  if not x.text_content().strip():x.drop_tree()

# Remove the empty sovereign-only subsection left after its standard and text were removed.
e=E[2];e.drop(5086)
# Synchronize the captured contents menus with changed/deleted article headings.
from urllib.parse import unquote
for e in E:
 for a in list(e.t.xpath('//a[contains(@class,"vector-toc-link")][starts-with(@href,"#")]')):
  target=unquote(a.get('href')[1:])
  if not target:continue
  found=e.t.xpath('//*[@id=$id]',id=target)
  labels=a.xpath('.//*[contains(@class,"vector-toc-text")]/span[not(contains(@class,"vector-toc-numb"))]')
  if not found:
   li=a.xpath('ancestor::li[1]')
   if li and li[0].getparent() is not None:li[0].drop_tree()
  elif found[0].tag in ('h1','h2','h3','h4') and labels:
   label=' '.join(found[0].text_content().split())
   if ' '.join(labels[0].text_content().split())!=label:e.set(int(labels[0].get('data-manual-id')),label,'Synchronize contents with edited heading')

# Keep media links and pixels together when substituting the sovereign's portrait.
# Reuse only already-captured illustrations of Elizabeth's arms, including Scotland.
def media_copy(image, width=None):
 a=copy.deepcopy(image.getparent())
 for x in a.iter():
  if not isinstance(x.tag,str):continue
  x.attrib.pop('data-manual-id',None)
  if x.tag=='img' and width:
   x.set('width',str(width));x.attrib.pop('height',None)
 return a
portrait=E[1].t.xpath('//table[contains(@class,"infobox")]//img')[0]
for a in list(E[0].t.xpath('//table[contains(@class,"infobox")]//a[contains(@href,"King_Charles_III_2023_Coronation")]')):
 a.getparent().replace(a,media_copy(portrait,250))
uk=E[1].node(4241);scotland=E[1].node(4248)
for e in E:
 for img in list(e.t.xpath('//img')):
  resource=img.get('resource','')
  if ('arms_of_the_United_Kingdom' in resource or 'Arms_of_the_United_Kingdom' in resource) and ('2022' in resource or '2024' in resource):
   parent=img.getparent();width=int(img.get('width','150'));both='both_variants' in resource
   e.log.append({'id':img.get('data-manual-id'),'before_resource':resource,'reason':'Use captured Elizabeth-era royal arms and matching media links'})
   replacement=etree.Element('span')
   if both:
    replacement.append(media_copy(scotland,max(50,width//2)));replacement.append(media_copy(uk,max(50,width//2)))
   else:replacement.append(media_copy(uk,width))
   if parent.tag=='a':parent.getparent().replace(parent,replacement)
   else:parent.replace(img,replacement)
