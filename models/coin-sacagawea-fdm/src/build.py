"""Export independently printable half-coins; only MODEL_OUTPUT_DIR is written."""
from pathlib import Path
import os
import numpy as np
import trimesh
from relief import surface, sample

from geometry import topology
from preview import preview

def main():
    OUT=Path(os.environ['MODEL_OUTPUT_DIR'])
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
    preview(fields, OUT)


if __name__=='__main__':
    main()
