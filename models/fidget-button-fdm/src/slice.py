"""P2S Tough+ audit; check roots, long arms and independent pads layer by layer."""
from tools.slicing import slicing_parser, configure_slicing

import json
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
import trimesh
from tools.slicing import audit_files, model_directory, save_report, slicing_workspace, source_hashes
from geometry import P, SPRING_THICKNESS, GUIDE_HEIGHT
HERE = Path(__file__).resolve().parents[1]
from tools.slicing_geometry import check_archive_geometry, extrusion_segments

SLICING = json.loads((Path(__file__).resolve().parents[1] / 'slicing.json').read_text())


def main():
    parser = slicing_parser(HERE, 'fidget-button-slicing')
    args = parser.parse_args()
    source = model_directory(HERE)
    root = slicing_workspace(HERE, args.output_dir)
    files = ['fidget-button-fdm.stl']
    inputs = source_hashes(source, files)
    if configure_slicing(args, root, source, files, inputs, SLICING):
        return

    def check(archive, config, gcode, plate, path):
        check_archive_geometry(archive,path)
        assert not plate.get('warning_message'), plate.get('warning_message')
        segments = extrusion_segments(gcode)
        m=trimesh.load(path,force='mesh')
        root_model=ET.fromstring(archive.read('3D/3dmodel.model'))
        item=root_model.find('.//{*}build/{*}item')
        transform=np.array([float(v) for v in item.attrib['transform'].split()]).reshape(4,3)
        assert np.allclose(transform[2], [0,0,1]), 'unexpected plate tilt'
        checks=[]
        regions=[('arms',np.arange(.2,SPRING_THICKNESS+.01,.16),[(-29+side*x,48+side*P['pad_y']) for side in (-1,1) for x in np.linspace(-12.5,10,46)]),('roots',np.arange(.2,SPRING_THICKNESS+.01,.16),[(-29+side*-13.5,48+side*P['pad_y']) for side in (-1,1)]),('guide',np.arange(1.32,GUIDE_HEIGHT,.16),[(-29+side*15.5,48) for side in (-1,1)]),('pads',np.arange(.2+.16*np.ceil((P['skirt_top']-.2)/.16),P['pusher_height'],.16),[(32+side*P['pad_x'],-25-side*P['pad_y']) for side in (-1,1)])]
        for name,heights,probes in regions:
            for height in np.round(heights,3):
                paths=[(a,b) for z,a,b,f in segments if abs(z-height)<.002]
                assert paths, (name,height)
                starts=np.array([a for a,b in paths]); vectors=np.array([b-a for a,b in paths])
                for probe in probes:
                    point=(np.array([*probe,0,1]) @ transform)[:2]
                    t=np.clip(np.sum((point-starts)*vectors,axis=1)/np.maximum(np.sum(vectors*vectors,axis=1),1e-12),0,1)
                    assert np.min(np.linalg.norm(starts+t[:,None]*vectors-point,axis=1))<.35,(name,height,probe)
                checks.append(dict(feature=name,z_mm=float(height),passed=True))
        # Continuous broad lock lobes at their center and flanks, both parts.
        for feature, center, radius, heights in (
            ('base_lobes', (32,26),17.35,(3.08,3.56,4.04)),
            ('shell_lobes',(-31,0),17.4,(15.4,15.88,16.36))):
            for height in heights:
                paths=[(a,b) for z,a,b,f in segments if abs(z-height)<.002]
                assert paths, (feature,height)
                starts=np.array([a for a,b in paths]); vectors=np.array([b-a for a,b in paths])
                for degrees in range(0,360,60):
                    for flank in (-5,0,5):
                        angle=np.radians(degrees+flank)
                        probe=np.array([center[0]+radius*np.cos(angle),center[1]+radius*np.sin(angle),0,1])
                        point=(probe @ transform)[:2]
                        t=np.clip(np.sum((point-starts)*vectors,axis=1)/np.maximum(np.sum(vectors*vectors,axis=1),1e-12),0,1)
                        assert np.min(np.linalg.norm(starts+t[:,None]*vectors-point,axis=1))<.35,(feature,height,degrees,flank)
                checks.append(dict(feature=feature,z_mm=height,passed=True))
        # No extrusion centerline may cross the middle of a free-tip gap.
        for height in np.round(np.arange(.2,SPRING_THICKNESS+.01,.16),3):
            paths=[(a,b) for z,a,b,f in segments if abs(z-height)<.002]
            starts=np.array([a for a,b in paths]); vectors=np.array([b-a for a,b in paths])
            for side in (-1,1):
                point=(np.array([-29+side*((P['arm_tip']+13.1)/2),48+side*P['pad_y'],0,1]) @ transform)[:2]
                t=np.clip(np.sum((point-starts)*vectors,axis=1)/np.maximum(np.sum(vectors*vectors,axis=1),1e-12),0,1)
                assert np.min(np.linalg.norm(starts+t[:,None]*vectors-point,axis=1))>.3,('free_tip_gap',height,side)
            checks.append(dict(feature='free_tip_gap',z_mm=height,passed=True))
        assert not any('support'  in f.lower() for z,a,b,f in segments)
        return dict(path_checks=checks,bridge_segments=sum('bridge' in f.lower() for z,a,b,f in segments))
    try:
        report=audit_files(args.studio,root,source,files,inputs,arrange=SLICING['arrange'],expected=SLICING['expected'],callback=check,collect_only=args.collect_only)
        report.update(status='complete',material='PLA Tough+',physical_print_test=False)
    except Exception as error:
        save_report(root,dict(status='failed',error=str(error)),source,inputs)
        raise
    save_report(root,report,source,inputs)
    print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':
    main()
