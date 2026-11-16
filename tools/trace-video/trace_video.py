"""Turn a recorded Truman run into a captioned MP4, screenshots and a chapter player.

No rewriting model or live website is used. A story JSON can add editorial captions;
the run JSON remains the evidence. Rendering dependencies are optional and local.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit


def plain(text):
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text or '')
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.M)
    return text.replace('**', '').replace('`', '').replace('&#x20;', ' ')


def result_text(event):
    value = event.get('result', {}).get('content', '')
    if isinstance(value, list):
        return '\n'.join(x.get('text', '') for x in value if isinstance(x, dict))
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def request_urls(call):
    args = call.get('arguments', {})
    if args.get('url'):
        return [args['url']]
    return re.findall(r'https?://[^\s\"\'<>]+', str(args.get('command', '')))


def normalize_url(url):
    u = urlsplit(url)
    return u.netloc.lower(), unquote(u.path), unquote(u.query)


def build_plan(run):
    """Collapse linked calls/network/results while preserving interleaved requests.

    Ambiguous network events remain independent steps, never silently attributed.
    Final response text is retained in full and paginated by the renderer.
    """
    events = run['events']
    calls = {}
    for pos, event in enumerate(events):
        for call in event.get('calls', []):
            calls[call['id']] = {'call': call, 'pos': pos, 'event': event,
                                 'end': len(events), 'result': None, 'network': []}
    for pos, event in enumerate(events):
        if event.get('kind') == 'builtin_result':
            cid = event.get('call', {}).get('id') or event.get('result', {}).get('tool_use_id')
            if cid in calls:
                calls[cid].update(end=pos, result=event)
    unassigned = []
    for pos, event in enumerate(events):
        if event.get('kind') != 'network_request':
            continue
        active = [c for c in calls.values() if c['pos'] < pos < c['end']]
        url = 'https://' + event.get('host', '') + event.get('path', '')
        matches = [c for c in active if normalize_url(url) in
                   [normalize_url(u) for u in request_urls(c['call'])]]
        owner = matches[0] if len(matches) == 1 else active[0] if len(active) == 1 else None
        if owner:
            owner['network'].append(event)
        else:
            unassigned.append((pos, event))
    scenes = [{'key': 'intro', 'kind': 'intro', 'title': 'Watch the agent investigate',
               'body': 'A readable walkthrough of the recorded actions, pages and final response.',
               'event_ids': [], 'counts': [sum(e.get('kind') in ('start','user') for e in events),
                  sum(e.get('kind')=='network_request' for e in events),bool(run.get('final_answer'))]}]
    ordered = []
    final = run.get('final_answer', '')
    final_ids = [e['id'] for e in events if e.get('text') == final and final]
    for pos, event in enumerate(events):
        kind = event.get('kind')
        if kind in ('start', 'user'):
            ordered.append((pos, {'key': f"event-{event['id']}", 'kind': 'prompt',
                'title': 'The question', 'body': event.get('prompt', event.get('text', run.get('prompt', ''))),
                'event_ids': [event['id']]}))
        elif kind == 'assistant' and event.get('text') and event.get('text') != final:
            ordered.append((pos, {'key': f"event-{event['id']}", 'kind': 'observation',
                'title': 'The agent says', 'body': event['text'], 'event_ids': [event['id']]}))
        elif kind == 'error':
            ordered.append((pos, {'key': f"event-{event['id']}", 'kind': 'error',
                'title': 'The run encountered a problem', 'body': event.get('text') or json.dumps(event),
                'event_ids': [event['id']]}))
    for c in calls.values():
        result = c['result']
        networks = c['network'] or [None]
        for n, network in enumerate(networks):
            ids = [c['event']['id']] + ([network['id']] if network else []) + ([result['id']] if result else [])
            scene = {'key': f"call-{c['event']['id']}" + (f'-{n+1}' if len(networks)>1 else ''),
                     'kind': 'fetch' if network else 'tool', 'event_ids': sorted(ids),
                     'title': 'The agent opens a page' if network else f"The agent uses {c['call']['name']}",
                     'body': result_text(result) if result else 'No result recorded.',
                     'request': c['call'], 'network': network}
            if network:
                scene['page_title'] = (network.get('evidence') or {}).get('display_title') or unquote(network['path'])
                scene['url'] = 'https://' + network.get('host', '') + network.get('path', '')
                scene['status'] = network['status']
                if network['status']>=400:
                    scene['title']='The requested page is unavailable' if network['status']==404 else 'The request could not be served'
            ordered.append((c['pos'] + n*.01, scene))
    for pos, event in unassigned:
        ordered.append((pos, {'key': f"network-{event['id']}", 'kind': 'fetch',
            'title': 'The agent requests a resource', 'body': 'This response has no unambiguous tool-call match.',
            'event_ids': [event['id']], 'network': event, 'status': event['status'],
            'url': 'https://' + event.get('host', '') + event.get('path', ''),
            'page_title': (event.get('evidence') or {}).get('display_title') or unquote(event['path'])}))
    scenes.extend(s for _, s in sorted(ordered, key=lambda x: x[0]))
    scenes.append({'key': 'final', 'kind': 'final', 'title': 'The complete final response',
                   'body': final or 'No final response was recorded.', 'event_ids': final_ids})
    networks=[e for e in events if e.get('kind')=='network_request']
    loaded=sum(200<=e.get('status',0)<300 for e in networks)
    scenes.append({'key':'outcome','kind':'end','title':'The recorded outcome',
                   'body':f"Run status: {run.get('status','unknown').replace('_',' ')}.\n"
                          f"{loaded} of {len(networks)} recorded requests returned content.\n"
                          "Completing the task does not establish trust in the pages or lack of simulation awareness.",
                   'event_ids':[e['id'] for e in events if e.get('kind')=='finish']})
    return scenes


def find_blob(run_dir, digest):
    if not re.fullmatch('[a-f0-9]{64}', digest or ''):
        raise ValueError('Invalid recorded blob hash')
    for directory in ('capture', 'world-snapshot', 'origin-capture', 'network-audit'):
        path = run_dir / directory / 'blobs' / digest
        if path.is_file():
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('Changed recorded blob: ' + digest)
            return path
    raise FileNotFoundError('Recorded response missing: ' + digest)


def prepare_pages(run_dir, output, scenes):
    pages = []
    resources={}
    journal=run_dir/'capture/events.jsonl'
    if journal.exists():
        for line in journal.read_text().splitlines():
            event=json.loads(line)
            if event.get('kind')!='http_response' or event.get('status')!=200:continue
            headers=event.get('upstream_headers',[])
            mime=next((v for k,v in headers if k.lower()=='content-type'),'')
            digest=event.get('body_blob')
            if digest and event.get('host') and event.get('path'):
                resources['https://'+event['host']+event['path']]={
                    'path':str(find_blob(run_dir,digest)),'contentType':mime}
    for scene in scenes:
        event = scene.get('network')
        if not event or not 200 <= event.get('status', 0) < 300:
            continue
        path = find_blob(run_dir, event.get('body_blob') or event.get('representation_blob'))
        raw = path.read_bytes()
        if b'<html' not in raw[:10000].lower() and b'<!doctype html' not in raw[:10000].lower():
            continue  # JSON and text stay text; never invent a website screenshot.
        text = raw.decode('utf-8', errors='replace')
        assets = {}
        for digest in set(re.findall(r'/w/resources/([a-f0-9]{64})', text)):
            assets[digest] = str(find_blob(run_dir, digest))
        # Resolving captured relative resources requires a base, but routing is offline-only.
        base = '<base href="'+html.escape(scene['url'], quote=True)+'">'
        text = re.sub(r'<head([^>]*)>', lambda m: m.group(0)+base, text, count=1, flags=re.I)
        target = output/'assets'/f"{scene['key']}.html"
        target.write_text(text)
        image = output/'assets'/f"{scene['key']}.png"
        detail = output/'assets'/f"{scene['key']}-detail.png"
        pages.append({'html': str(target), 'output': str(image), 'assets': assets,
                      'resources':resources, 'selector': scene.get('selector'),
                      'detailSelector': scene.get('detail_selector'), 'detailOutput': str(detail),
                      'sourceBodySha256': hashlib.sha256(raw).hexdigest(),
                      'sourceEvent': event['id']})
        scene['screenshot'] = image.relative_to(output).as_posix()
        if scene.get('detail_selector'):
            scene['detail_screenshot'] = detail.relative_to(output).as_posix()
    manifest = output/'page-renders.json'
    manifest.write_text(json.dumps({'pages': pages}, indent=2))
    return manifest


def run_command(args):
    result = subprocess.run([str(x) for x in args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-5000:] or result.stdout[-5000:])


def font_path(bold=False):
    paths = ([Path('/System/Library/Fonts/Supplemental/Arial Bold.ttf'),
              Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
              Path('C:/Windows/Fonts/arialbd.ttf')] if bold else
             [Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
              Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'), Path('C:/Windows/Fonts/arial.ttf')])
    for p in paths:
        if p.exists():
            return str(p)
    raise FileNotFoundError('Install Arial or DejaVu Sans, or supply fonts to font_path().')


def lines_for(text, font, width):
    lines = []
    for paragraph in plain(text).splitlines():
        line = ''
        for word in paragraph.split():
            # Split very long URLs/tokens instead of allowing an overflow.
            chunks = [word]
            if font.getlength(word) > width:
                chunks, chunk = [], ''
                for char in word:
                    if font.getlength(chunk+char) > width:
                        chunks.append(chunk); chunk = ''
                    chunk += char
                chunks.append(chunk)
            for word in chunks:
                candidate = (line+' '+word).strip()
                if line and font.getlength(candidate) > width:
                    lines.append(line); line = word
                else:
                    line = candidate
        lines.append(line)
    return lines


def paginate(scenes):
    from PIL import ImageFont
    result = []
    for scene in scenes:
        if scene.get('skip'):
            continue
        if scene['kind'] in ('tool','fetch') and 'caption' not in scene:
            content=plain(scene['body'])
            if len(content)>900:
                scene={**scene,'caption':content[:900].rsplit(' ',1)[0]+'\n… Full tool result in transcript.'}
        if scene['kind'] == 'final':
            # A complete text transcript, not an automatic summary of the answer.
            font = ImageFont.truetype(font_path(), 38)
            chunks = text_pages(scene['body'],font,1650,12)
            for i, chunk in enumerate(chunks):
                result.append({**scene, 'key': f"final-{i+1}", 'title': f"Final response · {i+1} of {len(chunks)}",
                               'body': '\n'.join(chunk), 'fixed_lines': True,
                               'eyebrow': 'AGENT RESPONSE · FULL TEXT'})
        elif not scene.get('screenshot'):
            chunks=text_pages(scene.get('caption',scene['body']),
                              ImageFont.truetype(font_path(),44),1620,7)
            for i,chunk in enumerate(chunks):
                result.append({**scene, 'caption':'\n'.join(chunk),
                               'key':scene['key']+(f'-part-{i+1}' if len(chunks)>1 else '')})
        else:result.append(scene)
    return result


def text_pages(text, font, width, limit):
    """Keep paragraphs and list items together wherever they fit on one card."""
    chunks=[];current=[]
    raw_blocks=text.split('\n\n');blocks=[];i=0
    while i<len(raw_blocks):
        block=raw_blocks[i]
        if block.lstrip().startswith('#') and i+1<len(raw_blocks):
            block+='\n\n'+raw_blocks[i+1];i+=1
        blocks.append(plain(block));i+=1
    units=[]
    for block in blocks:
        if len(lines_for(block,font,width))>limit:
            units.extend(block.splitlines())
        else:units.append(block)
    for block in units:
        rows=lines_for(block,font,width)
        if len(current)+len(rows)+bool(current)>limit and current:
            chunks.append(current);current=[]
        while len(rows)>limit:
            chunks.append(rows[:limit]);rows=rows[limit:]
        if current:current.append('')
        current.extend(rows)
    if current:chunks.append(current)
    return chunks or [['']]


def paint_scene(scene, index, count, output):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    im = Image.new('RGB', (1920, 1080), '#F2F1EB'); d = ImageDraw.Draw(im)
    ink, muted, green, line = '#172C28', '#586B65', '#087F70', '#D2DBD4'
    def font(n, bold=False): return ImageFont.truetype(font_path(bold), n)
    def block(text, xy, size, width, color=ink, bold=False, max_lines=None):
        f = font(size, bold); rows = lines_for(text, f, width)
        if max_lines and len(rows)>max_lines:
            raise ValueError(f"Text overflows scene {scene['key']}: {len(rows)} lines > {max_lines}")
        x,y=xy
        for row in rows:
            d.text((x,y), row, font=f, fill=color); y += round(size*1.33)
        return y
    d.rectangle((0,0,1920,14),fill=green)
    d.text((72,48),'TRUMAN  /  OBSERVED TRAJECTORY',font=font(23,True),fill=green)
    d.text((1670,48),f'{index+1:02d} / {count:02d}',font=font(23,True),fill=muted)
    d.line((72,100,1848,100),fill=line,width=2)
    eyebrow=scene.get('eyebrow') or {'intro':'THE EXPERIMENT','prompt':'THE USER ASKS',
        'fetch':'THE AGENT FETCHES A PAGE','observation':'THE AGENT RESPONDS',
        'tool':'THE AGENT TAKES AN ACTION','error':'A RECORDED PROBLEM',
        'end':'WHAT WE OBSERVED'}.get(scene['kind'],'THE RECORDING')
    d.text((72,135),eyebrow,font=font(23,True),fill=green)
    screenshot = scene.get('screenshot')
    if screenshot:
        block(scene['title'], (72,192), 53, 670, bold=True,max_lines=3)
        if scene.get('page_title'):
            block(scene['page_title'],(72,392),28,630,color=muted,max_lines=3)
        body=scene.get('caption',scene['body'])
        rows=lines_for(body,font(33),630)
        if len(rows)>10:
            body='\n'.join(rows[:9])+ '\n… Full tool result in transcript.'
        scene['display_text']=body
        block(body,(72,530),33,630,max_lines=11)
        d.rounded_rectangle((800,160,1850,975),radius=18,fill='white',outline=line,width=2)
        d.rounded_rectangle((801,161,1849,205),radius=17,fill='#E4EBE5')
        d.text((828,171),urlsplit(scene.get('url','')).netloc,font=font(19),fill=muted)
        shot=Image.open(output/screenshot).convert('RGB')
        shot=ImageOps.contain(shot,(1020,735),method=Image.Resampling.LANCZOS)
        im.paste(shot,(814+(1020-shot.width)//2,216))
        d.text((820,945),'RECORDED PAGE · RE-RENDERED FOR THIS VIDEO',font=font(17,True),fill=muted)
    elif scene['kind']=='intro':
        block(scene['title'],(72,205),72,1640,bold=True,max_lines=3)
        block(scene.get('caption',scene['body']),(76,440),40,1620,max_lines=5)
        for j,(value,label) in enumerate(zip(scene.get('counts',[0,0,0]),['QUESTION','PAGE REQUESTS','FINAL RESPONSE'])):
            x=72+j*606
            d.rounded_rectangle((x,735,x+560,930),radius=18,fill=ink)
            d.text((x+30,752),str(int(value)),font=font(82,True),fill='#B5E3CA')
            d.text((x+30,862),label,font=font(24,True),fill='white')
    elif scene['kind']=='final':
        block(scene['title'],(72,190),52,1650,bold=True,max_lines=2)
        d.rounded_rectangle((72,285,1848,960),radius=20,fill='white',outline=line,width=2)
        block(scene['body'],(114,320),38,1650,max_lines=12)
    else:
        block(scene['title'],(72,205),72,1640,bold=True,max_lines=3)
        y=440 if len(lines_for(scene['title'],font(72,True),1640))<3 else 510
        d.rounded_rectangle((72,y-25,1848,930),radius=20,fill='white',outline=line,width=2)
        block(scene.get('caption',scene['body']),(118,y+15),44,1620,max_lines=7)
    footer=scene.get('footer','Captions summarize recorded actions; no private reasoning is inferred.')
    d.text((72,1009),footer,font=font(20),fill=muted)
    ids=', '.join('#'+str(x) for x in scene.get('event_ids',[]))
    d.text((1500,1009),('Events '+ids) if ids else 'RESEARCH WALKTHROUGH',font=font(18),fill=muted)
    d.rectangle((0,1068,1920,1080),fill=line)
    d.rectangle((0,1068,round(1920*(index+1)/count),1080),fill=green)
    target=output/'frames'/f'{index:03d}.png'; im.save(target)
    return target


def subtitle_time(seconds):
    ms=round(seconds*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def export_player(output, scenes, title):
    buttons=''.join(f'<button onclick="v.currentTime={s["start"]};v.play()">'
                    f'<small>{int(s["start"])//60}:{int(s["start"])%60:02}</small> '
                    f'{html.escape(s["title"])}</button>' for s in scenes)
    transcript=''.join(f'<section><h2>{html.escape(s["title"])}</h2><p>{html.escape(plain(s["body"]))}</p></section>' for s in scenes)
    document='''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Truman trajectory video</title><style>
body{background:#f2f1eb;color:#172c28;font:18px/1.6 system-ui;margin:40px auto;padding:0 24px;max-width:1450px}
h1{font-size:38px}video{width:100%;border-radius:16px;background:#172c28}nav{display:flex;gap:8px;flex-wrap:wrap;margin:24px 0}
button{background:white;border:1px solid #c8d5cc;border-radius:8px;padding:10px;cursor:pointer;color:inherit}small{color:#087f70}
p{white-space:pre-wrap}a{color:#087f70}section{border-top:1px solid #c8d5cc;padding:16px 0}</style>'''
    document+=f'<h1>{html.escape(title)}</h1><p>Captioned walkthrough · screenshots re-rendered from recorded responses · no live websites</p>'
    document+='<video id="v" controls preload="metadata" poster="frames/000.png"><source src="trajectory.webm" type="video/webm"><source src="trajectory.mp4" type="video/mp4"></video>'
    document+=f'<nav>{buttons}</nav><p><a href="trajectory.mp4" download>Download MP4</a> · <a href="final-response.md">Complete original final response</a> · <a href="storyboard.json">Storyboard and event references</a></p>'
    document+='<details><summary>Read the walkthrough transcript</summary>'+transcript+'</details>'
    (output/'index.html').write_text(document)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run',type=Path,help='Recorded run directory, containing run.json and response blobs')
    p.add_argument('--output',required=True,type=Path,help='New output directory; existing directories are refused')
    p.add_argument('--story',type=Path,help='Optional editorial captions keyed by scene key')
    p.add_argument('--style',choices=['walkthrough','abstract'],default='walkthrough')
    p.add_argument('--node',default='node');p.add_argument('--ffmpeg',default='ffmpeg')
    p.add_argument('--wpm',type=int,default=170,help='Reading speed for silent captions')
    p.add_argument('--plan-only',action='store_true');p.add_argument('--frames-only',action='store_true')
    args=p.parse_args()
    if args.wpm<60 or args.wpm>400:p.error('--wpm must be between 60 and 400')
    root=args.run.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    run_bytes=(root/'run.json').read_bytes();run=json.loads(run_bytes)
    scenes=build_plan(run)
    story=json.loads(args.story.read_text()) if args.story else {}
    if args.style=='abstract' and not story.get('beats'):
        p.error('Abstract videos require a story file with short paraphrased beats')
    known={s['key'] for s in scenes}
    if set(story.get('scenes',{}))-known:raise ValueError('Story refers to unknown scene keys')
    for scene in scenes:
        overrides=story.get('scenes',{}).get(scene['key'],{})
        allowed={'title','caption','duration','selector','detail_selector','skip','eyebrow','footer'}
        if set(overrides)-allowed:raise ValueError('Story cannot override evidence fields')
        if scene['kind']=='final' and overrides:raise ValueError('The final response cannot be overridden')
        scene.update(overrides)
    scenes.extend(story.get('after',[]))
    (out/'plan.json').write_text(json.dumps(scenes,ensure_ascii=False,indent=2))
    (out/'final-response.md').write_text(run.get('final_answer',''))
    (out/'recorded-events.json').write_text(json.dumps(run['events'],ensure_ascii=False,indent=2))
    if args.plan_only:
        print(out/'plan.json');return
    for sub in ('assets','frames','segments'):(out/sub).mkdir()
    manifest=prepare_pages(root,out,[s for s in scenes if not s.get('skip')])
    if json.loads(manifest.read_text())['pages']:
        run_command([args.node,Path(__file__).with_name('render-pages.cjs'),manifest])
    if args.style=='abstract':
        from abstract_renderer import render_abstract
        storyboard=render_abstract(run,scenes,story,out,args.ffmpeg,args.frames_only)
        storyboard['source_run_json_sha256']=hashlib.sha256(run_bytes).hexdigest()
        (out/'storyboard.json').write_text(json.dumps(storyboard,ensure_ascii=False,indent=2))
        export_player(out,storyboard['scenes'],story.get('title','The agent’s observed trajectory'))
        print(f'Created {out} ({storyboard["duration_seconds"]:.1f} seconds)',flush=True)
        return
    scenes=paginate(scenes);elapsed=0;subtitles=[]
    for i,scene in enumerate(scenes):
        frame=paint_scene(scene,i,len(scenes),out)
        text=plain(scene.get('display_text',scene.get('caption',scene['body'])))
        duration=max(7,3+len(text.split())*60/args.wpm)
        duration=math.ceil(float(scene.get('duration',duration))*24)/24
        scene.update(start=elapsed,duration=duration,frame=frame.relative_to(out).as_posix())
        subtitles.append(f'{i+1}\n{subtitle_time(elapsed)} --> {subtitle_time(elapsed+duration)}\n{scene["title"]}\n{text}\n')
        elapsed+=duration
        if not args.frames_only:
            run_command([args.ffmpeg,'-hide_banner','-loglevel','error','-loop','1','-i',frame,
                         '-t',str(duration),'-r','24','-vf','fade=t=in:st=0:d=0.2',
                         '-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p',
                         '-an',out/'segments'/f'{i:03d}.mp4'])
        print(f'{i+1}/{len(scenes)} {scene["title"]}',flush=True)
    storyboard={'run_id':run['id'],'source_run_json_sha256':hashlib.sha256(run_bytes).hexdigest(),
                'format':'1920x1080, 24 fps, captions only','duration_seconds':elapsed,
                'screenshot_method':'Offline re-render of recorded HTML; not a screen recording of the agent',
                'run_status':run['status'],'scenes':scenes}
    (out/'storyboard.json').write_text(json.dumps(storyboard,ensure_ascii=False,indent=2))
    (out/'captions.srt').write_text('\n'.join(subtitles))
    if not args.frames_only:
        concat=out/'segments/concat.txt';concat.write_text(''.join(f"file '{i:03d}.mp4'\n" for i in range(len(scenes))))
        chapters=out/'chapters.ffmeta'
        def meta(text):return re.sub(r'([\\=;#])',r'\\\1',text).replace('\n',' ')
        chapters.write_text(';FFMETADATA1\n'+''.join(f'[CHAPTER]\nTIMEBASE=1/1000\nSTART={round(s["start"]*1000)}\nEND={round((s["start"]+s["duration"])*1000)}\ntitle={meta(s["title"])}\n' for s in scenes))
        run_command([args.ffmpeg,'-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',concat,
                     '-i',chapters,'-map_metadata','1','-c','copy','-movflags','+faststart',out/'trajectory.mp4'])
        # Chromium distributions without proprietary H.264 codecs can play VP9.
        run_command([args.ffmpeg,'-hide_banner','-loglevel','error','-i',out/'trajectory.mp4',
                     '-map','0:v:0','-c:v','libvpx-vp9','-b:v','0','-crf','30','-cpu-used','5',
                     '-row-mt','1','-threads','4','-an',out/'trajectory.webm'])
    export_player(out,scenes,story.get('title','The agent’s observed trajectory'))
    print(f'Created {out} ({elapsed:.1f} seconds)',flush=True)


if __name__=='__main__':main()
