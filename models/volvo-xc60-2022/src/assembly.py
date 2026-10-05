"""Ten-stage assembly guide using the printable meshes and illustrative hardware."""
import json
import math
import struct
import numpy as np
from tools.assembly_gltf import AssemblyWriter
from geometry import P, COLORS, AXLES, mesh, cyl, union

DURATION = 80
TITLES = ['清理与试配', '安装车窗与天窗', '安装车壳装饰', '组装左右前门', '安装前门与门销',
          '安装 B 柱定位片', '安装内饰', '安装轮轴', '合拢底盘并安装螺钉', '功能检查']
HINTS = [
    '先打印配合试打件，清理支撑与孔边毛刺。左右按驾驶席朝车头区分；动画演示顺序与定位，不模拟胶合、自攻或弹性受力。',
    '窗片按内侧台阶定位，仅涂少量胶；天窗盖嵌入车顶浅槽。窗片为不透明 PLA。',
    '先装格栅底板再装银色格栅；灯组、号牌与行李架试配后粘合。',
    '各门依次安装前侧窗、内饰板和后视镜；不要给活动铰链上胶。',
    '铰链叶片对准固定座，从下方穿入两根 1.5 × 20 mm 外购金属销；只固定销的一端。',
    '从车内插入 B 柱定位片，细弹片朝门内饰板；活动接触面禁胶，阻力过大时修薄接触端。',
    '座椅按底盘定位柱落位，随后安装仪表台；方向盘位于左侧。',
    '四只轴套位于轴承座与轮毂之间。穿入两根 2 × 77 mm 外购轮轴，固定轮毂后试滚，再粘轮胎与轮毂盖；轴与底盘、轴套禁胶。',
    '合拢底盘，从下方安装四颗外购 M2 × 6 mm 自攻螺钉，头径不大于 4 mm；拧到贴合即可。',
    '检查双前门 0–60°开合和轮轴滚动。后门、尾门与机盖固定，前轮不转向；实物试打尚未记录。']


def xyz(v):
    x, y, z = v
    return [x / 1000, z / 1000, -y / 1000]


def write_assembly(parts, path):
    writer = AssemblyWriter(DURATION)
    data, track = writer.data, writer.track

    targets = [[] for _ in TITLES]
    markers = [(0, 0, 40), (0, 0, 64), (-85, 0, 28), (-10, 97, 40),
               (*P['hinge_xy_mm'], 37), (10, 30, 35), (9, 0, -35),
               (AXLES[0], 25, P['wheel_radius_mm']-65), (-82, -24, 11), (0, 32, 40)]
    def group(name, parent=0, pivot=(0, 0, 0)):
        index = len(data['nodes'])
        data['nodes'].append(dict(name=name, children=[], translation=xyz(pivot)))
        data['nodes'][parent]['children'].append(index)
        return index

    # The chassis assembly remains below the shell until step nine.
    chassis_group = group('chassis-assembly')
    track(chassis_group, 'translation', [0, 64, 69, 80],
          [xyz((0, 0, -65)), xyz((0, 0, -65)), xyz((0, 0, 0)), xyz((0, 0, 0))], 'VEC3')
    doors = {}
    for side, suffix in [(1, 'left'), (-1, 'right')]:
        pivot = (P['hinge_xy_mm'][0], side*P['hinge_xy_mm'][1], 0)
        node = group('door-assembly-'+suffix, pivot=pivot)
        doors[suffix] = (node, pivot)
        track(node, 'translation', [0, 32, 35, 80],
              [xyz(np.array(pivot)+(0, side*65, 0)), xyz(np.array(pivot)+(0, side*65, 0)), xyz(pivot), xyz(pivot)], 'VEC3')
        angle = side*math.radians(P['door_open_deg'])/2
        track(node, 'rotation', [0, 72, 74, 76, 80],
              [[0,0,0,1], [0,0,0,1], [0,math.sin(angle),0,math.cos(angle)], [0,0,0,1], [0,0,0,1]], 'VEC4')
    wheels = {}
    for i, x in enumerate(AXLES):
        pivot = (x, 0, P['wheel_radius_mm'])
        node = group('wheel-assembly-'+str(i), chassis_group, pivot)
        wheels[i] = (node, pivot)
        # Quarter-turn keys avoid quaternion interpolation taking the shortest full-turn path.
        times = [0, 76, 76.5, 77, 77.5, 78, 80]
        values = [[0,0,0,1]]*2 + [[0,0,-math.sin(a/2),math.cos(a/2)] for a in [math.pi/2,math.pi,3*math.pi/2,2*math.pi]] + [[0,0,0,-1]]
        track(node, 'rotation', times, values, 'VEC4')

    rows = list(parts)
    for side, suffix in [(1, 'left'), (-1, 'right')]:
        rows.append(dict(name='hardware-pin-'+suffix, solid=cyl(P['hinge_pin_mm']/2,20,
                         (P['hinge_xy_mm'][0],side*P['hinge_xy_mm'][1],37)), color='silver', group='hardware-pin'))
    for i,x in enumerate(AXLES):
        rows.append(dict(name='hardware-axle-'+str(i), solid=cyl(P['axle_mm']/2,77,(x,0,P['wheel_radius_mm']),'y'), color='silver', group='hardware-axle'))
    for i,(x,y) in enumerate([(-82,-24),(-82,24),(84,-24),(84,24)]):
        rows.append(dict(name='hardware-screw-'+str(i), solid=union(cyl(1,6,(x,y,13.4)),cyl(2,1.2,(x,y,9.8))),color='silver',group='hardware-screw'))

    for part in rows:
        name = part['name']
        parent, pivot = 0, (0,0,0)
        offset = np.zeros(3)
        step, delay = 0, 0
        if part['group'].startswith('door-'):
            suffix = part['group'][5:]
            parent,pivot = doors[suffix]
            step = 4 if name == 'door-'+suffix else 3
            if step == 3:
                side = 1 if suffix == 'left' else -1
                offset = np.array((0, -side*20 if name.startswith('door-card') else side*20, 0))
                delay = 0 if name.startswith('glass') else 1.6 if name.startswith('door-card') else 3.2
        elif name == 'body':
            step = 0
        elif name.startswith('door-clip'):
            step = 5; offset = np.array((0, -25 if name.endswith('left') else 25, 0))
        elif name in ('chassis','interior','dashboard'):
            parent = chassis_group
            step = 0 if name == 'chassis' else 6
            if step == 6:
                offset = np.array((0,0,40 if name == 'interior' else 70)); delay = 0 if name == 'interior' else 3
        elif part['group'] == 'wheel' or part['group'] == 'hardware-axle':
            i = int(name.split('-')[-1] if part['group'] == 'hardware-axle' else name.split('-')[-2])
            # Spacers remain stationary when the axle rotates.
            parent,pivot = (chassis_group,(0,0,0)) if name.startswith('axle-spacer') else wheels[i]
            step = 7
            side = 1 if name.endswith('left') or part['group'] == 'hardware-axle' else -1
            offset = np.array((0,side*(90 if part['group']=='hardware-axle' else 38),0))
            delay = 0 if name.startswith('axle-spacer') else 1 if name.startswith('hardware') else 2 if name.startswith('rim') else 3.5 if name.startswith('tyre') else 4.5
        elif part['group'] == 'hardware-pin':
            step = 4; delay = 3; offset = np.array((0,0,-35))
        elif part['group'] == 'hardware-screw':
            step = 8; delay = 5; offset = np.array((0,0,-32))
        else:
            step = 1 if name.startswith('glass-') or name in ('windshield','rear-window','panoramic-roof') else 2
            bounds = np.asarray(part['solid'].bounding_box()).reshape(2,3)
            center = bounds.mean(0)
            if name.startswith('glass-'): offset = np.array((0,25 if center[1]>0 else -25,0))
            elif name in ('windshield','rear-window'): offset = np.array((-30 if name=='windshield' else 30,0,12))
            elif name == 'panoramic-roof' or name.startswith('roof-rail'): offset = np.array((0,0,35))
            else: offset = np.array((-35 if center[0]<0 else 35,0,0))
            delay = 0 if name == 'grille-backing' else 2 if name == 'grille-silver' else 1
        targets[step].append(name)
        obj = mesh(part['solid'])
        vertices = np.array([xyz(v-np.array(pivot)) for v in obj.vertices])
        normals = np.asarray(obj.vertex_normals)[:, [0,2,1]].copy(); normals[:,2] *= -1
        rgba = [float(v)/255 for v in COLORS[part['color']]]
        index = writer.mesh(name, vertices, normals, obj.faces, rgba,
                            metallic=.55 if name.startswith('hardware') else 0)
        node = len(data['nodes'])
        data['nodes'].append(dict(name=name,mesh=index,translation=xyz(offset),extras={'hardware':name.startswith('hardware')}))
        data['nodes'][parent]['children'].append(node)
        if np.any(offset):
            start = step*8+delay
            end = start+(1 if name.startswith('hardware-screw') else 1.5)
            track(node,'translation',[0,start,end,80],[xyz(offset),xyz(offset),[0,0,0],[0,0,0]],'VEC3')
    targets[0] = ['body','chassis']
    targets[4] += ['door-assembly-left','door-assembly-right']
    targets[8] += ['chassis-assembly']
    targets[9] = ['door-assembly-left','door-assembly-right','wheel-assembly-0','wheel-assembly-1']
    for i,title in enumerate(TITLES):
        data['scenes'][0]['extras']['assembly']['steps'].append(dict(title=title,hint=HINTS[i],targets=targets[i],start=i*8,end=i*8+7,
            marker=xyz(markers[i]),markerRadius=.002,transparentTargets=['body'] if 4<=i<=8 else [],opacity=.18))
    writer.write(path)


def verify_assembly(path, assembled):
    """Read the final binary and independently recover hierarchy and animated poses."""
    import trimesh
    raw = path.read_bytes()
    magic, version, length = struct.unpack_from('<4sII', raw)
    assert (magic, version, length) == (b'glTF', 2, len(raw))
    size, kind = struct.unpack_from('<II', raw, 12)
    assert kind == 0x4E4F534A
    data = json.loads(raw[20:20+size])
    binary = raw[28+size:]

    def values(index):
        row = data['accessors'][index]; view = data['bufferViews'][row['bufferView']]
        width = {'SCALAR':1,'VEC3':3,'VEC4':4}[row['type']]
        return np.frombuffer(binary, dtype='<f4' if row['componentType']==5126 else '<u4',
            count=row['count']*width, offset=view.get('byteOffset',0)+row.get('byteOffset',0)).reshape(-1,width)

    guide = data['scenes'][0]['extras']['assembly']
    assert guide['version']==1 and guide['duration']==80 and len(guide['steps'])==10
    nodes = data['nodes']; named = {n['name']:i for i,n in enumerate(nodes)}
    exported = {n['name'] for n in nodes if 'mesh' in n and not n.get('extras',{}).get('hardware')}
    assert exported == set(assembled) and len(exported)==52
    metadata=json.loads((path.parent/'assembly.json').read_text())
    for row in metadata['parts']:
        node=nodes[named[row['name']]]
        primitive=data['meshes'][node['mesh']]['primitives'][0]
        actual=data['materials'][primitive['material']]['pbrMetallicRoughness']['baseColorFactor']
        np.testing.assert_allclose(actual,np.array(COLORS[row['color']])/255,atol=1e-8)
    assert sum(n.get('extras',{}).get('hardware',False) for n in nodes)==8
    assert len(data['animations'])==1
    tracks = {}
    for channel in data['animations'][0]['channels']:
        sampler = data['animations'][0]['samplers'][channel['sampler']]
        times, poses = values(sampler['input']).ravel(), values(sampler['output'])
        assert np.isfinite(poses).all() and np.all(np.diff(times)>0)
        assert times[0]==0 and times[-1]==80 and len(times)==len(poses)
        key = (channel['target']['node'],channel['target']['path'])
        assert key not in tracks
        tracks[key] = (times,poses)
    parents = {child:i for i,n in enumerate(nodes) for child in n.get('children',[])}

    def matrices(time):
        result = {}
        def world(i):
            if i in result: return result[i]
            props = {k:np.array(nodes[i].get(k,default),dtype=float) for k,default in
                     [('translation',[0,0,0]),('rotation',[0,0,0,1])]}
            for prop in props:
                if (i,prop) not in tracks: continue
                times,poses = tracks[i,prop]
                j = min(max(np.searchsorted(times,time,side='right')-1,0),len(times)-2)
                weight = np.clip((time-times[j])/(times[j+1]-times[j]),0,1)
                a,b = poses[j].copy(),poses[j+1].copy()
                if prop=='rotation' and np.dot(a,b)<0: b=-b
                props[prop] = a*(1-weight)+b*weight
            q=props['rotation']; q=q/np.linalg.norm(q)
            tf=trimesh.transformations.quaternion_matrix(q[[3,0,1,2]])
            tf[:3,3]=props['translation']
            result[i] = world(parents[i])@tf if i in parents else tf
            return result[i]
        for i in range(len(nodes)): world(i)
        return result

    def points(name, transforms):
        node = nodes[named[name]]
        primitive = data['meshes'][node['mesh']]['primitives'][0]
        return trimesh.transform_points(values(primitive['attributes']['POSITION']),transforms[named[name]])

    from geometry import solid as to_solid, open_door
    def exported_solid(name, transforms):
        node=nodes[named[name]]
        primitive=data['meshes'][node['mesh']]['primitives'][0]
        vertices=points(name,transforms)*1000
        vertices=vertices[:,[0,2,1]]; vertices[:,1]*=-1
        return to_solid(trimesh.Trimesh(vertices,values(primitive['indices']).reshape(-1,3),process=False))

    # Boolean geometry comparison tolerates STL retriangulation of planar faces.
    for time in [71,80]:
        transforms=matrices(time)
        for name,expected in assembled.items():
            actual=exported_solid(name,transforms)
            np.testing.assert_allclose(actual.bounding_box(),expected.bounding_box(),atol=.01)
            assert (actual-expected).volume()+(expected-actual).volume()<.05,(name,time)
    opened=matrices(74)
    for suffix,side in [('left',1),('right',-1)]:
        for name,part in assembled.items():
            if name in ('door-'+suffix,'glass-front-'+suffix,'door-card-'+suffix,'mirror-'+suffix):
                expected=open_door(part,side,60); actual=exported_solid(name,opened)
                assert (actual-expected).volume()+(expected-actual).volume()<.05,name
    for i,x in enumerate(AXLES):
        for time in [76.5,77,77.5,78]:
            tf=matrices(time)
            angle=(time-76)*math.pi
            expected=trimesh.transformations.rotation_matrix(angle,[0,0,-1])
            np.testing.assert_allclose(tf[named['wheel-assembly-'+str(i)]][:3,:3],expected[:3,:3],atol=1e-7)
            np.testing.assert_allclose(tf[named['wheel-assembly-'+str(i)]][:3,3],xyz((x,0,P['wheel_radius_mm'])),atol=1e-8)
            np.testing.assert_allclose(tf[named['axle-spacer-'+str(i)+'-left']],matrices(71)[named['axle-spacer-'+str(i)+'-left']],atol=1e-8)
    for i,step in enumerate(guide['steps']):
        assert 'part' not in step
        assert step['start']==i*8 and step['end']==i*8+7
        assert all(name in named for name in step['targets']+step['transparentTargets'])
    covered=set(name for step in guide['steps'][:9] for name in step['targets'])
    assert exported <= covered
    # Hardware is dimensioned from the same mounting parameters, never printable output.
    installed=matrices(71)
    for name,length,diameter,axis in [(f'hardware-pin-{s}',20,1.5,1) for s in ['left','right']]+[(f'hardware-axle-{i}',77,2,2) for i in range(2)]:
        extents=np.ptp(points(name,installed),axis=0)*1000
        assert abs(extents[axis]-length)<.001
        assert abs(max(np.delete(extents,axis))-diameter)<.001
        center=points(name,installed).mean(axis=0)
        if name.startswith('hardware-pin'):
            side=1 if name.endswith('left') else -1
            expected=xyz((P['hinge_xy_mm'][0],side*P['hinge_xy_mm'][1],37))
        else:
            expected=xyz((AXLES[int(name[-1])],0,P['wheel_radius_mm']))
        np.testing.assert_allclose(center,expected,atol=1e-7)
    for i,(x,y) in enumerate([(-82,-24),(-82,24),(84,-24),(84,24)]):
        bounds=np.array([points('hardware-screw-'+str(i),installed).min(0),points('hardware-screw-'+str(i),installed).max(0)])
        np.testing.assert_allclose(bounds[:,[0,2]].mean(0),[x/1000,-y/1000],atol=1e-7)
        np.testing.assert_allclose(bounds[:,1],[.0092,.0164],atol=1e-7)
    # Sample exported translation paths against settled geometry. Threads and
    # designed flexible door-clip contacts are not rigid interference tests.
    from geometry import solid as to_solid
    path_checks = []
    for (node_index,prop),(times,poses) in tracks.items():
        if prop != 'translation': continue
        for segment in range(len(times)-1):
            if np.allclose(poses[segment],poses[segment+1]): continue
            moving_names = []
            for name in exported:
                ancestor = named[name]
                while ancestor != node_index and ancestor in parents: ancestor = parents[ancestor]
                if ancestor == node_index: moving_names.append(name)
            if not moving_names: continue
            maximum = 0.; collision_pair = None
            for fraction in [.25,.5,.75]:
                time = float(times[segment]+fraction*(times[segment+1]-times[segment]))
                tf = matrices(time)
                cache = {}
                def shape(name):
                    if name not in cache:
                        node = nodes[named[name]]
                        primitive = data['meshes'][node['mesh']]['primitives'][0]
                        obj = trimesh.Trimesh(points(name,tf)*1000,values(primitive['indices']).reshape(-1,3),process=False)
                        cache[name] = to_solid(obj)
                    return cache[name]
                for name in moving_names:
                    bounds = np.array(shape(name).bounding_box()).reshape(2,3)
                    for other in exported-set(moving_names):
                        if name.startswith('door-clip') or other.startswith('door-clip'): continue
                        other_bounds = np.array(shape(other).bounding_box()).reshape(2,3)
                        if np.any(bounds[1]<=other_bounds[0]) or np.any(other_bounds[1]<=bounds[0]): continue
                        volume = (shape(name)^shape(other)).volume()
                        if volume > maximum: maximum,collision_pair = volume,[name,other]
            assert maximum < .025, (nodes[node_index]['name'], collision_pair, maximum)
            path_checks.append(dict(node=nodes[node_index]['name'],max_collision_mm3=round(maximum,6),parts=collision_pair))
    return dict(parts=52, hardware=8, steps=10, duration_seconds=80,
                geometry_matches_print_parts=True, final_poses_match=True,
                door_open_degrees=60, wheel_rotation_degrees=360,
                sampled_installation_paths=path_checks,
                installation_paths='illustrative; glue, thread engagement and elastic forces not simulated')
