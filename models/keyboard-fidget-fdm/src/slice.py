"""Optional local P2S slicing audit, separate from reproducible geometry builds."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import zipfile
import xml.etree.ElementTree as ET
import numpy as np
import trimesh
from scipy.spatial import cKDTree
from PIL import Image, ImageDraw

HERE=Path(__file__).resolve().parents[1]


sys.path.insert(0, str(HERE.parents[1]))
from tools.slicing import sha, resolve_profiles, run_studio, studio_metadata


def check_archive_geometry(archive, source):
    """Collect mode cannot attach a stale slice to a newer STL."""
    meshes=[]
    for name in archive.namelist():
        if not name.endswith('.model'):
            continue
        for mesh in ET.fromstring(archive.read(name)).findall('.//{*}mesh'):
            vertices=[[float(v.attrib[k]) for k in ('x','y','z')]
                      for v in mesh.findall('./{*}vertices/{*}vertex')]
            faces=[[int(f.attrib[k]) for k in ('v1','v2','v3')]
                   for f in mesh.findall('./{*}triangles/{*}triangle')]
            meshes.append(trimesh.Trimesh(vertices,faces,process=False))
    actual=trimesh.util.concatenate(meshes)
    expected=trimesh.load(source,force='mesh')
    assert len(actual.faces)==len(expected.faces), 'stale sliced mesh topology'
    for m in (actual,expected):
        m.apply_translation(-m.bounds.mean(axis=0))
    np.testing.assert_allclose(actual.extents,expected.extents,atol=2e-5)
    for a,b in ((actual,expected),(expected,actual)):
        distances,_=cKDTree(a.triangles_center).query(b.triangles_center)
        assert max(distances)<2e-5, 'sliced geometry differs from current STL'


def inspect_spring_paths(gcode, output, bounds):
    """Audit first four layers at beam-centre probes; retain toolpath overview."""
    layer=0.; feature=''; relative=True; position=dict(X=0.,Y=0.,Z=0.,E=0.)
    segments=[]
    for line in gcode.splitlines():
        if line.startswith('; Z_HEIGHT:'):
            layer=round(float(line.split(':')[1]),3)
        if line.startswith('; FEATURE:'):
            feature=line.split(':',1)[1].strip()
        words=line.split(';',1)[0].split()
        if not words:
            continue
        if words[0] in ('M82','M83'):
            relative=words[0]=='M83'
        if words[0]=='G92':
            for word in words[1:]:
                if word[0] in position:
                    position[word[0]]=float(word[1:])
        if words[0] not in ('G0','G1'):
            continue
        data={word[0]:float(word[1:]) for word in words[1:] if word[0] in position}
        old=position.copy()
        e=data.get('E',0) if relative else data.get('E',old['E'])-old['E']
        position.update(data)
        if e>0 and ('X' in data or 'Y' in data) and 0<layer<=.8:
            segments.append((layer,np.array([old['X'],old['Y']]),np.array([position['X'],position['Y']]),feature))
    source=trimesh.load(HERE/'all-parts.stl',force='mesh')
    shift=np.array([bounds['x'],bounds['y']])-source.bounds[0,:2]
    checks=[]; canvas=Image.new('RGB',(1400,820),'#f5f2eb'); draw=ImageDraw.Draw(canvas)
    for col,(part,center) in enumerate((('return-spring',(9,18)),('click-spring',(49,18)))):
        center=np.array(center)+shift
        for row,height in enumerate((.2,.4,.6,.8)):
            paths=[(a,b,f) for z,a,b,f in segments if z==height and
                   np.all(np.abs((a+b)/2-center)<15)]
            assert paths, f'{part} missing layer {height}'
            # Continuous centreline coverage over both straight compliant arms.
            if part=='return-spring':
                probes=np.array([(side*x,side*2.6) for side in (-1,1) for x in np.linspace(-10,7,35)])+center
            else:
                # Printed upside down, so assembly Y reverses.
                probes=np.array([(side*11,-y) for side in (-1,1) for y in np.linspace(-10,1,30)])+center
            starts=np.array([a for a,b,f in paths]); vectors=np.array([b-a for a,b,f in paths])
            denom=np.sum(vectors*vectors,axis=1)
            for point in probes:
                t=np.clip(np.sum((point-starts)*vectors,axis=1)/np.maximum(denom,1e-12),0,1)
                distances=np.linalg.norm(starts+t[:,None]*vectors-point,axis=1)
                assert min(distances)<.32, f'{part} discontinuous beam at Z={height}: {point}'
            checks.append(dict(part=part,z_mm=height,beam_probes=len(probes),passed=True))
            origin=np.array([90+col*700,30+row*200]); scale=5.6
            draw.text(tuple(origin),f'{part} | Z {height:.1f} mm',fill='#253846')
            for a,b,f in paths:
                a=(a-center)*scale+origin+[240,105]; b=(b-center)*scale+origin+[240,105]
                color='#b56b2f' if 'wall' in f.lower() else '#277f85'
                draw.line([tuple(a),tuple(b)],fill=color,width=2)
    canvas.save(output/'spring-toolpaths.png')
    return checks


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--studio',default='/Applications/BambuStudio.app/Contents/MacOS/BambuStudio')
    parser.add_argument('--profiles',type=Path,default=Path('/Applications/BambuStudio.app/Contents/Resources/profiles/BBL'))
    parser.add_argument('--output-dir',type=Path,default=HERE.parents[1]/'tmp/keyboard-fidget-slicing')
    parser.add_argument('--collect-only',action='store_true',help='Verify and collect existing externally sliced 3MF outputs')
    args=parser.parse_args(); root=args.output_dir.resolve(); root.mkdir(parents=True,exist_ok=True)
    resolve=resolve_profiles(args.profiles)
    machine=resolve('Bambu Lab P2S 0.4 nozzle')
    process=resolve('0.20mm Standard @BBL P2S')
    filament=resolve('Bambu PLA Basic @BBL P2S')
    process.update(layer_height='0.2',initial_layer_print_height='0.2',wall_loops='3',
                   sparse_infill_density='15%',enable_support='0',brim_type='no_brim',
                   outer_wall_speed=['45','45','45'],inner_wall_speed=['80','80','80'],
                   wall_generator='arachne',detect_thin_wall='0')
    for name,data in [('machine',machine),('process',process),('filament',filament)]:
        (root/f'{name}.json').write_text(json.dumps(data,indent=2)+'\n')
    rows=[]
    logs=[]
    for filename in ('fit-coupon.stl','all-parts.stl'):
        output=root/Path(filename).stem; output.mkdir(exist_ok=True)
        command=[args.studio,'--datadir',str(root/'config'),
                 '--load-settings',f'{root}/machine.json;{root}/process.json',
                 '--load-filaments',str(root/'filament.json'),
                 '--arrange','1','--orient','0','--slice','0','--export-3mf','sliced.3mf',
                 '--outputdir',str(output),str(HERE/filename)]
        print('Slicing '+filename,flush=True)
        if not args.collect_only:
            run_studio(command, output)
        logs.append(output/'studio.log')
        info=json.loads((output/'result.json').read_text()); assert info['return_code']==0
        with zipfile.ZipFile(output/'sliced.3mf') as archive:
            check_archive_geometry(archive,HERE/filename)
            config=json.loads(archive.read('Metadata/project_settings.config'))
            assert config['printer_model']=='Bambu Lab P2S' and config['nozzle_diameter']==['0.4']
            assert config['layer_height']=='0.2' and config['enable_support']=='0'
            for name in ('Metadata/plate_1.png','Metadata/top_1.png'):
                (output/Path(name).name).write_bytes(archive.read(name))
            gcode=archive.read('Metadata/plate_1.gcode').decode()
            (output/'plate.gcode').write_text(gcode)
        plate=info['sliced_plates'][0]
        path_checks=inspect_spring_paths(gcode,root,plate['objects'][0]['bbox']) if filename=='all-parts.stl' else []
        rows.append(dict(path_checks=path_checks,file=filename,sha256=sha(HERE/filename),return_code=0,
                         warning=plate.get('warning_message',''),seconds=plate['total_predication'],
                         filaments=plate['filaments'],features=plate['feature_type_times'],
                         gcode_sha256=hashlib.sha256(gcode.encode()).hexdigest()))
    report=dict(status='complete',printer='Bambu Lab P2S',nozzle_mm=.4,layer_mm=.2,
                first_layer_mm=.2,wall_loops=3,infill_percent=15,supports=False,
                profile_sha256={name:sha(root/f'{name}.json') for name in ('machine','process','filament')},
                plates=rows,physical_print_test=False)
    report.update(studio_metadata(args.studio, logs, collect_only=args.collect_only))
    (HERE/'slicing-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
