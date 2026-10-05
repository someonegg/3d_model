"""Public relief surface preview."""
import numpy as np
from PIL import Image, ImageDraw
from relief import RADIUS

def render(field):
    z=field[::2,::2]
    gy,gx=np.gradient(z,.1,.1)
    normal=np.stack((-gx,gy,np.ones_like(z)),axis=-1)
    normal/=np.linalg.norm(normal,axis=-1)[...,None]
    light=np.array([-.55,.45,.70])
    light/=np.linalg.norm(light)
    shade=.35+.65*np.clip(normal@light,0,1)
    rgb=np.clip(shade[...,None]*[205,171,111],0,255).astype(np.uint8)
    axis=np.linspace(-RADIUS,RADIUS,len(z))
    x,y=np.meshgrid(axis,axis)
    rgb[np.hypot(x,y)>RADIUS]=[246,244,240]
    return Image.fromarray(rgb)


def preview(fields, out):
    images=[render(fields[side]) for side in ('obverse','reverse')]
    width,height=images[0].size
    canvas=Image.new('RGB',(width*2,height+32),'#f6f4f0')
    draw=ImageDraw.Draw(canvas)
    labels=('Obverse | generated surface | 60 mm',
            'Reverse | generated surface | 60 mm')
    for i,(image,label) in enumerate(zip(images,labels)):
        x=i*width
        canvas.paste(image,(x,0))
        draw.text((x+12,height+8),label,fill='#332e27')
    canvas.save(out/'preview.png')


