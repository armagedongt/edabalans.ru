"""Only visually inspected photos; diagrams and text screenshots stay lossless."""
from pathlib import Path
import json
from PIL import Image, ImageOps

ROOT=Path(__file__).resolve().parents[2]
base=ROOT/'content/blog/media'
sources=['12237133/'+f'{n:02d}.'+('png' if n in [10,18] else 'jpg') for n in [1,3,4,5,6,7,8,9,10,12,13,14,16,17,18]]
sources+=['11927800/tilda-01.jpg','11927800/tilda-05.png','11927800/tilda-07.png','11927800/tilda-08.jpg','11269472/01.jpg']
manifest_path=ROOT/'content/blog/manifest.json'
manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
report=[]
for name in sources:
    original=base/name
    stem=str(Path(name).with_suffix('')).replace('\\','/')
    replacements={name,stem+'-v2-body.webp'}
    target_name=stem+'-v3-photo.webp'
    with Image.open(original) as image:
        photo=ImageOps.exif_transpose(image).convert('RGB')
        if photo.width>1520:
            photo=ImageOps.contain(photo,(1520,round(photo.height*1520/photo.width)),Image.Resampling.LANCZOS)
        photo.save(base/target_name,format='WEBP',quality=88,method=6)
    article=next(a for a in manifest['articles'] if a['source_id']==name.split('/')[0])
    path=ROOT/'content/blog/articles'/article['body_file']
    text=path.read_text(encoding='utf-8')
    for current in replacements:
        text=text.replace('/blog/media/'+current+')','/blog/media/'+target_name+')')
    path.write_text(text,encoding='utf-8')
    if article['hero']['file'] in replacements:
        article['hero']['file']=target_name
    if article['card']['file'] in replacements|{stem+'-v2-card.webp'}:
        card_name=stem+'-v3-card.webp'
        card=ImageOps.contain(photo,(760,round(photo.height*760/photo.width)),Image.Resampling.LANCZOS) if photo.width>760 else photo
        card.save(base/card_name,format='WEBP',quality=88,method=6)
        article['card']['file']=card_name
        article['media'].append(card_name)
    article['media']=sorted(set(article['media']+[target_name,name]))
    report.append({'original':name,'derivative':target_name,'before_bytes':original.stat().st_size,'after_bytes':(base/target_name).stat().st_size,'width':photo.width,'height':photo.height,'quality':88,'visual_classification':'photo inspected in contact sheet','crop':'none'})
manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(Path(__file__).parent/'photo-optimization.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(sum(r['before_bytes'] for r in report),sum(r['after_bytes'] for r in report))
