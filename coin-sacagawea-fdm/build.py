"""Export independently printable half-coins; only MODEL_OUTPUT_DIR is written."""
from pathlib import Path
import os
import numpy as np
import trimesh
from PIL import Image, ImageDraw
from relief import surface, sample

SOURCE=Path(__file__).resolve().parent
OUT=Path(os.environ.get('MODEL_OUTPUT_DIR',SOURCE))


def topology(rings=250,sectors=1440):
    theta=np.arange(sectors)*2*np.pi/sectors
    r=np.arange(1,rings+1)*30/rings
    xy=np.vstack(([0,0],np.column_stack(((r[:,None]*np.cos(theta)).ravel(),
                                        (r[:,None]*np.sin(theta)).ravel()))))
    j=np.arange(sectors)
    faces=[np.column_stack((np.zeros(sectors,int),1+j,1+(j+1)%sectors))]
    for k in range(rings-1):
        a,b=1+k*sectors+j,1+k*sectors+(j+1)%sectors
        c,d=a+sectors,b+sectors
        faces.extend((np.column_stack((a,c,d)),np.column_stack((a,d,b))))
    edge=np.arange(1+(rings-1)*sectors,1+rings*sectors)
    n=len(xy)
    a,b=edge,np.roll(edge,-1)
    c,d=n+j,n+(j+1)%sectors
    faces.extend((np.column_stack((a,c,d)),np.column_stack((a,d,b)),
                  np.column_stack((np.full(sectors,n+sectors),d,c))))
    return xy,edge,np.vstack(faces)


def render(field):
    z=field[::2,::2]
    gy,gx=np.gradient(z,.1,.1)
    normal=np.stack((-gx,gy,np.ones_like(z)),axis=-1)
    normal/=np.linalg.norm(normal,axis=-1)[...,None]
    light=np.array([-.55,.45,.70])
    light/=np.linalg.norm(light)
    shade=.35+.65*np.clip(normal@light,0,1)
    rgb=np.clip(shade[...,None]*[205,171,111],0,255).astype(np.uint8)
    axis=np.linspace(-30,30,len(z))
    x,y=np.meshgrid(axis,axis)
    rgb[np.hypot(x,y)>30]=[246,244,240]
    return Image.fromarray(rgb)


def preview(fields):
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
    canvas.save(OUT/'preview.png')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    xy,edge,faces=topology()
    fields={}
    for side in ('obverse','reverse'):
        field=surface(side)
        fields[side]=field
        vertices=np.vstack((np.column_stack((xy,sample(field,xy[:,0],xy[:,1]))),
                            np.column_stack((xy[edge],np.zeros(len(edge)))),[0,0,0]))
        mesh=trimesh.Trimesh(vertices=vertices,faces=faces,process=False)
        if not (mesh.is_watertight and mesh.is_winding_consistent and mesh.volume>0):
            raise ValueError(f'{side} mesh failed build integrity checks')
        if not np.all(mesh.area_faces>1e-12):
            raise ValueError(f'{side} mesh contains degenerate triangles')
        mesh.export(OUT/f'coin-sacagawea-fdm-{side}.stl')
        print(side,mesh.extents.tolist(),flush=True)
    preview(fields)


if __name__=='__main__':
    main()
