"""Surface preview from the same sampled coin height field."""
import numpy as np
from PIL import Image, ImageDraw
from geometry import RADIUS, DIAMETER, heights

def preview(out, fields):
    # Orthographic surface rendering from the SAME height function as the STL.
    size = 720
    extent = RADIUS + 1
    axis = np.linspace(-extent,extent,size)
    x,y = np.meshgrid(axis,-axis)
    canvas = Image.new('RGB',(size*2, size+50),'#f4f2ee')
    for k,side in enumerate(('obverse','reverse')):
        z = heights(x,y,side,fields)
        dy,dx = np.gradient(z,2*extent/(size-1))
        normal = np.stack((-dx,dy,np.ones_like(z)),axis=-1)
        normal /= np.linalg.norm(normal,axis=-1)[...,None]
        light = np.array([-0.4,0.5,0.76]); light /= np.linalg.norm(light)
        shade = .34+.66*np.clip(normal@light,0,1)
        rgb = np.clip(shade[...,None]*np.array([208,174,108]),0,255).astype('uint8')
        rgb[np.hypot(x,y)>RADIUS] = [244,242,238]
        canvas.paste(Image.fromarray(rgb),(k*size,0))
    ImageDraw.Draw(canvas).text((25,size+8),f'STL surface preview | {DIAMETER:g} mm | reconstructed face / simplified eagle relief',fill='#343434')
    canvas.save(out/'preview.png')


