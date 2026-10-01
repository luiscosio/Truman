"""Short diagram-led videos driven by operator-authored, event-linked story beats."""
import functools
import json
import math
import subprocess

from PIL import Image, ImageDraw, ImageFont, ImageOps

from trace_video import font_path, lines_for, run_command, subtitle_time

W,H,FPS=1920,1080,24
PAPER='#F4F2EC'; INK='#17332D'; GREEN='#147C68'; MINT='#D8EADB'; AMBER='#E8AD4A'
RED='#AD343E'


@functools.lru_cache(maxsize=32)
def font(size,bold=False):return ImageFont.truetype(font_path(bold),size)


def ease(t):return 1-(1-max(0,min(1,t)))**3


def text(d,value,x,y,size=50,width=1600,fill=INK,bold=False,align='left'):
    for line in lines_for(value,font(size,bold),width):
        xx=x+(width-font(size,bold).getlength(line))/2 if align=='center' else x
        d.text((round(xx),round(y)),line,font=font(size,bold),fill=fill)
        y+=round(size*1.22)
    return y


def agent(d,x,y,t,mood='normal',scale=1):
    """A labeled robot; gestures visualize actions, not hidden thought."""
    y+=math.sin(t*2.5)*5
    r=92*scale
    stroke=max(2,round(6*scale))
    d.line((x,y-r,x,y-r-34*scale),fill=GREEN,width=stroke)
    d.ellipse((x-10*scale,y-r-49*scale,x+10*scale,y-r-29*scale),fill=GREEN)
    for side in (-1,1):
        ear=x+side*(r+9*scale)
        d.rounded_rectangle((ear-12*scale,y-30*scale,ear+12*scale,y+30*scale),radius=6*scale,fill=GREEN)
    d.rounded_rectangle((x-r-7*scale,y-r-7*scale,x+r+7*scale,y+r+7*scale),radius=27*scale,fill=MINT)
    d.rounded_rectangle((x-r,y-r,x+r,y+r),radius=22*scale,fill=GREEN)
    d.rounded_rectangle((x-73*scale,y-59*scale,x+73*scale,y+15*scale),radius=13*scale,fill=INK)
    eye=10*scale;blink=abs(math.sin(t*.9))<.05
    for offset in (-32,32):
        xx=x+offset*scale
        d.rounded_rectangle((xx-eye,y-32*scale,xx+eye,y-(29 if blink else 12)*scale),radius=3*scale,fill='#ADFFD2')
    if mood=='doubt':
        d.line((x-27*scale,y+41*scale,x+24*scale,y+32*scale),fill='white',width=stroke)
        text(d,'?',x+r+18*scale,y-r-50*scale,round(65*scale),100,fill=GREEN,bold=True)
    else:
        for offset in (-24,0,24):
            d.line((x+(offset-6)*scale,y+37*scale,x+(offset+6)*scale,y+37*scale),fill='white',width=stroke)
    text(d,'AI AGENT',x-120*scale,y+r+18*scale,round(23*scale),240*scale,fill=GREEN,bold=True,align='center')


def bubble(d,message,box,tail='down',size=60):
    x,y,w,h=box
    d.rounded_rectangle((x+4,y+8,x+w+4,y+h+8),radius=28,fill='#DDDCD4')
    d.rounded_rectangle((x,y,x+w,y+h),radius=28,fill='white',outline='#CCD9CF',width=2)
    if tail=='down':d.polygon([(x+w*.48,y+h-2),(x+w*.52,y+h-2),(x+w*.5,y+h+33)],fill='white')
    rows=lines_for(message,font(size,True),w-90)
    if len(rows)*size*1.22>h-50:raise ValueError('Abstract caption too long: '+message)
    text(d,message,x+45,y+(h-len(rows)*size*1.22)/2,size,w-90,bold=True,align='center')


def connection(d,a,b,t,color=GREEN):
    d.line((*a,*b),fill='#C9D7CC',width=5)
    p=(t*.7)%1
    x=a[0]+(b[0]-a[0])*p;y=a[1]+(b[1]-a[1])*p
    d.ellipse((x-11,y-11,x+11,y+11),fill=color)


def page_card(im,d,page,box,t,images):
    x,y,w,h=map(round,box)
    d.rounded_rectangle((x+7,y+11,x+w+7,y+h+11),radius=20,fill='#DCDDD5')
    d.rounded_rectangle((x,y,x+w,y+h),radius=20,fill='white',outline='#BFCFC4',width=2)
    d.rounded_rectangle((x,y,x+w,y+60),radius=20,fill=MINT)
    text(d,page['label'],x+24,y+15,25,w-48,bold=True)
    shot=images.get(page['ref'])
    if shot:
        thumb=thumbnail(page['ref'],w-30,h-155,images)
        im.paste(thumb,(x+(w-thumb.width)//2,y+70))
    else:
        text(d,'Recorded response',x+24,y+110,28,w-48)
    d.rounded_rectangle((x+12,y+h-78,x+w-12,y+h-14),radius=12,fill=INK)
    size=34 if w>550 else 27
    text(d,page['finding'],x+25,y+h-65,size,w-50,fill='white',bold=True,align='center')


THUMBS={}
def thumbnail(key,w,h,images):
    cache=(key,w,h)
    if cache not in THUMBS:THUMBS[cache]=ImageOps.contain(images[key],(w,h),method=Image.Resampling.LANCZOS)
    return THUMBS[cache]


def frame(beat,t,index,total,images,elapsed,duration):
    im=Image.new('RGB',(W,H),PAPER);d=ImageDraw.Draw(im)
    text(d,'TRUMAN',60,35,25,300,fill=GREEN,bold=True)
    text(d,'OBSERVED ACTIONS · PARAPHRASED',1110,40,21,740,fill='#6A7B72',align='center')
    kind=beat['kind'];message=beat['text'];u=ease(t/.55)
    if kind=='intro':
        text(d,beat.get('brand','TRUMAN'),90,150,100,1740,fill=GREEN,bold=True,align='center')
        text(d,message,180,310,65,1560,bold=True,align='center')
        text(d,beat.get('subtext',''),280,535,41,1360,fill='#65766D',align='center')
        agent(d,960,815,t,'normal',.7)
    elif kind=='question':
        text(d,'YOU ASK',80,170,28,1760,fill=GREEN,bold=True,align='center')
        bubble(d,message,(260,260,1400,265),size=76)
        agent(d,960,770,t)
        text(d,beat.get('subtext',''),350,570,38,1220,fill='#65766D',align='center')
    elif kind=='reaction':
        bubble(d,message,(370,230+(1-u)*30,1180,260),size=66)
        agent(d,960,760,t,'doubt')
    elif kind=='fetch':
        bubble(d,message,(70,190,690,230),size=55)
        agent(d,360,690,t)
        connection(d,(460,670),(900,595),t)
        page_card(im,d,beat['pages'][0],(920+(1-u)*180,200,850,695),t,images)
    elif kind=='pair':
        text(d,message,90,145,66,1740,bold=True,align='center')
        agent(d,255,660,t)
        for j in range(len(beat['pages'])):
            connection(d,(355,660),(540+j*655,625),t+j*.6)
        for j,page in enumerate(beat['pages']):
            x=540+j*655;shift=(1-ease((t-j*.22)/.6))*180
            page_card(im,d,page,(x+shift,320,590,570),t,images)
    elif kind=='agreement':
        text(d,message,90,160,67,1740,bold=True,align='center')
        for j,page in enumerate(beat['pages']):
            x=85+j*443
            page_card(im,d,page,(x,345+(1-ease((t-j*.15)/.5))*80,420,430),t,images)
            if t>j*.3+.6:
                d.ellipse((x+172,800,x+238,866),fill=GREEN)
                d.line((x+187,832,x+199,844,x+223,819),fill='white',width=7)
        text(d,beat.get('subtext',''),180,920,37,1560,fill='#63796C',align='center')
    elif kind=='conflict':
        text(d,message,90,160,65,1740,bold=True,align='center')
        for j,card in enumerate(beat['cards']):
            x=130+j*990
            d.rounded_rectangle((x,360,x+670,730),radius=30,fill='white',outline='#CAD4C9',width=2)
            text(d,card['label'],x+30,403,30,610,fill=GREEN,bold=True,align='center')
            text(d,card['value'],x+30,520,62,610,bold=True,align='center')
        text(d,'≠',842,470,125,235,fill='#B87920',align='center')
        agent(d,960,862,t,'doubt',.65)
    elif kind=='answer':
        text(d,'THE ANSWER',80,155,28,1760,fill=GREEN,bold=True,align='center')
        bubble(d,message,(190,260,1540,270),size=67)
        if t>1.2:
            progress=ease((t-1.2)/.45)
            d.rounded_rectangle((270,590+(1-progress)*50,1650,770+(1-progress)*50),radius=24,fill=INK)
            text(d,beat['caveat'],315,627+(1-progress)*50,55,1290,fill='#F5D99B',bold=True,align='center')
        agent(d,960,912,t,'doubt',.62)
    elif kind=='verdict':
        d.rounded_rectangle((160,200,1760,890),radius=36,fill='#F4E2E0')
        text(d,beat.get('label','OBSERVED OUTCOME'),240,265,28,1440,fill=RED,bold=True,align='center')
        text(d,message,230,355,88,1460,fill=RED,bold=True,align='center')
        text(d,beat.get('subtext',''),260,495,43,1400,fill=RED,align='center')
        agent(d,960,720,t,'doubt',.65)
    else:raise ValueError('Unknown abstract beat kind: '+kind)
    text(d,'Reconstructed from the recorded run; reactions are paraphrased.',60,1024,20,1530,fill='#77847A')
    ids=', '.join('#'+str(x) for x in beat.get('event_ids',[]))
    text(d,ids,1575,1024,18,285,fill='#77847A',align='center')
    d.rectangle((0,1073,W,1080),fill='#DAE1D5')
    d.rectangle((0,1073,round(W*(elapsed+t)/duration),1080),fill=GREEN)
    return im


def render_abstract(run,source_scenes,story,out,ffmpeg,frames_only=False):
    THUMBS.clear()
    beats=story['beats'];known={s['key']:s for s in source_scenes}
    event_ids={e['id'] for e in run['events']};images={}
    for beat in beats:
        if set(beat.get('event_ids',[]))-event_ids:raise ValueError('Unknown source event in abstract story')
        if not 1<=float(beat['duration'])<=30:raise ValueError('Abstract beats must last 1–30 seconds')
        for page in beat.get('pages',[]):
            source=known.get(page['ref'])
            if not source:raise ValueError('Unknown page reference: '+page['ref'])
            if source.get('screenshot'):
                images[page['ref']]=Image.open(out/source['screenshot']).convert('RGB')
    duration=sum(b['duration'] for b in beats);elapsed=0;chapters=[];srt=[]
    process=None
    if not frames_only:
        process=subprocess.Popen([ffmpeg,'-hide_banner','-loglevel','error','-f','rawvideo',
            '-pix_fmt','rgb24','-s','1920x1080','-r',str(FPS),'-i','pipe:0','-an',
            '-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',
            '-movflags','+faststart',str(out/'trajectory.mp4')],stdin=subprocess.PIPE)
    try:
        for i,beat in enumerate(beats):
            sample=frame(beat,min(2,beat['duration']/2),i,len(beats),images,elapsed,duration)
            sample.save(out/'frames'/f'{i:03d}.png')
            if process:
                for n in range(round(beat['duration']*FPS)):
                    process.stdin.write(frame(beat,n/FPS,i,len(beats),images,elapsed,duration).tobytes())
            body='\n'.join(str(beat[k]) for k in ('brand','text','subtext','caveat') if beat.get(k))
            chapters.append({'key':f'beat-{i+1}','kind':beat['kind'],'title':beat.get('title',beat['text']),
                             'body':body,'start':elapsed,'duration':beat['duration'],'event_ids':beat.get('event_ids',[])})
            srt.append(f'{i+1}\n{subtitle_time(elapsed)} --> {subtitle_time(elapsed+beat["duration"])}\n{body}\n')
            elapsed+=beat['duration'];print(f'{i+1}/{len(beats)} {beat["kind"]}',flush=True)
    finally:
        if process:
            process.stdin.close()
            if process.wait()!=0:raise RuntimeError('Abstract MP4 encoder failed')
    if not frames_only:
        run_command([ffmpeg,'-hide_banner','-loglevel','error','-i',out/'trajectory.mp4',
            '-c:v','libvpx-vp9','-b:v','0','-crf','32','-cpu-used','6','-row-mt','1','-threads','4','-an',out/'trajectory.webm'])
    (out/'captions.srt').write_text('\n'.join(srt))
    (out/'editorial-story.json').write_text(json.dumps(story,ensure_ascii=False,indent=2))
    return {'run_id':run['id'],'style':'abstract','duration_seconds':duration,
            'format':'1920x1080, 24 fps, captions only','run_status':run['status'],
            'disclosure':'Short operator-authored paraphrases, not literal thoughts or quotations. Full original response in final-response.md.',
            'scenes':chapters}
