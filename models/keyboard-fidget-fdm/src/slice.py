"""P2S PLA audit of the replacement cartridge and five-piece plate."""
from tools.slicing import slicing_parser, configure_slicing

import manifold3d as mf
import json
from pathlib import Path
import numpy as np
import trimesh
from tools.slicing import audit_files, model_directory, save_report, slicing_workspace, source_hashes
HERE = Path(__file__).resolve().parents[1]

from tools.slicing_geometry import check_archive_geometry, extrusion_segments as _extrusion_segments, require_material, require_clear, deposited_region

def extrusion_segments(gcode, dimensions=False):
    # Machine purge paths precede the first model layer; retain all model heights.
    return _extrusion_segments(gcode, dimensions, require_layer=True)


def inspect_cartridge_paths(gcode, bounds, source):
    """Plate is not rotated or auto-arranged: cartridge at (55,-35)."""
    segments = extrusion_segments(gcode)
    assert segments, 'cartridge missing layer 0.2'
    mesh = trimesh.load(source, force='mesh')
    shift = np.array([bounds['x'], bounds['y']]) - mesh.bounds[0, :2]
    checks = []
    p = json.loads((source.parent/'assembly.json').read_text())['parameters']
    cx = p['click_x']
    center = np.array([55, -35]) + shift
    regions = [('return-arms', np.arange(0.2, 1.01, 0.2), [(side * 5, side * y) for side in (-1, 1) for y in np.linspace(-14, 12, 40)]), ('click-arms', np.arange(0.2, 3.21, 0.2), [(side * cx, y) for side in (-1, 1) for y in np.linspace(-14, 12, 40)]), ('raised-return-pads', np.arange(1.2, 4.21, 0.2), [(5, 13), (-5, -13)]), ('return-roots', np.arange(0.2, 1.01, 0.2), [(5, -17), (-5, 17)]), ('click-roots', np.arange(0.2, 3.21, 0.2), [(-cx, -17), (cx, -17)]), ('thick-contacts', np.arange(0.2, 3.21, 0.2), [(-cx, 13), (cx, 13), (-cx, 16), (cx, 16)])]
    for name, heights, probes in regions:
        for height in np.round(heights, 3):
            paths = [(a, b) for z, a, b, f in segments if z == height and np.all(np.abs((a + b) / 2 - center) < 21)]
            assert paths, f'{name} missing layer {height}'
            starts = np.array([a for a, b in paths])
            vectors = np.array([b - a for a, b in paths])
            for probe in probes:
                point = center + probe
                t = np.clip(np.sum((point - starts) * vectors, axis=1) / np.maximum(np.sum(vectors * vectors, axis=1), 1e-12), 0, 1)
                assert np.min(np.linalg.norm(starts + t[:, None] * vectors - point, axis=1)) < 0.34, f'{name} missing extrusion {height}/{probe}'
            checks.append(dict(feature=name, z_mm=float(height), probes=len(probes), passed=True))
    return checks

def inspect_screw_paths(gcode, bounds, source):
    """Verify continuous boss walls and floor bearing around both blind pilots."""
    metadata = json.loads((source.parent / 'assembly.json').read_text())
    rows = {r['id']:r for r in metadata['parts']}
    mesh = trimesh.load(source, force='mesh')
    shift = np.array([bounds['x'],bounds['y']])-mesh.bounds[0,:2]
    segments = extrusion_segments(gcode)
    checks = []
    for x,y in metadata['parameters']['screw_centers']:
        for name, heights, radius in [('shell',np.arange(.2,16.01,.2),1.8),('base',np.arange(.2,2.41,.2),2.55)]:
            row=rows[name]
            transform=np.array(row['assembly_to_print'])
            # Probe towards the inside of the square, away from the curved outer corner.
            probes=[(x-np.sign(x)*radius,y,0),(x,y-np.sign(y)*radius,0)]
            points=[(transform @ [*probe,1])[:2]+row['plate_xy']+shift for probe in probes]
            for height in np.round(heights,3):
                paths=[(a,b) for z,a,b,f in segments if abs(z-height)<.002]
                assert paths,(name,height)
                starts=np.array([a for a,b in paths]); vectors=np.array([b-a for a,b in paths])
                for point in points:
                    t=np.clip(np.sum((point-starts)*vectors,axis=1)/np.maximum(np.sum(vectors*vectors,axis=1),1e-12),0,1)
                    assert np.min(np.linalg.norm(starts+t[:,None]*vectors-point,axis=1))<.4,(name,height,point.tolist())
                checks.append(dict(feature='screw-bearing' if name=='base' else 'blind-boss',part=name,z_mm=float(height),passed=True))
    return checks

def inspect_guide_paths(gcode, bounds, source):
    """Probe lands, groove floors/voids and both mouths at every printed layer."""
    metadata = json.loads((source.parent / 'assembly.json').read_text())
    rows = {r['id']: r for r in metadata['parts']}
    mesh = trimesh.load(source, force='mesh')
    shift = np.array([bounds['x'], bounds['y']]) - mesh.bounds[0, :2]
    segments = extrusion_segments(gcode)
    checks = []
    for name in ('plunger', 'shell'):
        row = rows[name]
        matrix = np.array(row['assembly_to_print'])
        for height in np.round(np.arange(.2, 8.41 if name == 'plunger' else 7.21, .2), 3):
            # G-code height is the layer top; probe the deposited layer centre.
            assembly_z = (np.linalg.inv(matrix) @ [0, 0, height-.1, 1])[2]
            material, void = [], []
            if name == 'plunger':
                if assembly_z < 11.26:
                    continue
                relief = .4 * max(0, min(1, (assembly_z-11.26)/.6, (18.59-assembly_z)/.6))
                for side in (-1, 1):
                    material += [(side*6.75, y) for y in (-12.2, 12.2)]
                    material += [(x, side*13.75) for x in (-5.2, 5.2)]
                    material += [(side*(7-relief-.25), 0), (0, side*(14-relief-.25))]
                    if relief > .3:
                        void += [(side*6.95, 0), (0, side*13.95)]
                feature = 'guide-lands-and-relief-ramps' if relief < .4 else 'guide-lands-and-grooves'
            else:
                relief = max(0, .4-min(assembly_z-11.25,18.4-assembly_z))
                for side in (-1,1):
                    material += [(side*(7.2+relief+.25),0),(0,side*(14.2+relief+.25))]
                    if relief > .2:
                        void += [(side*7.25,0),(0,side*14.25)]
                feature = 'guide-mouth-chamfer' if relief else 'long-guide-wall'
            paths = [(a,b) for z,a,b,f in segments if abs(z-height)<.002]
            assert paths, (name,height)
            starts = np.array([a for a,b in paths]); vectors = np.array([b-a for a,b in paths])
            def distance(probe):
                point = (matrix @ [*probe,assembly_z,1])[:2] + row['plate_xy'] + shift
                t = np.clip(np.sum((point-starts)*vectors,axis=1)/np.maximum(np.sum(vectors*vectors,axis=1),1e-12),0,1)
                return float(np.min(np.linalg.norm(starts+t[:,None]*vectors-point,axis=1)))
            for probe in material:
                assert distance(probe)<.34, ('guide missing extrusion',name,height,probe,distance(probe))
            for probe in void:
                assert distance(probe)>.22, ('guide relief filled',name,height,probe,distance(probe))
            checks.append(dict(feature=feature,part=name,z_mm=float(height),probes=len(material)+len(void),passed=True))
    return checks

def inspect_support_snap_paths(gcode, bounds, source):
    """Check shelves, open windows and taper at deposited layer centres."""
    metadata=json.loads((source.parent/'assembly.json').read_text())
    p=metadata['parameters']
    mesh=trimesh.load(source,force='mesh')
    shift=np.array([bounds['x'],bounds['y']])-mesh.bounds[0,:2]
    segments=extrusion_segments(gcode)
    checks=[]
    for row in metadata['parts']:
        name=row['id']
        if name not in ('base','shell','cartridge','plunger'):
            continue
        matrix=np.array(row['assembly_to_print'])
        height_max={'base':14.4,'shell':16.,'cartridge':3.2,'plunger':1.0}[name]
        for height in np.round(np.arange(.2,height_max+.01,.2),3):
            z=(np.linalg.inv(matrix)@[0,0,height-.1,1])[2]
            material=[]; void=[]
            for side in (-1,1):
                if name=='base':
                    if 2.4<z<6:
                        material += [(side*p['click_x'],12)]
                    if 6<z<9.4:
                        void += [(side*(p['window_edge']-.3),13)]
                    if 6.2<z<14.4:
                        half=p['snap_stem_half']+(p['snap_head_half']-p['snap_stem_half'])*max(0,1-abs(z-p['snap_peak']))
                        material += [(side*20.05,-11+half-.25)]
                        void += [(side*20.05,-11+half+.35)]
                elif name=='shell' and 2.8<z<14.4:
                    half=p['snap_slot_half']+(p['snap_pocket_half']-p['snap_slot_half'])*np.clip((z-p['snap_transition_bottom'])/(p['snap_transition_top']-p['snap_transition_bottom']),0,1)
                    material += [(side*21.8,-11),(side*20.5,-11+half+.3)]
                    void += [(side*20.05,-11+half-.35)]
                elif name=='plunger':
                    material += [(side*(p['plate_edge']-.25),y) for y in (10.5,-15.45)]
                    void += [(side*(p['plate_edge']+.35),y) for y in (10.5,-15.45)]
                elif name=='cartridge':
                    material += [(side*x,float(y)) for y in np.arange(-17.,17.01,1.) for x in (p['window_edge']+.25, p['window_edge']+p['side_wall']/2, p['frame_half']-.3) if not (x > p['snap_x']-1.25 and -15.25 < y < -6.75) and not (side == -1 and x > 18.7 and abs(y)<3.1)]
                    void += [(side*(p['window_edge']-.3),float(y)) for y in np.arange(-15.,17.01,1.)]
            if not material and not void:
                continue
            paths=[(a,b) for h,a,b,f in segments if abs(h-height)<.002]
            assert paths,(name,height)
            starts=np.array([a for a,b in paths]);vectors=np.array([b-a for a,b in paths])
            def distance(probe):
                point=(matrix@[*probe,z,1])[:2]+row['plate_xy']+shift
                t=np.clip(np.sum((point-starts)*vectors,axis=1)/np.maximum(np.sum(vectors*vectors,axis=1),1e-12),0,1)
                return float(np.min(np.linalg.norm(starts+t[:,None]*vectors-point,axis=1)))
            for probe in material:
                assert distance(probe)<.34,('missing support/snap wall',name,height,probe,distance(probe))
            for probe in void:
                assert distance(probe)>.22,('filled support/window/snap clearance',name,height,probe,distance(probe))
            checks.append(dict(feature='support-window-snap',part=name,z_mm=float(height),probes=len(material)+len(void),passed=True))
    return checks

def inspect_snap_frame_path(shell, base, frame, frame_offset):
    rows = []
    for direction, offsets in [('insert', np.linspace(14.5, 0, 146)), ('extract', np.linspace(0, 14.5, 146))]:
        for dz in offsets:
            moving = shell.translate((0, 0, float(dz)))
            for fx in (-frame_offset, frame_offset):
                for fy in (-frame_offset, frame_offset):
                    require_clear(moving, frame.translate((fx, fy, 0)), f'snap/frame {direction}/{dz}')
            rows.append(dict(direction=direction, offset_mm=float(dz),
                             contact_volume_mm3=max(0., (moving ^ base).volume())))
    return rows


def inspect_contact_envelopes(gcode,bounds,source):
    """Reconstruct the snap and click contact regions in assembly coordinates."""
    import verify
    metadata=json.loads((source.parent/'assembly.json').read_text())
    p=metadata['parameters']
    rows={r['id']:r for r in metadata['parts']}
    mesh=trimesh.load(source,force='mesh')
    shift=np.array([bounds['x'],bounds['y']])-mesh.bounds[0,:2]
    segments=extrusion_segments(gcode,dimensions=True)
    envelopes={}
    def cube(w,d,h,x,y,z):
        return mf.Manifold.cube((w,d,h)).translate((x-w/2,y-d/2,z))
    masks={}
    for name in ('shell','base','plunger','cartridge'):
        mask=mf.Manifold()
        for side in (-1,1):
            if name in ('shell','base'):
                mask+=cube(4,10,13,side*p['snap_x'],-11,2.3)
            else:
                mask+=cube(4.8,8,4,side*14.5,13,6.0 if name=='cartridge' else 8.0)
        masks[name]=mask
        envelopes[name]=deposited_region(segments,rows[name],shift,mask)
    # The frame beside the locating slots is a separate region from the click
    # contacts. Keep both regions: the latter also replaces CAD in check_motion.
    frame_mask=mf.Manifold()
    for side in (-1,1):
        frame_mask+=cube(4,10,p['frame_thickness'],side*p['snap_x'],-11,p['frame_bottom'])
    frame=deposited_region(segments,rows['cartridge'],shift,frame_mask)
    # Two printed layers must carry the .40 mm plateau at the outer peak.
    for side in (-1,1):
        for z in (p['frame_bottom']+.1,p['frame_bottom']+p['frame_thickness']-.1):
            require_material(frame,cube(.12,.3,.04,side*(p['snap_x']-1.7),-11,z),'locating-slot frame')
        for z in (10.95,11.15):
            require_material(envelopes['plunger'],cube(.08,2,.04,side*(p['cam_peak']-.10),13,z),'cam plateau')
        for z in (8.9,9.1,9.3):
            require_material(envelopes['cartridge'],cube(.12,2,.04,side*14.1,13,z),'contact pad')
        require_material(envelopes['base'],cube(.4,.08,.04,side*p['snap_x'],-11+4.05,13.3),'snap head')
        require_clear(envelopes['shell'],cube(.6,8.0,.04,side*20.6,-11,13.4),'snap pocket filled')
    require_clear(envelopes['base'],envelopes['shell'],'seated snap')
    snap_rows=inspect_snap_frame_path(envelopes['shell'],envelopes['base'],frame,p['frame_offset'])
    solids={};meshes={}
    for name,row in rows.items():
        m=trimesh.load(source.parent/row['file'],force='mesh')
        m.apply_transform(np.linalg.inv(row['assembly_to_print']))
        solids[name]=verify.solid(m);meshes[name]=m
    # Retain CAD outside reconstructed regions; only the contact regions below
    # are certified against the toolpath envelope.
    for name in ('plunger','cartridge'):
        solids[name]=(solids[name]-masks[name])+envelopes[name]
        raw=solids[name].to_mesh()
        meshes[name]=trimesh.Trimesh(np.asarray(raw.vert_properties)[:,:3],np.asarray(raw.tri_verts),process=True)
    motion=verify.check_motion(solids,meshes)
    return dict(feature='deposited-contact-envelopes',passed=True,
                widths_mm=[min(r[4] for r in segments),max(r[4] for r in segments)],
                heights_mm=sorted(set(r[5] for r in segments)),
                snap_path=snap_rows,elastic_snap_verified=False,
                motion_samples=motion['verified_samples'],peak_click_mm=motion['peak_click_displacement_mm'],
                method='Measured LINE_WIDTH/LAYER_HEIGHT; circumscribed round capsules; critical regions replaced in CAD; existing complete motion and tolerance sweep')


SLICING = json.loads((Path(__file__).resolve().parents[1] / 'slicing.json').read_text())


def main():
    parser = slicing_parser(HERE, 'keyboard-fidget-slicing')
    args = parser.parse_args()
    root = slicing_workspace(HERE, args.output_dir)
    source = model_directory(HERE)
    files = ['all-parts.stl']
    inputs = source_hashes(source, [*files, 'assembly.json'])
    if configure_slicing(args, root, source, files, inputs, SLICING):
        return


    partial_checks = {}

    def check(archive, config, gcode, plate, path):
        check_archive_geometry(archive, path)
        assert not plate.get('warning_message'), plate.get('warning_message')
        features = {f.lower() for z, a, b, f in extrusion_segments(gcode)}
        assert not any(('support' in f for f in features)), 'support extrusion'
        bridges = [(z,a,b) for z,a,b,f in extrusion_segments(gcode) if 'bridge' in f.lower()]
        assert all(np.linalg.norm(b-a) <= 8.5 for z,a,b in bridges), 'bridge exceeds 8.5 mm screening limit'
        assert 'sparse infill' not in features, 'parts must be solid'
        screw_paths = inspect_screw_paths(gcode, plate['objects'][0]['bbox'], path)
        partial_checks.update(screw_path_checks=screw_paths, supports=False, geometry_matches_source=True)
        envelopes = inspect_contact_envelopes(gcode, plate['objects'][0]['bbox'], path)
        partial_checks.update(contact_envelopes=envelopes)
        return dict(contact_envelopes=envelopes, bridge_segments=len(bridges), maximum_bridge_mm=max((float(np.linalg.norm(b-a)) for z,a,b in bridges),default=0), path_checks=inspect_cartridge_paths(gcode, plate['objects'][0]['bbox'], path) + screw_paths + inspect_guide_paths(gcode, plate['objects'][0]['bbox'], path) + inspect_support_snap_paths(gcode, plate['objects'][0]['bbox'], path))
    try:
        report = audit_files(args.studio, root, source, files, inputs, arrange=SLICING['arrange'], expected=SLICING['expected'], callback=check, collect_only=args.collect_only)
        report.update(status='complete', printer='Bambu Lab P2S', material='PLA Tough+', nozzle_mm=0.4, layer_mm=0.2, supports=False, physical_print_test=False, printable_validation_complete=False,  solid_parts=True)
        if any('Invalid T command (T65535)' not in row for row in report['cli_diagnostics']):
            raise RuntimeError('Unexpected Studio diagnostic: ' + str(report['cli_diagnostics']))
        if report['cli_diagnostics']:
            report['status'] = 'toolpaths-complete-with-cli-diagnostic'
            report['diagnostic_note'] = 'Stock P2S end macro T65535 is logged as invalid by Studio CLI despite exit code 0. Machine end G-code is unchanged; actual printer execution remains unverified.'
    except (RuntimeError, AssertionError, ValueError, OSError) as error:
        save_report(root, dict(status='failed', error=str(error), printable_validation_complete=False, **partial_checks), source, inputs)
        raise
    save_report(root, report, source, inputs)
    print(json.dumps({key: value for key, value in report.items() if key != 'plates'}, ensure_ascii=False))
if __name__ == '__main__':
    main()
